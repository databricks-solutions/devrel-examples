"""4D reconstruction of a person from N synchronised, posed, moving cameras: every slice of a clip, on one GPU.

    python recon4d_job.py --release <folder with clips/> --clip <clip_id> --out <out folder> \
                          [--shard 0/4] [--smooth 7] [--model pi3x|stub] [--max-slices N]

Input is the release layout of the drone-swarm-4d dataset (clips/<clip>/clip.json, frames.parquet, cameras.json,
video/drone_N.mp4, masks/drone_N.mkv, optionally cloud/ to compare against). Your own capture works the same once it
is in that layout: per-frame times on one clock, camera-to-world poses, intrinsics, and a person mask per frame.

Per slice: the frame of every camera nearest the slice time goes into Pi3X with its intrinsics and pose (see
pi3x_instant.py, which is also the single-instant tool). The model's cameras are aligned to the given poses with a
Sim(3). Pass two smooths the per-slice Sim(3) over time (a centred window of --smooth slices: mean translation and
chordal-mean rotation; scale stays per slice): that is what takes the frame-to-frame shake away. Then each view's person points
are cut, fused across cameras and written in the release cloud format (int16 mm xyz + uint8 rgb, 9 bytes per point),
plus index.json, report.json and, last, manifest.json.

Runs on AIR as one task or as N independent tasks (--shard i/N): each task infers its slices plus a halo of
--smooth//2 on each side, so shards smooth exactly like a single run, and writes only its own slices.

Progress goes to MLflow the way AIR's ETA reads it: param max_steps = slices to infer, metric epoch = fraction done,
logged by MlflowClient against the run id captured at start (never through mlflow.start_run, which can consume the
injected run id and log to a new run). No MLflow: progress is printed only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import pi3x_instant as pi  # the single-instant module: model, Sim(3), person cut, fusion, cloud I/O

T0 = time.time()
RUN_ID = os.environ.get("MLFLOW_RUN_ID")  # capture now, before any library can pop it


def log(msg: str):
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


class Progress:
    """epoch = done / max_steps, through an explicit run id; never fatal."""

    def __init__(self, total: int):
        self.total, self.done, self.client, self.last = total, 0, None, 0.0
        if RUN_ID:
            try:
                from mlflow.tracking import MlflowClient

                self.client = MlflowClient()
                self.client.log_param(RUN_ID, "max_steps", total)
            except Exception as e:  # progress must never take the job down
                log(f"progress: MLflow off ({e!r})")
                self.client = None

    def step(self, **metrics):
        self.done += 1
        now = time.time()
        if now - self.last < 10 and self.done < self.total:
            return
        self.last = now
        log(f"progress {self.done}/{self.total}")
        if self.client:
            try:
                ts = int(now * 1000)
                self.client.log_metric(RUN_ID, "epoch", self.done / self.total, timestamp=ts, step=self.done)
                for k, v in metrics.items():
                    self.client.log_metric(RUN_ID, k, float(v), timestamp=ts, step=self.done)
            except Exception as e:
                log(f"progress: log failed ({e!r})")


# ---------------------------------------------------------------- inputs


def load_clip(release: Path, clip: str):
    import pyarrow.parquet as pq

    d = release / "clips" / clip
    c = json.loads((d / "clip.json").read_text())
    drones = list(c["drones"])
    index = json.loads((d / "cloud" / "index.json").read_text()) if (d / "cloud" / "index.json").exists() else None
    if index:
        slices = index["slices"] if isinstance(index, dict) else index
        times = np.array([float(s["t_s"]) for s in slices])
        ids = [int(s.get("i", k)) for k, s in enumerate(slices)]
    else:  # no reference clouds: slices at the clip's frame rate over the common time span
        fps = float(c.get("fps", 29.97))
        fr = pq.read_table(d / "frames.parquet", columns=["drone", "t_s"]).to_pandas()
        lo, hi = fr.groupby("drone").t_s.min().max(), fr.groupby("drone").t_s.max().min()
        times = np.arange(lo, hi + 1e-9, 1 / fps)
        ids = list(range(len(times)))
        slices = [dict(i=i, t_s=float(t)) for i, t in zip(ids, times, strict=True)]
    cams = json.loads((d / "cameras.json").read_text()) if (d / "cameras.json").exists() else None
    frames = pq.read_table(d / "frames.parquet").to_pylist()
    return d, drones, slices, times, ids, cams, frames


def pick_frames(frames, drones, times):
    """For each slice and drone: the nearest frame row."""
    out = []
    by = {dr: sorted((r for r in frames if r["drone"] == dr), key=lambda r: r["t_s"]) for dr in drones}
    for dr in drones:
        if not by[dr]:
            raise RuntimeError(f"frames.parquet has no rows for {dr}")
    for t in times:
        row = []
        for dr in drones:
            rs = by[dr]
            ts = np.array([r["t_s"] for r in rs])
            row.append(rs[int(np.argmin(np.abs(ts - t)))])
        out.append(row)
    return out


def decode_needed(video: Path, wanted: set[int], gray: bool = False) -> dict[int, np.ndarray]:
    """One sequential pass over a video, keeping only the wanted frame indices (exact, unlike seeks)."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    got, i, last = {}, 0, max(wanted)
    try:
        while i <= last:
            if i in wanted:
                ok, img = cap.read()
                if not ok:
                    raise RuntimeError(f"{video}: cannot decode frame {i}")
                got[i] = (img[..., 0] if img.ndim == 3 else img) > 127 if gray else img[..., ::-1].copy()
            elif not cap.grab():
                raise RuntimeError(f"{video}: ends before frame {i}")
            i += 1
    finally:
        cap.release()
    return got


def pose_of(row, cams, drones, k_pos, dr):
    if "cam_to_world" in row and row["cam_to_world"] is not None:
        return np.asarray(row["cam_to_world"], dtype=np.float64).reshape(4, 4)
    return pi.slice_cameras(cams, drones, k_pos)[drones.index(dr)]


# ---------------------------------------------------------------- smoothing


def smooth_sim3(S: list[tuple], win: int) -> list[tuple]:
    """Centred window over per-slice (s, R, t): chordal-mean R and mean t; s stays per slice (it compensates the
    model's per-instant depth scale: smoothing it made flicker worse, 1.41 -> 2.08 cm). Window shrinks at the ends."""
    if win <= 1:
        return S
    h, out = win // 2, []
    for k in range(len(S)):
        w = S[max(0, k - h): k + h + 1]
        out.append((S[k][0], pi.rot_mean([x[1] for x in w]), np.mean([x[2] for x in w], axis=0)))
    return out


# ---------------------------------------------------------------- main


def run(a) -> dict:
    scratch = Path("/local_disk0") if os.access("/local_disk0", os.W_OK) else Path(os.environ.get("TMPDIR", "/tmp"))
    scratch = scratch / f"recon4d_{a.clip}_{os.getpid()}"
    scratch.mkdir(parents=True, exist_ok=True)
    timings = {}

    t = time.time()
    d, drones, slices, times, ids, cams, frames = load_clip(Path(a.release), a.clip)
    n_all = len(slices) if not a.max_slices else min(a.max_slices, len(slices))
    i, n = (int(x) for x in a.shard.split("/"))
    lo, hi = n_all * i // n, n_all * (i + 1) // n           # slices this task writes
    h = a.smooth // 2
    ilo, ihi = max(0, lo - h), min(n_all, hi + h)            # slices this task infers (halo for smoothing)
    rows = pick_frames(frames, drones, times[ilo:ihi])
    log(f"{a.clip}: {len(drones)} cameras, writing slices {lo}..{hi - 1} of {n_all}, inferring {ilo}..{ihi - 1}")

    # copy inputs to local disk once, then decode each video in one pass (volume FUSE seeks are slow)
    rgb, msk = {}, {}
    for v, dr in enumerate(drones):
        want = {int(r[v]["frame_index"]) for r in rows}
        vid, m = scratch / f"{dr}.mp4", scratch / f"{dr}.mkv"
        shutil.copyfile(d / "video" / f"{dr}.mp4", vid)
        shutil.copyfile(d / "masks" / f"{dr}.mkv", m)
        rgb[dr], msk[dr] = decode_needed(vid, want), decode_needed(m, want, gray=True)
    timings["inputs"] = round(time.time() - t, 1)
    log(f"inputs ready in {timings['inputs']}s")

    t = time.time()
    model = None
    if a.model == "pi3x":
        model = pi.Pi3XModel(a.device, "poses")
    timings["model"] = round(time.time() - t, 1)

    # pass 1: infer every slice, keep model-frame outputs (small: points are cut later) and the per-slice Sim(3)
    t = time.time()
    prog = Progress(ihi - ilo)
    raw, S, align = [], [], []
    for j, k in enumerate(range(ilo, ihi)):
        views = []
        for v, dr in enumerate(drones):
            r = rows[j][v]
            img, mk = rgb[dr][int(r["frame_index"])], msk[dr][int(r["frame_index"])]
            K = np.array([[r["fx"], 0, r["cx"]], [0, r["fy"], r["cy"]], [0, 0, 1]], dtype=np.float64)
            K[0] *= img.shape[1] / float(r["width"])
            K[1] *= img.shape[0] / float(r["height"])
            if mk.shape != img.shape[:2]:
                mk = cv2.resize(mk.astype(np.uint8), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
            views.append(dict(rgb=img, mask=mk, K=K, c2w=pose_of(r, cams, drones, k, dr)))
        Wn, Hn = views[0]["rgb"].shape[1], views[0]["rgb"].shape[0]
        Wm, Hm = pi.model_size(Wn, Hn)                        # ~672 long side: Pi3X's training size; more is worse
        imgs = [cv2.resize(v["rgb"], (Wm, Hm), interpolation=cv2.INTER_AREA) for v in views]
        Ks = np.stack([v["K"] * np.array([[Wm / Wn], [Hm / Hn], [1]]) for v in views])
        Pr = np.stack([v["c2w"] for v in views])
        m = model if model else pi.StubModel(d / "cloud" / slices[k]["file"])
        lp, conf, Pm = m(imgs, Ks, Pr)
        if not (np.isfinite(lp).mean() > 0.99 and np.isfinite(Pm).all()):
            raise RuntimeError(f"slice {ids[k]}: non-finite model output")
        s, R, tt = pi.sim3(Pm, Pr)
        rot = max(pi.angle_deg((R @ Pm[v, :3, :3]).T @ Pr[v, :3, :3]) for v in range(len(views)))
        raw.append((lp.astype(np.float16), conf.astype(np.float16), Pm, views))
        S.append((s, R, tt))
        align.append(round(rot, 3))
        prog.step(max_cam_rot_err_deg=rot)
    timings["infer"] = round(time.time() - t, 1)
    del model

    # pass 2: smooth the alignment over time, cut, fuse, write. Each slice is written whole as soon as it is ready.
    t = time.time()
    S = smooth_sim3(S, a.smooth)
    out = Path(a.out) / a.clip / "cloud"
    written, chamfer = [], []
    for j, k in enumerate(range(ilo, ihi)):
        if not lo <= k < hi:
            continue
        lp, conf, Pm, views = raw[j]
        s, R, tt = S[j]
        P, C, src = [], [], []
        for v, view in enumerate(views):
            X, col = pi.person_points(lp[v].astype(np.float32), conf[v].astype(np.float32), view["mask"], view["rgb"],
                                      Pm[v], a.up, a.min_conf, 1.0 / s)
            P.append(s * X @ R.T + tt)
            C.append(col)
            src.append(np.full(len(X), v))
        X, Cc, Sv = np.concatenate(P), np.concatenate(C), np.concatenate(src)
        if a.fuse_cm > 0 and len(drones) > 1 and len(X):
            X, _ = pi.fuse(X, Sv, a.fuse_cm / 100)
        if not len(X):
            raise RuntimeError(f"slice {ids[k]}: no person points (masks? times?)")
        name = f"s{ids[k]:03d}.bin"
        pi.put_whole(pi.write_cloud(X, Cc), out / name)
        ref = d / "cloud" / slices[k].get("file", name)
        cmp = pi.compare(X, pi.read_cloud(ref)[0]) if a.compare and ref.exists() else {}
        if cmp.get("chamfer_cm") is not None:
            chamfer.append(cmp["chamfer_cm"])
        written.append(dict(i=ids[k], t_s=round(float(times[k]), 4), file=name, n=int(len(X)),
                            scale=round(s, 5), cam_rot_err_deg=align[j], chamfer_cm=cmp.get("chamfer_cm")))
    timings["write"] = round(time.time() - t, 1)

    report = dict(format="multiview-4d/run/v1", clip=a.clip, shard=a.shard, slices=[lo, hi], n_cameras=len(drones),
                  settings=dict(smooth=a.smooth, up=a.up, min_conf=a.min_conf, fuse_cm=a.fuse_cm, model=a.model),
                  median_points=int(np.median([w["n"] for w in written])) if written else 0,
                  median_chamfer_cm=float(np.median(chamfer)) if chamfer else None, seconds=timings)
    base = Path(a.out) / a.clip
    pi.put_whole(json.dumps(dict(fps=float(1 / np.median(np.diff(times))) if len(times) > 1 else None, slices=written),
                            indent=1).encode(), base / f"index_shard{i}of{n}.json")
    pi.put_whole(json.dumps(report, indent=1).encode(), base / f"report_shard{i}of{n}.json")
    # manifest last: a consumer that sees it knows this shard's files are complete
    pi.put_whole(json.dumps(dict(shard=a.shard, files=[w["file"] for w in written], status="done")).encode(),
                 base / f"manifest_shard{i}of{n}.json")
    shutil.rmtree(scratch, ignore_errors=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", required=True)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", default="0/1", help="i/N: this task writes the i-th of N contiguous slice ranges")
    ap.add_argument("--smooth", type=int, default=7, help="centred window (slices) for the per-slice Sim(3); 1 = off")
    ap.add_argument("--max-slices", type=int, default=0, help="only the first N slices (smoke tests)")
    ap.add_argument("--model", choices=["pi3x", "stub"], default="pi3x")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--up", type=int, default=2)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--fuse-cm", type=float, default=4.0)
    ap.add_argument("--compare", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--timeout-s", type=int, default=55 * 60)
    a = ap.parse_args()
    if a.device == "auto":
        try:
            import torch

            a.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        except ImportError:
            a.device = "cpu"
    threading.Timer(a.timeout_s, lambda: (log("watchdog timeout"), os._exit(3))).start()
    log(f"recon4d {a.clip} shard={a.shard} model={a.model} device={a.device} run_id={RUN_ID}")
    rc = 0
    try:
        r = run(a)
        print(json.dumps(r), flush=True)
    except Exception as e:
        import traceback

        traceback.print_exc()
        log(f"FAILED: {e!r}")
        rc = 1
    sys.stdout.flush()
    os._exit(rc)  # a stray thread must never keep a billed GPU alive


if __name__ == "__main__":
    main()

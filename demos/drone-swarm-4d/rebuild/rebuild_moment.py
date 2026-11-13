"""Rebuild one moment of a drone swarm 4D clip with Pi3X, and compare it with the released slice.

    python rebuild_moment.py --release /Volumes/<catalog>/<schema>/release_files/release --clip clip1_three_drones \
                             --t 4.0 --out /Volumes/<catalog>/<schema>/release_files/rebuilds

For the slice nearest --t: every drone's video frame at that time, its person mask and its released pose and
intrinsics go into Pi3X (yyfz233/Pi3X, conditioned on the intrinsics and poses) as one multi-view instant. The
model's cameras are aligned to the released ones with a Sim(3) (rotation first, then scale and translation from the
camera centres), the person's pixels are kept through the masks, and the points are written in the release's cloud
format (int16 x, y, z mm + uint8 r, g, b; 9 bytes per point) to OUT/<clip>/sNNN.bin, followed by OUT/<clip>/sNNN.json
with the comparison against the released slice (Chamfer distance, point counts) and the run's settings.

--model stub replaces Pi3X with a stand-in that renders depth from the released slice (in a deliberately different
frame and scale), to test everything else on a CPU in seconds.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

T0 = time.time()
PI3X_REPO, PI3X_REVISION = "yyfz233/Pi3X", "bb1deea4d7423de5b30691739cb451a3f57dc1d5"


def log(msg: str):
    print(f"[{time.time() - T0:7.1f}s] {msg}", flush=True)


class Stage:
    """Logs the start and end of each stage and records its duration."""

    timings: dict[str, float] = {}

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.t = time.time()
        log(f"stage {self.name}: start")

    def __exit__(self, kind, err, tb):
        dt = round(time.time() - self.t, 2)
        Stage.timings[self.name] = dt
        log(f"stage {self.name}: {'done' if kind is None else 'FAILED'} in {dt:.1f}s")


def put_whole(data: bytes, dest: Path):
    """Whole-file write, then rename (volumes cannot append; rename-over can be refused: fall back to copy)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, dest)
    except OSError:
        shutil.copyfile(tmp, dest)
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- release inputs


def m16(v) -> np.ndarray:
    if isinstance(v, dict):
        v = v.get("cam_to_world", v.get("c2w"))
    return np.asarray(v, dtype=np.float64).reshape(4, 4)


def slice_cameras(cams, drones: list[str], k: int) -> np.ndarray:
    """cameras.json -> (V, 4, 4) cam_to_world of slice k. Accepts per-slice or per-drone layouts."""
    sl = cams.get("slices") if isinstance(cams, dict) else cams
    if isinstance(sl, list):
        s = sl[k]
        per = s.get("cam_to_world") or s.get("cameras") or s.get("drones") or s
        return np.stack([m16(per[d]) for d in drones])
    src = cams.get("cam_to_world") or cams.get("cameras") or cams.get("drones") or cams
    return np.stack([m16(src[d][k]) for d in drones])


def read_cloud(path: Path) -> tuple[np.ndarray, np.ndarray]:
    a = np.fromfile(path, dtype=[("p", "<i2", 3), ("c", "u1", 3)])
    return a["p"].astype(np.float64) / 1000.0, a["c"].copy()


def write_cloud(P: np.ndarray, C: np.ndarray) -> bytes:
    a = np.zeros(len(P), dtype=[("p", "<i2", 3), ("c", "u1", 3)])
    a["p"] = np.clip(np.round(P * 1000), -32768, 32767)
    a["c"] = C
    return a.tobytes()


def decode_frames(video: Path, wanted: set[int], gray: bool = False) -> dict[int, np.ndarray]:
    """The wanted frame indices of a video, in one sequential pass (exact, unlike container seeks): BGR, or 2-D gray.
    Decoded by imageio-ffmpeg's static ffmpeg in a subprocess: OpenCV in the AIR base image has no FFmpeg, and PyAV's
    bundled OpenSSL aborts on the hosts' FIPS self-test."""
    import imageio_ffmpeg

    got, last = {}, max(wanted)
    frames = imageio_ffmpeg.read_frames(str(video), pix_fmt="gray" if gray else "bgr24", bpp=1 if gray else 3)
    try:
        meta = next(frames)
        w, h = meta["size"]
        for i, buf in enumerate(frames):
            if i in wanted:
                a = np.frombuffer(buf, np.uint8)
                got[i] = a.reshape(h, w).copy() if gray else a.reshape(h, w, 3).copy()
            if i >= last:
                break
    finally:
        frames.close()
    missing = sorted(wanted - got.keys())
    if missing:
        raise RuntimeError(f"{video}: ends before frame {missing[0]}")
    return got


def read_frame(video: Path, index: int, gray: bool = False) -> np.ndarray:
    """Frame `index` of a video: BGR, or 2-D gray."""
    return decode_frames(video, {index}, gray)[index]


def load_inputs(release: Path, clip: str, t: float | None, slice_i: int | None, scratch: Path):
    import pyarrow.parquet as pq

    d = release / "clips" / clip
    c = json.loads((d / "clip.json").read_text())
    drones = list(c["drones"])
    index = json.loads((d / "cloud" / "index.json").read_text())
    slices = index if isinstance(index, list) else next(
        index[k] for k in ("slices", "index", "items", "frames") if isinstance(index.get(k), list))
    times = np.array([float(s["t_s"]) for s in slices])
    k = slice_i if slice_i is not None else int(np.argmin(np.abs(times - t)))
    if not 0 <= k < len(slices):
        raise ValueError(f"slice {k} out of range (0..{len(slices) - 1})")
    ts = float(times[k])
    c2w = slice_cameras(json.loads((d / "cameras.json").read_text()), drones, k)
    fr = pq.read_table(d / "frames.parquet").to_pylist()
    views = []
    for v, drone in enumerate(drones):
        rows = [r for r in fr if r["drone"] == drone]
        if not rows:
            raise RuntimeError(f"frames.parquet has no rows for {drone}")
        r = min(rows, key=lambda r: abs(r["t_s"] - ts))
        # copy the two small inputs to local disk before decoding (volume FUSE reads are slow to seek)
        vid, msk = scratch / f"{drone}.mp4", scratch / f"{drone}_mask.mkv"
        shutil.copyfile(d / "video" / f"{drone}.mp4", vid)
        shutil.copyfile(d / "masks" / f"{drone}.mkv", msk)
        img = read_frame(vid, int(r["frame_index"]))
        m = read_frame(msk, int(r["frame_index"]), gray=True)
        m = (m[..., 0] if m.ndim == 3 else m) > 127
        K = np.array([[r["fx"], 0, r["cx"]], [0, r["fy"], r["cy"]], [0, 0, 1]], dtype=np.float64)
        sx, sy = img.shape[1] / float(r["width"]), img.shape[0] / float(r["height"])   # intrinsics are for (width, height)
        K[0] *= sx
        K[1] *= sy
        if m.shape != img.shape[:2]:
            m = cv2.resize(m.astype(np.uint8), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        views.append(dict(drone=drone, frame_index=int(r["frame_index"]), frame_t_s=float(r["t_s"]), rgb=img[..., ::-1].copy(),
                          mask=m, K=K, c2w=c2w[v]))
        log(f"{drone}: frame {r['frame_index']} at {r['t_s']:.3f}s (slice {ts:.3f}s), "
            f"{img.shape[1]}x{img.shape[0]}, mask {m.mean() * 100:.1f}%")
    cloud = d / "cloud" / slices[k]["file"]
    return dict(clip=clip, drones=drones, slice=int(slices[k].get("i", k)), slice_pos=k, t_s=ts, views=views, release_cloud=cloud)


# ---------------------------------------------------------------- models
# A model maps V images (uint8, model size) + intrinsics at that size + released poses to, per view, points in its own
# camera frame (V, H, W, 3), a confidence (V, H, W) and its own cameras (V, 4, 4) in its own world frame and scale.


def model_size(w: int, h: int, long_side: int = 672) -> tuple[int, int]:
    """Pi3X's default: about 255 k pixels, sides multiples of its 14-pixel patch."""
    s = long_side / max(w, h)
    return int(round(w * s / 14)) * 14, int(round(h * s / 14)) * 14


class Pi3XModel:
    def __init__(self, device: str, condition: str = "poses"):
        import torch
        from pi3.models.pi3x import Pi3X

        self.torch, self.device, self.condition = torch, device, condition
        self.m = Pi3X.from_pretrained(PI3X_REPO, revision=PI3X_REVISION).to(device).eval()
        log(f"Pi3X {PI3X_REVISION[:8]} on {device}"
            + (f", {torch.cuda.memory_allocated() / 2**30:.1f} GiB" if device == "cuda" else ""))

    def __call__(self, imgs, K, c2w):
        torch = self.torch
        V = len(imgs)
        x = torch.from_numpy(np.stack(imgs)).permute(0, 3, 1, 2).float().div(255)[None].to(self.device)
        kw = {}   # condition: "poses" = intrinsics + poses, "intrinsics" = intrinsics only, "none" = images only
        if self.condition in ("poses", "intrinsics"):
            kw["intrinsics"] = torch.tensor(K, dtype=torch.float32)[None].to(self.device)
            kw["mask_add_ray"] = torch.ones((1, V), dtype=torch.bool, device=self.device)
        if self.condition == "poses":
            kw["poses"] = torch.tensor(c2w, dtype=torch.float32)[None].to(self.device)
            kw["mask_add_pose"] = torch.ones((1, V), dtype=torch.bool, device=self.device)
        with torch.inference_mode():
            if self.device == "cuda":
                with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                    r = self.m(imgs=x, **kw)
            else:
                r = self.m(imgs=x, **kw)
        lp = r["local_points"][0].float().cpu().numpy()
        conf = torch.sigmoid(r["conf"][0, ..., 0].float()).cpu().numpy()
        return lp, conf, r["camera_poses"][0].float().cpu().numpy().astype(np.float64)


class StubModel:
    """Stand-in for tests: depth rendered from the released slice, in a model frame of its own (rotated, shifted and
    scaled by 0.6), so the alignment and everything downstream are exercised."""

    def __init__(self, cloud: Path):
        self.P, _ = read_cloud(cloud)
        a = 0.7
        self.R0 = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1.0]])
        self.s0, self.t0 = 0.6, np.array([3.0, -1.0, 0.5])

    def __call__(self, imgs, K, c2w):
        V, (H, W) = len(imgs), imgs[0].shape[:2]
        lp, conf, poses = np.zeros((V, H, W, 3)), np.zeros((V, H, W)), np.zeros((V, 4, 4))
        for v in range(V):
            w2c = np.linalg.inv(c2w[v])
            X = self.P @ w2c[:3, :3].T + w2c[:3, 3]
            X = X[X[:, 2] > 0.05]
            u = np.round(K[v][0, 0] * X[:, 0] / X[:, 2] + K[v][0, 2]).astype(int)
            w = np.round(K[v][1, 1] * X[:, 1] / X[:, 2] + K[v][1, 2]).astype(int)
            z = np.full((H, W), 50.0)
            for du in (-1, 0, 1):   # small splats close the gaps between points
                for dv in (-1, 0, 1):
                    uu, ww = u + du, w + dv
                    ok = (uu >= 0) & (uu < W) & (ww >= 0) & (ww < H)
                    np.minimum.at(z, (ww[ok], uu[ok]), X[ok, 2])
            ys, xs = np.mgrid[0:H, 0:W]
            ray = np.stack([(xs - K[v][0, 2]) / K[v][0, 0], (ys - K[v][1, 2]) / K[v][1, 1], np.ones((H, W))], -1)
            lp[v] = ray * z[..., None] * self.s0
            conf[v] = (z < 50).astype(float)
            poses[v] = np.eye(4)
            poses[v][:3, :3] = self.R0 @ c2w[v][:3, :3]
            poses[v][:3, 3] = self.s0 * self.R0 @ c2w[v][:3, 3] + self.t0
        return lp, conf, poses


# ---------------------------------------------------------------- geometry


def rot_mean(Rs) -> np.ndarray:
    u, _, vt = np.linalg.svd(sum(Rs))
    R = u @ vt
    if np.linalg.det(R) < 0:
        R = u @ np.diag([1, 1, -1]) @ vt
    return R


def sim3(Pm: np.ndarray, Pr: np.ndarray):
    """Model and released cam_to_world (V, 4, 4) of the same cameras -> s, R, t with X_release = s R X_model + t.
    Rotation first (chordal mean of R_rel R_model^T), then scale and translation from the camera centres."""
    R = rot_mean([Pr[i, :3, :3] @ Pm[i, :3, :3].T for i in range(len(Pm))])
    cm, cr = Pm[:, :3, 3], Pr[:, :3, 3]
    a, b = cm - cm.mean(0), cr - cr.mean(0)
    s = float(np.sum((a @ R.T) * b) / max(np.sum(a * a), 1e-12))
    return s, R, cr.mean(0) - s * R @ cm.mean(0)


def angle_deg(R: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def person_points(lp, conf, mask, rgb, cam, up: int, min_conf: float, gate: float):
    """One view: model-frame camera points (H, W, 3) -> person points in the model world and their colours.
    Mask eroded by one model pixel, depth edges removed, and points farther than `gate` (model units) from the median
    person depth dropped."""
    H, W = lp.shape[:2]
    Hu, Wu = H * up, W * up
    z = np.maximum(lp[..., 2], 1e-4)
    lg = np.log(z)
    edge = np.zeros((H, W), bool)
    gy, gx = np.abs(np.diff(lg, axis=0)) > 0.02, np.abs(np.diff(lg, axis=1)) > 0.02
    edge[1:] |= gy
    edge[:-1] |= gy
    edge[:, 1:] |= gx
    edge[:, :-1] |= gx
    edge = cv2.dilate(edge.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    m = cv2.resize(mask.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    keep = cv2.erode(m, np.ones((3, 3), np.uint8)) > 0
    keep &= ~edge & (conf >= min_conf)
    if m.any():
        keep &= np.abs(z - np.median(z[m > 0])) < gate
    lpu = cv2.resize(lp.astype(np.float32), (Wu, Hu), interpolation=cv2.INTER_LINEAR)
    ku = cv2.resize(keep.astype(np.uint8), (Wu, Hu), interpolation=cv2.INTER_NEAREST) > 0
    ys, xs = np.nonzero(ku)
    X = lpu[ys, xs].astype(np.float64)
    X = X @ cam[:3, :3].T + cam[:3, 3]
    Hn, Wn = rgb.shape[:2]
    u = np.clip(np.round((xs + 0.5) * Wn / Wu - 0.5).astype(int), 0, Wn - 1)
    v = np.clip(np.round((ys + 0.5) * Hn / Hu - 0.5).astype(int), 0, Hn - 1)
    return X, rgb[v, u]


def fuse(X: np.ndarray, src: np.ndarray, tau: float) -> tuple[np.ndarray, int]:
    """Each point with another drone's points within tau moves to the midpoint with their mean."""
    from scipy.spatial import cKDTree

    acc, cnt = np.zeros_like(X), np.zeros(len(X))
    for v in np.unique(src):
        Xv = X[src == v]
        if len(Xv) < 10:
            continue
        dd, ii = cKDTree(Xv).query(X, k=4, distance_upper_bound=tau)
        ok = (src != v)[:, None] & np.isfinite(dd)
        for c in range(4):
            o = ok[:, c]
            acc[o] += Xv[ii[o, c]]
            cnt[o] += 1
    f = cnt > 0
    Y = X.copy()
    Y[f] = 0.5 * X[f] + 0.5 * acc[f] / cnt[f, None]
    return Y, int(f.sum())


def compare(A: np.ndarray, B: np.ndarray) -> dict:
    """Rebuild A vs release B, in cm: nearest-neighbour distances both ways; Chamfer = mean of the two means."""
    from scipy.spatial import cKDTree

    if not len(A) or not len(B):
        return dict(n_points=len(A), n_release=len(B), chamfer_cm=None)
    ab = cKDTree(B).query(A)[0] * 100
    ba = cKDTree(A).query(B)[0] * 100
    def q(x):
        return dict(mean=round(float(x.mean()), 2), median=round(float(np.median(x)), 2), p90=round(float(np.percentile(x, 90)), 2))

    return dict(n_points=len(A), n_release=len(B), chamfer_cm=round(float((ab.mean() + ba.mean()) / 2), 2),
                rebuild_to_release_cm=q(ab), release_to_rebuild_cm=q(ba),
                within_2cm=dict(rebuild=round(float((ab < 2).mean()), 3), release=round(float((ba < 2).mean()), 3)))


# ---------------------------------------------------------------- main


def rebuild(a) -> dict:
    scratch = Path("/local_disk0") if os.access("/local_disk0", os.W_OK) else Path(os.environ.get("TMPDIR", "/tmp"))
    scratch = scratch / f"rebuild_{a.clip}_{os.getpid()}"
    scratch.mkdir(parents=True, exist_ok=True)
    with Stage("inputs"):
        inp = load_inputs(Path(a.release), a.clip, a.t, a.slice, scratch)
        views = inp["views"]
        log(f"{a.clip}: slice {inp['slice']} at {inp['t_s']:.3f}s, {len(views)} views")
    Wn, Hn = views[0]["rgb"].shape[1], views[0]["rgb"].shape[0]
    Wm, Hm = (int(v) for v in a.res.split("x")) if a.res else model_size(Wn, Hn)
    with Stage("model"):
        model = StubModel(inp["release_cloud"]) if a.model == "stub" else Pi3XModel(a.device, a.condition)
    with Stage("infer"):
        imgs = [cv2.resize(v["rgb"], (Wm, Hm), interpolation=cv2.INTER_AREA) for v in views]
        Ks = np.stack([v["K"] * np.array([[Wm / v["rgb"].shape[1]], [Hm / v["rgb"].shape[0]], [1]]) for v in views])
        Pr = np.stack([v["c2w"] for v in views])
        lp, conf, Pm = model(imgs, Ks, Pr)
        if not (np.isfinite(lp).mean() > 0.99 and np.isfinite(Pm).all()):
            raise RuntimeError("non-finite model output")
        log(f"model output {Wm}x{Hm}, median depth {np.median(lp[..., 2]):.2f} (model units)")
    with Stage("align"):
        s, R, t = sim3(Pm, Pr)
        cams = []
        for v in range(len(views)):
            c = np.eye(4)
            c[:3, :3] = R @ Pm[v, :3, :3]
            c[:3, 3] = s * R @ Pm[v, :3, 3] + t
            cams.append(c)
        rot_err = [round(angle_deg(cams[v][:3, :3].T @ Pr[v, :3, :3]), 3) for v in range(len(views))]
        ctr_err = [round(float(np.linalg.norm(cams[v][:3, 3] - Pr[v, :3, 3])) * 100, 2) for v in range(len(views))]
        log(f"Sim(3) scale {s:.4f}; camera rotation error {rot_err} deg, centre error {ctr_err} cm")
    with Stage("person"):
        pts, cols, src = [], [], []
        for v, view in enumerate(views):
            X, C = person_points(lp[v], conf[v], view["mask"], view["rgb"], Pm[v], a.up, a.min_conf, 1.0 / s)   # 1 m
            X = s * X @ R.T + t
            pts.append(X)
            cols.append(C)
            src.append(np.full(len(X), v))
            log(f"{view['drone']}: {len(X)} person points")
        X, C, S = np.concatenate(pts), np.concatenate(cols), np.concatenate(src)
        n_fused = 0
        if a.fuse_cm > 0 and len(views) > 1 and len(X):
            X, n_fused = fuse(X, S, a.fuse_cm / 100)
        if not len(X):
            raise RuntimeError("no person points: check the masks and the slice time")
    with Stage("compare"):
        Prl, _ = read_cloud(inp["release_cloud"])
        cmp = compare(X, Prl)
        log(f"{len(X)} points (release {len(Prl)}), Chamfer {cmp['chamfer_cm']} cm")
    with Stage("write"):
        out = Path(a.out) / a.clip
        name = f"s{inp['slice']:03d}"
        put_whole(write_cloud(X, C), out / f"{name}.bin")
        report = dict(
            format="drone-swarm-4d/rebuild/v1", clip=a.clip, slice=inp["slice"], t_s=inp["t_s"],
            model=dict(name="stub" if a.model == "stub" else PI3X_REPO, revision=None if a.model == "stub" else PI3X_REVISION,
                       conditioning=a.condition, size=[Wm, Hm], device=a.device),
            views=[dict(drone=v["drone"], frame_index=v["frame_index"], frame_t_s=v["frame_t_s"]) for v in views],
            n_points=int(len(X)), n_per_drone={views[v]["drone"]: int((S == v).sum()) for v in range(len(views))},
            n_fused=n_fused, settings=dict(up=a.up, min_conf=a.min_conf, fuse_cm=a.fuse_cm),
            alignment=dict(scale=round(s, 5), camera_rotation_error_deg=rot_err, camera_centre_error_cm=ctr_err),
            comparison=cmp, seconds=Stage.timings,
            versions=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__))
        put_whole(json.dumps(report, indent=1).encode(), out / f"{name}.json")
        log(f"wrote {out / name}.bin and .json")
    shutil.rmtree(scratch, ignore_errors=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", required=True, help="release folder: the one holding clips/")
    ap.add_argument("--clip", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--t", type=float, help="time in seconds on the clip clock; the nearest slice is rebuilt")
    g.add_argument("--slice", type=int, help="slice position in cloud/index.json")
    ap.add_argument("--out", required=True, help="rebuilds folder; writes OUT/<clip>/sNNN.bin and sNNN.json")
    ap.add_argument("--model", choices=["pi3x", "stub"], default="pi3x")
    ap.add_argument("--device", default="auto", help="cuda, mps, cpu or auto")
    ap.add_argument("--condition", choices=["poses", "intrinsics", "none"], default="poses",
                    help="what Pi3X is given besides the images: released intrinsics and poses, intrinsics only, or nothing")
    ap.add_argument("--res", default="", help="model input WxH (multiples of 14); default about 672 on the long side")
    ap.add_argument("--up", type=int, default=2, help="point-map upsampling before extraction")
    ap.add_argument("--min-conf", type=float, default=0.0, help="drop pixels below this confidence (0..1)")
    ap.add_argument("--fuse-cm", type=float, default=4.0, help="cross-drone midpoint fusion radius; 0 = off")
    ap.add_argument("--timeout-s", type=int, default=25 * 60)
    a = ap.parse_args()
    if a.device == "auto":
        try:
            import torch

            a.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        except ImportError:
            a.device = "cpu"
    # a hard stop inside the job too, in addition to the platform's timeout
    threading.Timer(a.timeout_s, lambda: (log("watchdog timeout"), os._exit(3))).start()
    log(f"rebuild {a.clip} t={a.t} slice={a.slice} model={a.model} device={a.device}")
    rc = 0
    try:
        r = rebuild(a)
        print(json.dumps(dict(n_points=r["n_points"], comparison=r["comparison"], seconds=r["seconds"])), flush=True)
    except Exception as e:   # report, then exit non-zero; never leave a GPU running
        import traceback

        traceback.print_exc()
        log(f"FAILED: {e!r}")
        rc = 1
    sys.stdout.flush()
    os._exit(rc)   # skip interpreter teardown: stray threads must not keep a billed GPU alive


if __name__ == "__main__":
    main()

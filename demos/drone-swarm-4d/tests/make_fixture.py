"""Build a tiny synthetic release in the layout of the Hugging Face dataset, for local tests.

    python tests/make_fixture.py [OUT_DIR]        # default: tests/fixture/hf

Two clips with the real clip ids, but small: a few seconds at 10 fps, 320x180 videos, a few thousand
person points per slice. The "person" is a walking figure of coloured ellipsoids; the videos are its
rendering from each drone's camera, so poses, intrinsics, masks and clouds all agree. Needs numpy,
pyarrow and ffmpeg (libx264, libx265, ffv1).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(7)

CLIPS = [
    dict(id="clip1_three_drones", title="Three drones, one walk", drones=3, seconds=2.0, fps=10.0, size=(320, 180),
         full=None, radius=3.6, height=2.2),
    dict(id="walk_4k", title="Two drones, a walk filmed in 4K", drones=2, seconds=1.6, fps=10.0, size=(320, 180),
         full=(640, 360), radius=4.0, height=2.6),
]


def body(t: float, n: int = 2600) -> tuple[np.ndarray, np.ndarray]:
    """Points (n, 3) in metres, z up, and colours (n, 3) uint8 of a figure walking along +x at 1 m/s."""
    parts = [  # centre (x, y, z), radii, colour, share of points
        ((0.0, 0.0, 1.25), (0.16, 0.22, 0.30), (40, 110, 190), 0.30),   # torso
        ((0.0, 0.0, 1.68), (0.11, 0.11, 0.13), (225, 180, 150), 0.12),  # head
        ((0.0, 0.10, 0.48), (0.08, 0.08, 0.45), (60, 60, 70), 0.18),    # leg L
        ((0.0, -0.10, 0.48), (0.08, 0.08, 0.45), (60, 60, 70), 0.18),   # leg R
        ((0.0, 0.29, 1.22), (0.05, 0.05, 0.30), (40, 110, 190), 0.11),  # arm L
        ((0.0, -0.29, 1.22), (0.05, 0.05, 0.30), (40, 110, 190), 0.11),  # arm R
    ]
    swing = 0.35 * np.sin(2 * np.pi * 0.9 * t)
    pts, cols = [], []
    for k, (c, r, col, share) in enumerate(parts):
        m = int(n * share)
        u = RNG.normal(size=(m, 3))
        u /= np.linalg.norm(u, axis=1, keepdims=True)
        p = u * np.array(r) + np.array(c)
        if k in (2, 3, 4, 5):  # limbs swing about the hip / shoulder
            sgn = (1 if k in (2, 5) else -1) * swing
            pivot = np.array([0, c[1], 0.95 if k < 4 else 1.50])
            a = p - pivot
            ca, sa = np.cos(sgn), np.sin(sgn)
            p = pivot + np.stack([ca * a[:, 0] + sa * a[:, 2], a[:, 1], -sa * a[:, 0] + ca * a[:, 2]], 1)
        pts.append(p)
        cols.append(np.clip(np.array(col) + RNG.normal(0, 12, (m, 3)), 0, 255))
    P = np.concatenate(pts)
    P[:, 0] += -0.8 + 1.0 * t
    return P, np.concatenate(cols).astype(np.uint8)


def look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    """cam_to_world 4x4, OpenCV camera (x right, y down, z forward)."""
    z = target - eye
    z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, y, z, eye
    return M


def render(P, C, c2w, K, size):
    """Splat points into an image with a z-buffer. Returns rgb (H, W, 3) uint8 and the keep mask (H, W) bool."""
    W, H = size
    w2c = np.linalg.inv(c2w)
    X = P @ w2c[:3, :3].T + w2c[:3, 3]
    ok = X[:, 2] > 0.1
    X, C = X[ok], C[ok]
    u = K[0, 0] * X[:, 0] / X[:, 2] + K[0, 2]
    v = K[1, 1] * X[:, 1] / X[:, 2] + K[1, 2]
    img = np.zeros((H, W, 3), np.uint8)
    zb = np.full((H, W), np.inf)
    r = max(1, int(round(W / 320)))
    for du in range(-r, r + 1):
        for dv in range(-r, r + 1):
            uu, vv = np.round(u).astype(int) + du, np.round(v).astype(int) + dv
            m = (uu >= 0) & (uu < W) & (vv >= 0) & (vv < H)
            for i in np.flatnonzero(m)[np.argsort(-X[m, 2])]:   # far to near: near points win
                if X[i, 2] < zb[vv[i], uu[i]]:
                    zb[vv[i], uu[i]] = X[i, 2]
                    img[vv[i], uu[i]] = C[i]
    return img, np.isfinite(zb)


def encode(frames, path: Path, fps: float, codec: str, gray: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    H, W = frames[0].shape[:2]
    pix_in = "gray" if gray else "rgb24"
    args = {"h264": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", "-g", "10"],
            "h265": ["-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-x265-params", "log-level=error"],
            "ffv1": ["-c:v", "ffv1", "-pix_fmt", "gray"]}[codec]
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix_in, "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", *args, str(path)]
    subprocess.run(cmd, input=b"".join(f.tobytes() for f in frames), check=True)


def write_cloud(path: Path, P, C):
    rec = np.zeros(len(P), dtype=[("x", "<i2"), ("y", "<i2"), ("z", "<i2"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    mm = np.clip(np.round(P * 1000), -32768, 32767).astype("<i2")
    rec["x"], rec["y"], rec["z"] = mm[:, 0], mm[:, 1], mm[:, 2]
    rec["r"], rec["g"], rec["b"] = C[:, 0], C[:, 1], C[:, 2]
    path.write_bytes(rec.tobytes())


def telemetry(drones, seconds):
    """Sparse wide table: drone, stream, seq, t_s and one struct column per stream (null on other streams' rows)."""
    streams = {
        "pose": (10.0, lambda t, d: dict(x_m=float(np.cos(t + d)), y_m=float(np.sin(t + d)), z_m=2.2,
                                         yaw_deg=float(30 * d + 10 * t))),
        "battery": (1.0, lambda t, d: dict(pct=float(80 - t), voltage_v=float(7.8 - 0.01 * t))),
        "gimbal": (10.0, lambda t, d: dict(pitch_deg=float(-25 - d), yaw_deg=float(30 * d))),
        "control_intent": (10.0, lambda t, d: dict(vx_mps=0.3, vy_mps=0.0, vz_mps=0.0, yaw_rate_dps=5.0, mode="orbit")),
        "frames_sent": (10.0, lambda t, d: dict(frames=int(t * 30), bytes=int(t * 30 * 40000))),
        "controller_tick": (20.0, lambda t, d: dict(dt_ms=50.0, lag_ms=float(8 + d))),
        "event": (0.5, lambda t, d: dict(kind="waypoint", detail=f"wp{int(t)}")),
    }
    rows = []
    for di, d in enumerate(drones):
        for name, (hz, f) in streams.items():
            for seq, t in enumerate(np.arange(0, seconds, 1 / hz)):
                rows.append(dict(drone=d, stream=name, seq=seq, t_s=round(float(t), 4), **{name: f(float(t), di)}))
    cols = {"drone": [], "stream": [], "seq": [], "t_s": []} | {n: [] for n in streams}
    for r in rows:
        for k in cols:
            cols[k].append(r.get(k))
    return pa.table(cols)


def build_clip(spec, root: Path):
    cid, nd, fps = spec["id"], spec["drones"], spec["fps"]
    W, H = spec["size"]
    out = root / "clips" / cid
    drones = [f"drone_{i + 1}" for i in range(nd)]
    n = int(round(spec["seconds"] * fps))
    times = [round(i / fps, 4) for i in range(n)]
    K = np.array([[0.9 * W, 0, W / 2], [0, 0.9 * W, H / 2], [0, 0, 1.0]])
    intr = {d: dict(width=W, height=H, fx=K[0, 0], fy=K[1, 1], cx=K[0, 2], cy=K[1, 2]) for d in drones}
    cams, frames_rows, idx = [], [], []
    video = {d: [] for d in drones}
    full = {d: [] for d in drones}
    masks = {d: [] for d in drones}
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    (out / "cloud").mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(times):
        P, C = body(t)
        centre = np.array([-0.8 + t, 0, 1.0])
        c2w = {}
        for di, d in enumerate(drones):
            a = 2 * np.pi * di / nd + 0.25 * t + 0.4
            eye = centre + np.array([spec["radius"] * np.cos(a), spec["radius"] * np.sin(a), spec["height"] - 1.0])
            c2w[d] = look_at(eye, centre)
            img, keep = render(P, C, c2w[d], K, (W, H))
            video[d].append(img)
            masks[d].append(np.where(keep, 255, 0).astype(np.uint8))
            if spec["full"]:
                Wf, Hf = spec["full"]
                Kf = K * np.array([[Wf / W], [Hf / H], [1]])
                full[d].append(render(P, C, c2w[d], Kf, (Wf, Hf))[0])
            frames_rows.append(dict(drone=d, frame_index=i, t_s=t, cam_to_world=[float(v) for v in c2w[d].reshape(-1)],
                                    fx=float(K[0, 0]), fy=float(K[1, 1]), cx=float(K[0, 2]), cy=float(K[1, 2]), width=W, height=H))
        cams.append(dict(i=i, t_s=t, cam_to_world={d: [round(float(v), 6) for v in c2w[d].reshape(-1)] for d in drones}))
        name = f"s{i:03d}.bin"
        write_cloud(out / "cloud" / name, P, C)
        idx.append(dict(i=i, t_s=t, file=name, n=len(P)))
        lo, hi = np.minimum(lo, P.min(0)), np.maximum(hi, P.max(0))
    for d in drones:
        encode(video[d], out / "video" / f"{d}.mp4", fps, "h264")
        encode(masks[d], out / "masks" / f"{d}.mkv", fps, "ffv1", gray=True)
        if spec["full"]:
            encode(full[d], out / "video_full" / f"{d}.mp4", fps, "h265")
    clip = dict(id=cid, title=spec["title"], n_drones=nd, drones=drones, duration_s=spec["seconds"], fps=fps,
                frame_of_reference=dict(name="local", units="m", axes="x, y horizontal, z up", origin="arbitrary point near the person"),
                slice_times_s=times, intrinsics=intr,
                camera_convention="OpenCV: x right, y down, z forward; cam_to_world is a row-major 4x4 (16 floats)")
    (out / "clip.json").write_text(json.dumps(clip, indent=1))
    (out / "cameras.json").write_text(json.dumps(dict(convention=clip["camera_convention"], slices=cams)))
    bounds = dict(min=lo.round(3).tolist(), max=hi.round(3).tolist())
    (out / "cloud" / "index.json").write_text(json.dumps(dict(slices=idx, bounds=bounds)))
    schema = pa.schema([("drone", pa.string()), ("frame_index", pa.int32()), ("t_s", pa.float64()),
                        ("cam_to_world", pa.list_(pa.float32(), 16)), ("fx", pa.float32()), ("fy", pa.float32()),
                        ("cx", pa.float32()), ("cy", pa.float32()), ("width", pa.int32()), ("height", pa.int32())])
    pq.write_table(pa.Table.from_pylist(frames_rows, schema=schema), out / "frames.parquet")
    pq.write_table(telemetry(drones, spec["seconds"]), out / "telemetry.parquet")


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "fixture" / "hf"
    root.mkdir(parents=True, exist_ok=True)
    for spec in CLIPS:
        build_clip(spec, root)
        print("built", spec["id"])
    (root / "README.md").write_text("---\nlicense: cc-by-4.0\n---\n# drone-swarm-4d (synthetic test fixture)\n")
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            b = p.read_bytes()
            files.append(dict(path=p.relative_to(root).as_posix(), bytes=len(b), sha256=hashlib.sha256(b).hexdigest()))
    (root / "manifest.json").write_text(json.dumps(dict(dataset="nick-karpov/drone-swarm-4d", files=files), indent=1))
    print(f"{len(files)} files, {sum(f['bytes'] for f in files) / 1e6:.1f} MB in {root}")


if __name__ == "__main__":
    main()

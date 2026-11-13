"""Drone swarm 4D viewer: a Databricks App that serves the three.js viewer and streams the release files.

On Databricks the files come from the Unity Catalog volume through the Files API, as the app's service
principal (the bundle grants it READ VOLUME). Locally they come from a folder:

    DRONE4D_LOCAL_DIR=~/path/to/release python app.py          # http://localhost:8000

Environment:
    DRONE4D_VOLUME       /Volumes/<catalog>/<schema>/<volume>: release under release/, rebuilds under rebuilds/
    DRONE4D_LOCAL_DIR    local release folder (the Hugging Face layout: clips/<clip_id>/...); wins over the volume
    DRONE4D_REBUILD_DIR  local folder of rebuilds (<clip_id>/sNNN.bin + .json); optional, local mode only
    DATABRICKS_APP_PORT  port to listen on (set by Databricks Apps; default 8000)
"""
from __future__ import annotations

import io
import json
import logging
import os
import posixpath
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("drone4d")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC = Path(__file__).resolve().parent / "static"
CHUNK = 1 << 20            # streaming chunk
MAX_OPEN_RANGE = 8 << 20   # an open-ended range ("bytes=N-") is answered with at most this many bytes
SMALL = 4 << 20            # files up to this size are cached in memory
CACHE_BUDGET = 256 << 20


# ---------------------------------------------------------------- storage


class NotFound(Exception):
    pass


class LocalStore:
    """A local folder. Paths are POSIX, relative to the root."""

    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()

    def describe(self) -> str:
        return f"local folder {self.root}"

    def _p(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise NotFound(rel)
        return p

    def size(self, rel: str) -> int:
        p = self._p(rel)
        if not p.is_file():
            raise NotFound(rel)
        return p.stat().st_size

    def read(self, rel: str) -> bytes:
        p = self._p(rel)
        if not p.is_file():
            raise NotFound(rel)
        return p.read_bytes()

    def read_range(self, rel: str, start: int, end: int) -> Iterator[bytes]:
        with open(self._p(rel), "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                b = f.read(min(CHUNK, left))
                if not b:
                    break
                left -= len(b)
                yield b

    def list(self, rel: str) -> list[str]:
        p = self._p(rel)
        return sorted(c.name for c in p.iterdir()) if p.is_dir() else []


class VolumeStore:
    """A folder on a Unity Catalog volume, read through the Files API with the app's credentials."""

    def __init__(self, root: str):
        from databricks.sdk import WorkspaceClient

        self.root = root.rstrip("/")
        self.w = WorkspaceClient()   # in a Databricks App: the app's service principal (OAuth M2M, injected env)

    def describe(self) -> str:
        return f"volume folder {self.root}"

    def _p(self, rel: str) -> str:
        return f"{self.root}/{rel}" if rel else self.root

    def size(self, rel: str) -> int:
        from databricks.sdk.errors import NotFound as SdkNotFound

        try:
            return int(self.w.files.get_metadata(self._p(rel)).content_length)
        except SdkNotFound as e:
            raise NotFound(rel) from e

    def read(self, rel: str) -> bytes:
        from databricks.sdk.errors import NotFound as SdkNotFound

        try:
            return self.w.files.download(self._p(rel)).contents.read()
        except SdkNotFound as e:
            raise NotFound(rel) from e

    def read_range(self, rel: str, start: int, end: int) -> Iterator[bytes]:
        # The Files API honours the HTTP Range header; the SDK's API client adds authentication.
        from urllib.parse import quote

        res = self.w.api_client.do(
            "GET", f"/api/2.0/fs/files{quote(self._p(rel))}",
            headers={"Accept": "application/octet-stream", "Range": f"bytes={start}-{end}"},
            raw=True, response_headers=["content-range"])
        body = res["contents"]
        try:
            want = end - start + 1
            if not res.get("content-range") and start:   # range ignored: skip to start
                skip = start
                while skip:
                    skip -= len(body.read(min(CHUNK, skip)))
            while want > 0:
                b = body.read(min(CHUNK, want))
                if not b:
                    break
                want -= len(b)
                yield b
        finally:
            body.close()

    def list(self, rel: str) -> list[str]:
        from databricks.sdk.errors import NotFound as SdkNotFound

        try:
            return sorted(e.name for e in self.w.files.list_directory_contents(self._p(rel) + "/"))
        except SdkNotFound:
            return []


def make_stores():
    local = os.environ.get("DRONE4D_LOCAL_DIR")
    if local:
        rb = os.environ.get("DRONE4D_REBUILD_DIR")
        return LocalStore(local), (LocalStore(rb) if rb else None)
    vol = os.environ.get("DRONE4D_VOLUME")
    if not vol:
        raise SystemExit("Set DRONE4D_VOLUME (/Volumes/<catalog>/<schema>/<volume>) or DRONE4D_LOCAL_DIR.")
    return VolumeStore(vol.rstrip("/") + "/release"), VolumeStore(vol.rstrip("/") + "/rebuilds")


RELEASE, REBUILDS = make_stores()
log.info("release: %s; rebuilds: %s", RELEASE.describe(), REBUILDS.describe() if REBUILDS else "none")


class SmallCache:
    """LRU of small, immutable release files (clouds, JSON), bounded in bytes."""

    def __init__(self, budget: int):
        self.budget, self.used, self.d, self.lock = budget, 0, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            v = self.d.get(key)
            if v is not None:
                self.d.move_to_end(key)
            return v

    def put(self, key, v: bytes):
        with self.lock:
            if key in self.d or len(v) > self.budget // 8:
                return
            self.d[key] = v
            self.used += len(v)
            while self.used > self.budget:
                self.used -= len(self.d.popitem(last=False)[1])


CACHE = SmallCache(CACHE_BUDGET)


def read_json(store, rel: str):
    key = (id(store), rel)
    b = CACHE.get(key) if store is RELEASE else None
    if b is None:
        b = store.read(rel)
        if store is RELEASE:
            CACHE.put(key, b)
    return json.loads(b)


# ---------------------------------------------------------------- release metadata


CLIP_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _slices(index) -> tuple[list[dict], dict | None]:
    """cloud/index.json: a list of {i, t_s, file, n}, or an object holding that list plus bounds."""
    if isinstance(index, list):
        return index, None
    for key in ("slices", "index", "items", "frames"):
        if isinstance(index.get(key), list):
            return index[key], index.get("bounds")
    raise ValueError("cloud/index.json: no slice list")


def _cams(cams, drones: list[str], n: int) -> dict[str, list[list[float]]]:
    """cameras.json -> {drone: [16 floats per slice]} in slice order. Accepts per-slice or per-drone layouts."""
    def m16(v):
        if isinstance(v, dict):
            v = v.get("cam_to_world", v.get("c2w"))
        if v and isinstance(v[0], list):
            v = [x for row in v for x in row]
        return [float(x) for x in v]

    out = {d: [] for d in drones}
    sl = cams.get("slices") if isinstance(cams, dict) else cams
    if isinstance(sl, list):
        for s in sl:
            per = s.get("cam_to_world") or s.get("cameras") or s.get("drones") or s
            for d in drones:
                out[d].append(m16(per[d]))
    else:
        src = cams.get("cam_to_world") or cams.get("cameras") or cams.get("drones") or cams
        for d in drones:
            out[d] = [m16(v) for v in src[d]]
    for d in drones:
        if len(out[d]) != n:
            raise ValueError(f"cameras.json: {len(out[d])} poses for {d}, {n} slices")
    return out


def _frame_times(cid: str, drones: list[str]) -> dict[str, list[float]]:
    """Per drone, the clip time of each video frame: frames.parquet frame_index i is frame i of video/<drone>.mp4."""
    import pyarrow.parquet as pq

    t = pq.read_table(io.BytesIO(RELEASE.read(f"clips/{cid}/frames.parquet")), columns=["drone", "frame_index", "t_s"])
    out: dict[str, list] = {d: [] for d in drones}
    for d, i, ts in zip(t["drone"].to_pylist(), t["frame_index"].to_pylist(), t["t_s"].to_pylist(), strict=True):
        if d in out:
            L = out[d]
            if i >= len(L):
                L.extend([None] * (i + 1 - len(L)))
            L[i] = round(float(ts), 5)
    for L in out.values():   # fill any gap from the previous frame
        for k in range(len(L)):
            if L[k] is None:
                L[k] = L[k - 1] if k else 0.0
    return out


META: dict[str, dict] = {}
META_LOCK = threading.Lock()


def clip_meta(cid: str) -> dict:
    if not CLIP_ID.match(cid):
        raise NotFound(cid)
    with META_LOCK:
        if cid in META:
            return META[cid]
    c = read_json(RELEASE, f"clips/{cid}/clip.json")
    drones = list(c["drones"])
    slices, bounds = _slices(read_json(RELEASE, f"clips/{cid}/cloud/index.json"))
    cams = _cams(read_json(RELEASE, f"clips/{cid}/cameras.json"), drones, len(slices))
    intr = c.get("intrinsics") or {}
    files = set(RELEASE.list(f"clips/{cid}/video"))
    ft = _frame_times(cid, drones)
    times = [float(s["t_s"]) for s in slices] + [v for L in ft.values() for v in L[:1] + L[-1:]]
    fps = float(c.get("fps") or 30.0)
    meta = dict(
        id=cid, title=c.get("title", cid), drones=drones, fps=fps, duration_s=float(c.get("duration_s") or 0),
        frame_of_reference=c.get("frame_of_reference") or c.get("frame"),
        camera_convention=c.get("camera_convention") or (c.get("frame_of_reference") or {}).get("camera_convention"),
        t_start=min(times), t_end=max(times) + 1 / fps,
        slices=[dict(i=int(s.get("i", k)), t_s=float(s["t_s"]), file=f"clips/{cid}/cloud/{s['file']}", n=int(s.get("n", 0)))
                for k, s in enumerate(slices)],
        bounds=bounds, cams=cams,
        intrinsics={d: {k: float(v) for k, v in (intr.get(d) or {}).items()} for d in drones},
        video={d: dict(url=f"files/release/clips/{cid}/video/{d}.mp4", frame_t=ft[d]) for d in drones if f"{d}.mp4" in files},
    )
    with META_LOCK:
        META[cid] = meta
    return meta


def rebuilds_of(cid: str) -> list[dict]:
    """Rebuilt slices for a clip: rebuilds/<clip_id>/sNNN.bin with an optional sNNN.json report."""
    if REBUILDS is None:
        return []
    names = set(REBUILDS.list(cid))
    out = []
    for n in sorted(names):
        m = re.fullmatch(r"s(\d+)\.bin", n)
        if not m:
            continue
        rep = None
        if f"s{m.group(1)}.json" in names:
            try:
                rep = json.loads(REBUILDS.read(f"{cid}/s{m.group(1)}.json"))
            except Exception as e:   # a report being written: show the cloud anyway
                log.warning("report %s/%s: %s", cid, n, e)
        out.append(dict(slice=int(m.group(1)), file=f"files/rebuilds/{cid}/{n}", report=rep))
    return out


# ---------------------------------------------------------------- HTTP

app = FastAPI(title="Drone swarm 4D", docs_url=None, redoc_url=None)


@app.exception_handler(NotFound)
async def _nf(_, e: NotFound):
    return JSONResponse({"error": f"not found: {e}"}, status_code=404)


@app.exception_handler(Exception)
async def _err(request: Request, e: Exception):
    log.exception("%s %s failed", request.method, request.url.path)
    return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/clips")
def api_clips():
    out = []
    for cid in RELEASE.list("clips"):
        try:
            c = read_json(RELEASE, f"clips/{cid}/clip.json")
        except NotFound:
            continue
        out.append(dict(id=cid, title=c.get("title", cid), n_drones=c.get("n_drones", len(c.get("drones", []))),
                        duration_s=c.get("duration_s")))
    return out


@app.get("/api/clips/{cid}")
def api_clip(cid: str):
    meta = dict(clip_meta(cid))
    meta["rebuilds"] = rebuilds_of(cid)
    return JSONResponse(meta, headers={"Cache-Control": "no-store"})


RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def serve(store, rel: str, request: Request, immutable: bool) -> Response:
    rel = posixpath.normpath(rel)
    if rel.startswith("..") or rel.startswith("/") or "/../" in rel:
        raise NotFound(rel)
    ctype = {"mp4": "video/mp4", "mkv": "video/x-matroska", "json": "application/json", "bin": "application/octet-stream",
             "parquet": "application/octet-stream", "md": "text/markdown"}.get(rel.rsplit(".", 1)[-1], "application/octet-stream")
    cache = "public, max-age=3600" if immutable else "no-cache"
    rng = request.headers.get("range")
    if not rng:
        key = (id(store), rel)
        b = CACHE.get(key) if immutable else None
        if b is None:
            size = store.size(rel)
            if size <= SMALL:
                b = store.read(rel)
                if immutable:
                    CACHE.put(key, b)
            else:
                return StreamingResponse(store.read_range(rel, 0, size - 1), media_type=ctype,
                                         headers={"Content-Length": str(size), "Accept-Ranges": "bytes", "Cache-Control": cache})
        return Response(b, media_type=ctype, headers={"Accept-Ranges": "bytes", "Cache-Control": cache})
    size = store.size(rel)
    m = RANGE.match(rng.strip())
    if not m or (not m.group(1) and not m.group(2)):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)) if m.group(2) else start + MAX_OPEN_RANGE - 1, size - 1)
    else:   # suffix range: the last N bytes
        start, end = max(0, size - int(m.group(2))), size - 1
    if start >= size or end < start:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    return StreamingResponse(store.read_range(rel, start, end), status_code=206, media_type=ctype, headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1),
        "Accept-Ranges": "bytes", "Cache-Control": cache})


@app.get("/files/release/{rel:path}")
def files_release(rel: str, request: Request):
    if not rel.startswith("clips/"):
        raise NotFound(rel)
    return serve(RELEASE, rel, request, immutable=True)


@app.get("/files/rebuilds/{rel:path}")
def files_rebuilds(rel: str, request: Request):
    if REBUILDS is None:
        raise NotFound(rel)
    return serve(REBUILDS, rel, request, immutable=False)


@app.get("/healthz")
def healthz():
    return {"ok": True, "release": RELEASE.describe(), "time": time.time()}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(HTTPException)
async def _http(_, e: HTTPException):
    return JSONResponse({"error": e.detail}, status_code=e.status_code)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))

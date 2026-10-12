"""Any video -> camera poses + sparse cloud (+ optional Gaussian splat), published progressively to a run folder.

Generic skeleton for aerial or ground video (e.g. drones, phones, robots, vehicle cameras). Pose priors are optional.

    python recon_job.py --video IN.mp4 --run RUN_DIR [--priors priors.csv] [--masks MASK_DIR]
                        [--max-frames 200] [--mapper global|incremental] [--splat-steps 0]

RUN_DIR may be a Unity Catalog volume path (/Volumes/<catalog>/<schema>/<volume>/runs/<id>). Every file
there is written whole and then renamed into place: volumes cannot append. All scratch work happens on local disk.

priors.csv (optional): header `t_s,x,y,z`, timestamps in seconds from the start of the video, positions in
metres in any local metric frame (e.g. ENU from GPS, odometry or SLAM). With priors, match pairs are predicted from
positions and the model is aligned to the priors' frame; without them, pairs come from the video order and
the model stays in COLMAP's arbitrary frame and scale.

Run folder contract: manifest.json (rewritten whole after each asset), assets/NNN_<kind>.<ext> (immutable),
events/NNNNNN.jsonl (immutable chunks), progress.json (heartbeat). A viewer polls manifest.json.
"""
from __future__ import annotations

import argparse, bisect, csv, json, math, os, re, shutil, subprocess, sys, threading, time
from pathlib import Path

T0 = time.time()


def wall():
    return round(time.time() - T0, 2)


def put_whole(src_bytes: bytes, dest: Path):
    """Whole-file write + rename. UC-volume FUSE can refuse rename-over-existing: fall back to copy."""
    tmp = dest.with_name(dest.name + '.tmp')
    tmp.write_bytes(src_bytes)
    try:
        os.replace(tmp, dest)
    except OSError:
        shutil.copyfile(tmp, dest); tmp.unlink(missing_ok=True)


class Publisher:
    """Assets first, manifest last. Events are buffered and flushed as new chunk files, never appended."""

    def __init__(self, run: Path, flush_s: float = 3.0):
        self.run = run; (run / 'assets').mkdir(parents=True, exist_ok=True); (run / 'events').mkdir(exist_ok=True)
        self.manifest = dict(schema_version=1, status='running', job_start_unix=T0, frame='unknown', assets=[], stages={},
                             events=dict(chunks=0, count=0))
        self.pending, self.lock, self.flush_s = [], threading.Lock(), flush_s
        self._write_manifest()
        threading.Thread(target=self._flusher, daemon=True).start()

    def _write_manifest(self):
        put_whole(json.dumps(self.manifest, indent=1).encode(), self.run / 'manifest.json')

    def event(self, type_, **fields):
        with self.lock:
            self.pending.append(dict(seq=self.manifest['events']['count'] + len(self.pending), t=wall(), type=type_, **fields))

    def flush_events(self):
        with self.lock:
            recs, self.pending = self.pending, []
            if not recs:
                return
            ev = self.manifest['events']
            put_whole(''.join(json.dumps(r) + '\n' for r in recs).encode(), self.run / 'events' / f'{ev["chunks"]:06d}.jsonl')
            ev.update(chunks=ev['chunks'] + 1, count=ev['count'] + len(recs), last_type=recs[-1]['type'])
            self._write_manifest()

    def _flusher(self):
        while True:
            time.sleep(self.flush_s); self.flush_events()
            put_whole(json.dumps(dict(updated_unix=time.time(), wall_s=wall(), status=self.manifest['status'])).encode(),
                      self.run / 'progress.json')

    def asset(self, kind: str, src: Path, **meta):
        with self.lock:
            seq = len(self.manifest['assets'])
            name = f'{seq:03d}_{kind}{src.suffix}'
            put_whole(src.read_bytes(), self.run / 'assets' / name)
            self.manifest['assets'].append(dict(seq=seq, kind=kind, file=f'assets/{name}', bytes=src.stat().st_size,
                                                wall_s_since_job_start=wall(), **meta))
            self._write_manifest()
        self.event('asset_published', kind=kind, asset_seq=seq)
        print(f'[{wall():7.1f}s] published #{seq} {kind}', flush=True)

    def stage(self, name, phase):
        with self.lock:
            st = self.manifest['stages'].setdefault(name, {})
            st['start_wall_s' if phase == 'start' else 'end_wall_s'] = wall()
            if phase == 'end':
                st['seconds'] = round(st['end_wall_s'] - st['start_wall_s'], 2)
        self.event('stage', name=name, phase=phase)

    def finish(self, status, **extra):
        self.flush_events()
        with self.lock:
            self.manifest.update(status=status, **extra); self._write_manifest()


def sh(cmd, log: Path):
    t = time.time()
    with open(log, 'a') as f:
        f.write('$ ' + ' '.join(map(str, cmd)) + '\n'); f.flush()
        r = subprocess.run(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT)
    print(f'[{wall():7.1f}s] {Path(str(cmd[0])).name} {cmd[1] if len(cmd) > 1 else ""}: rc {r.returncode} in {time.time() - t:.1f}s', flush=True)
    if r.returncode:
        raise RuntimeError(f'{cmd[:2]} failed, see {log}')


def load_priors(path):
    rows = sorted((float(r['t_s']), float(r['x']), float(r['y']), float(r['z'])) for r in csv.DictReader(open(path)))
    return [r[0] for r in rows], [r[1:] for r in rows]


def prior_at(priors, t):
    ts, ps = priors
    i = bisect.bisect_left(ts, t)
    if i <= 0 or i >= len(ts):
        return ps[min(max(i, 0), len(ts) - 1)]
    w = (t - ts[i - 1]) / max(ts[i] - ts[i - 1], 1e-9)
    return [a + w * (b - a) for a, b in zip(ps[i - 1], ps[i])]


def select_frames(video, out_dir: Path, max_frames, decode_fps, max_side):
    """Sharpest frame per time window (variance of the Laplacian); windows sized so we keep ~max_frames."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = n / fps if n else None
    window = max(duration / max_frames, 1.0 / decode_fps) if duration else 1.0 / decode_fps
    step = max(int(round(fps / decode_fps)), 1)
    best, chosen, i = {}, [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, img = cap.retrieve()
            if ok:
                t = i / fps
                s = max(img.shape[:2])
                if s > max_side:
                    img = cv2.resize(img, None, fx=max_side / s, fy=max_side / s, interpolation=cv2.INTER_AREA)
                sharp = float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
                w = int(t // window)
                if w not in best or sharp > best[w][0]:
                    best[w] = (sharp, t, img)
        i += 1
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, w in enumerate(sorted(best)):
        sharp, t, img = best[w]
        name = f'f{k:05d}.jpg'
        cv2.imwrite(str(out_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        chosen.append(dict(name=name, t=round(t, 3), sharpness=round(sharp, 1)))
    return chosen


def predict_pairs(frames, priors, seq_window, radius_k):
    """Sequential neighbours always; with priors also every pair closer than radius_k x median step (revisits)."""
    pairs = set()
    for i in range(len(frames)):
        for j in range(i + 1, min(i + 1 + seq_window, len(frames))):
            pairs.add((i, j))
    if priors:
        P = [prior_at(priors, f['t']) for f in frames]
        steps = sorted(math.dist(P[i], P[i + 1]) for i in range(len(P) - 1)) or [1.0]
        r = radius_k * max(steps[len(steps) // 2], 1e-3)
        for i in range(len(P)):
            for j in range(i + seq_window + 1, len(P)):
                if math.dist(P[i], P[j]) < r:
                    pairs.add((i, j))
    return sorted(pairs)


def model_stats(colmap, model: Path, log: Path):
    out = subprocess.run([colmap, 'model_analyzer', '--path', str(model)], capture_output=True, text=True)
    txt = out.stdout + out.stderr
    log.open('a').write(txt)
    num = lambda pat: (float(m.group(1)) if (m := re.search(pat, txt)) else None)
    return dict(registered=num(r'Registered images:\s*([\d.]+)'), points=num(r'Points:\s*([\d.]+)'),
                reproj_px=num(r'Mean reprojection error:\s*([\d.]+)'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', type=Path, required=True); ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--priors', type=Path); ap.add_argument('--masks', type=Path, help='COLMAP mask dir: <image>.png, 0 = ignore (e.g. sky/water)')
    ap.add_argument('--max-frames', type=int, default=200); ap.add_argument('--decode-fps', type=float, default=5)
    ap.add_argument('--max-side', type=int, default=1920); ap.add_argument('--sift-features', type=int, default=6000)
    ap.add_argument('--seq-window', type=int, default=4); ap.add_argument('--radius-k', type=float, default=3.0)
    ap.add_argument('--mapper', choices=['global', 'incremental'], default='global')
    ap.add_argument('--min-registered-frac', type=float, default=0.9); ap.add_argument('--max-reproj-px', type=float, default=1.0)
    ap.add_argument('--splat-steps', type=int, default=0, help='0 = skip; else run gsplat simple_trainer (needs GSPLAT_EXAMPLES)')
    ap.add_argument('--timeout-s', type=int, default=40 * 60); ap.add_argument('--gpu', type=int, default=1)
    a = ap.parse_args()

    # Hard stop inside the job too, in addition to the platform's timeout_minutes.
    threading.Timer(a.timeout_s, lambda: (print('watchdog timeout', flush=True), os._exit(3))).start()
    colmap = os.environ.get('COLMAP', 'colmap')
    local = Path('/local_disk0') if os.access('/local_disk0', os.W_OK) else Path('/tmp')
    work = local / f'recon_{a.run.name}'; shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    log = work / 'colmap.log'
    pub = Publisher(a.run)
    priors = load_priors(a.priors) if a.priors else None
    try:
        pub.stage('select', 'start')
        frames = select_frames(a.video, work / 'images', a.max_frames, a.decode_fps, a.max_side)
        if len(frames) < 3:
            raise RuntimeError(f'only {len(frames)} frames decoded from {a.video}')
        for f in frames:
            if priors:
                f['prior_p'] = prior_at(priors, f['t'])
        (work / 'frames.json').write_text(json.dumps(dict(frames=frames, priors=bool(priors)), indent=1))
        pub.asset('frames_chosen', work / 'frames.json', n_frames=len(frames))
        pub.stage('select', 'end')

        pub.stage('match', 'start')
        db, img = work / 'database.db', work / 'images'
        extract = [colmap, 'feature_extractor', '--database_path', db, '--image_path', img,
                   '--ImageReader.single_camera', 1, '--ImageReader.camera_model', 'OPENCV',
                   '--SiftExtraction.max_num_features', a.sift_features, '--FeatureExtraction.use_gpu', a.gpu]
        if a.masks:
            extract += ['--ImageReader.mask_path', a.masks]
        sh(extract, log)
        pairs = predict_pairs(frames, priors, a.seq_window, a.radius_k)
        (work / 'pairs.txt').write_text(''.join(f'{frames[i]["name"]} {frames[j]["name"]}\n' for i, j in pairs))
        sh([colmap, 'matches_importer', '--database_path', db, '--match_list_path', work / 'pairs.txt',
            '--match_type', 'pairs', '--FeatureMatching.use_gpu', a.gpu], log)
        pub.event('pairs', n=len(pairs), from_priors=bool(priors))
        pub.stage('match', 'end')

        pub.stage('sfm', 'start')
        sparse = work / 'sparse'; sparse.mkdir()
        sh([colmap, 'global_mapper' if a.mapper == 'global' else 'mapper', '--database_path', db, '--image_path', img,
            '--output_path', sparse], log)
        models = sorted((p for p in sparse.iterdir() if p.is_dir()), key=lambda p: model_stats(colmap, p, log)['registered'] or 0)
        if not models:
            raise RuntimeError('no model reconstructed')
        model = models[-1]
        # One full BA pass: refines, and recomputes per-point errors (global_mapper's stored errors are not usable for QA).
        refined = work / 'refined'; refined.mkdir()
        sh([colmap, 'bundle_adjuster', '--input_path', model, '--output_path', refined], log)
        model = refined
        if priors:   # Sim3 into the priors' frame; COLMAP refuses if the fit is worse than alignment_max_error metres
            ref = work / 'ref_positions.txt'
            ref.write_text(''.join(f'{f["name"]} {f["prior_p"][0]} {f["prior_p"][1]} {f["prior_p"][2]}\n' for f in frames))
            aligned = work / 'aligned'; aligned.mkdir()
            sh([colmap, 'model_aligner', '--input_path', model, '--output_path', aligned, '--ref_images_path', ref,
                '--ref_is_gps', 0, '--alignment_type', 'custom', '--alignment_max_error', 3.0], log)
            model = aligned
            with pub.lock:
                pub.manifest['frame'] = 'priors'
        sh([colmap, 'model_converter', '--input_path', model, '--output_path', work / 'points.ply', '--output_type', 'PLY'], log)
        stats = model_stats(colmap, model, log)
        frac = (stats['registered'] or 0) / max(len(frames), 1)
        qa = dict(registered_frac=round(frac, 3), reproj_px=stats['reproj_px'],
                  passed=frac >= a.min_registered_frac and (stats['reproj_px'] or 99) <= a.max_reproj_px)
        pub.asset('points_final', work / 'points.ply', n_points=stats['points'], qa=qa)
        pub.event('qa', **qa)
        pub.stage('sfm', 'end')

        if a.splat_steps:
            pub.stage('splat', 'start')
            ex = Path(os.environ['GSPLAT_EXAMPLES'])   # a checkout of nerfstudio-project/gsplat examples/
            data = work / 'gs_data'; (data / 'sparse').mkdir(parents=True)
            shutil.copytree(model, data / 'sparse' / '0'); os.symlink(img, data / 'images')
            sh([sys.executable, ex / 'simple_trainer.py', 'default', '--data_dir', data, '--result_dir', work / 'splat',
                '--data_factor', 1, '--max_steps', a.splat_steps, '--save_ply', '--ply_steps', a.splat_steps,
                '--disable_viewer'], work / 'splat.log')
            plys = sorted((work / 'splat').rglob('*.ply'))
            if plys:
                pub.asset('splat_final_ply', plys[-1], step=a.splat_steps)
            pub.stage('splat', 'end')
        status, extra = 'complete', dict(qa=qa)
    except Exception as e:  # report, then exit; never leave the GPU running
        print('FAILED', repr(e), flush=True)
        status, extra = 'failed', dict(error=repr(e)[:500])
    if log.exists():
        shutil.copyfile(log, work / 'colmap_log.txt'); pub.asset('log', work / 'colmap_log.txt')
    pub.finish(status, **extra)
    sys.stdout.flush()
    rc = 0 if status == 'complete' else 1
    os._exit(rc)   # skip interpreter teardown: stray non-daemon threads must not keep a billed GPU alive


if __name__ == '__main__':
    main()

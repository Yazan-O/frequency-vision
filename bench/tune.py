import argparse
import json
import multiprocessing as mp
import os
import platform
import socket
import sys
import time
from pathlib import Path

import cv2 as cv
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e as E
from hertz import freq

TOL = 1e-3


def meta(label, **kw):
    info = cv.getBuildInformation()
    return {"label": label, "host": socket.gethostname(), "machine": platform.machine(), "cpu_count": os.cpu_count(), "python": platform.python_version(),
            "opencv": cv.__version__, "cv2_file": cv.__file__, "numpy": np.__version__,
            "build": [line.strip() for line in info.splitlines() if any(k in line for k in ("HAL", "KleidiCV", "Baseline", "Dispatched", "Parallel framework"))],
            "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw}


def det_pass(det, ws):
    out, lat = [], []
    for w in ws:
        t = time.perf_counter()
        b, s, _ = det.detect(w["img"])
        lat.append(time.perf_counter() - t)
        out.append((b, s))
    return out, np.array(lat) * 1e3


def diff(ref, got):
    n_mis, mx = 0, 0.0
    for (rb, rs), (gb, gs) in zip(ref, got):
        if len(rb) != len(gb):
            n_mis += 1
            continue
        if len(rb):
            mx = max(mx, float(np.abs(rb - gb).max()), float(np.abs(rs - gs).max()))
    return n_mis, mx


def det(a):
    ws = E.windows()
    targets = ["default", "cpu"] + (["cpu_fp16"] if cv.dnn.DNN_TARGET_CPU_FP16 in cv.dnn.getAvailableTargets(cv.dnn.DNN_BACKEND_OPENCV) else [])
    cfgs = [(e, t, n) for e in ("new", "classic") for t in targets for n in (4, 2)]
    cfgs.remove(("new", "default", 4))
    cfgs.insert(0, ("new", "default", 4))
    rows, ref = [], None
    for e, t, n in cfgs:
        row = {"engine": e, "target": t, "threads": n}
        try:
            cv.setNumThreads(n)
            d = E.make_detector(a.onnx, e, t)
            det_pass(d, ws[:5])
            out, lat = det_pass(d, ws)
            ref = ref or out
            n_mis, mx = diff(ref, out)
            row.update({"net_layers": len(d.net.getLayerNames()), "windows": len(ws), "boxes": int(sum(len(b) for b, _ in out)), "det_p50_ms": float(np.percentile(lat, 50)),
                        "det_mean_ms": float(lat.mean()), "det_p95_ms": float(np.percentile(lat, 95)), "box_count_mismatch_windows": n_mis,
                        "max_abs_diff_box_px_or_score": mx, "correct": n_mis == 0 and mx <= TOL})
        except cv.error as x:
            row["error"] = str(x).strip().splitlines()[-1][:300]
        rows.append(row)
        print(json.dumps(row), flush=True)
    ok = [r for r in rows if r.get("correct")]
    best = min(ok, key=lambda r: r["det_mean_ms"])
    res = {"meta": meta(a.label, onnx=os.path.basename(a.onnx), reference="engine new, default target, 4 threads (the current setting)", tolerance=TOL,
                        opencv_targets=[int(x) for x in cv.dnn.getAvailableTargets(cv.dnn.DNN_BACKEND_OPENCV)]),
           "configs": rows, "best": best}
    Path(a.out).write_text(json.dumps(res, indent=1))
    print("BEST", best["engine"], best["target"], best["threads"])


def ev_windows(ws, length_us):
    out = []
    for w in ws:
        t0 = w["t1"] - length_us
        if t0 >= int(w["ev"]["t"][0]):
            out.append({**w, "t0": t0})
    return out


def ev(a):
    ws = E.windows()
    src = next(iter(sorted(Path(a.out).parent.glob("e2e-pip-best-*-r3.json"))), Path(a.boxes))
    a.boxes = str(src)
    ref = {(r["clip"], r["frame"]): np.array(r["boxes"], np.float32).reshape(-1, 4) for r in json.loads(src.read_text())["windows"]}
    rows, recs = [], []
    for n in (1, 4):
        cv.setNumThreads(n)
        for ms in (20, 50, 100, 500):
            sub = ev_windows(ws, ms * 1000)[:: a.stride_500 if ms == 500 else 1]
            tf, tb, nev = [], [], []
            for rep in range(a.reps + 1):
                for w in sub:
                    t = time.perf_counter()
                    fmap, smap = freq.frequency_map(w["ev"], w["t0"], w["t1"], (0, 0, w["w"], w["h"]))
                    t1 = time.perf_counter()
                    spec = []
                    for b in ref[(w["clip"], w["frame"])]:
                        s0 = time.perf_counter()
                        spec.append(freq.box_spectrum(w["ev"], b, w["t0"], w["t1"]))
                        tb.append(time.perf_counter() - s0) if rep else None
                    if rep:
                        tf.append(t1 - t)
                    if rep == 1:
                        i0, i1 = np.searchsorted(w["ev"]["t"], [w["t0"], w["t1"]])
                        nev.append(int(i1 - i0))
                        if n == 4:
                            recs.append({"window_ms": ms, "clip": w["clip"], "frame": w["frame"], "active": int((smap > 0).sum()),
                                         "hum_pixels": int((smap >= freq.CLEAR_SNR).sum()), "fmap_sum": round(float(fmap.sum()), 3),
                                         "peaks": [round(float(d["peak_hz"]), 4) for d in spec], "snr": [round(float(d["snr"]), 4) for d in spec],
                                         "clear": [d["clear"] for d in spec]})
            tf, tb = np.array(tf) * 1e3, np.array(tb) * 1e3
            row = {"threads": n, "window_ms": ms, "windows": len(sub), "reps": a.reps, "events_per_window_median": float(np.median(nev)),
                   "fmap_p50_ms": float(np.percentile(tf, 50)), "fmap_mean_ms": float(tf.mean()),
                   "box_checks_per_rep": len(tb) // a.reps, "box_p50_ms": float(np.percentile(tb, 50)) if len(tb) else None,
                   "box_mean_ms": float(tb.mean()) if len(tb) else None,
                   "events_per_s_fmap_mean": float(np.sum(nev) / (tf.sum() / 1e3 / a.reps))}
            rows.append(row)
            print(json.dumps(row), flush=True)
    res = {"meta": meta(a.label, boxes_from=os.path.basename(a.boxes), reps_after_one_warmup_pass=a.reps, window_500ms_every_nth=a.stride_500,
                        workload="hertz.freq.frequency_map over the full 1280x720 sensor and hertz.freq.box_spectrum on each detector box (boxes from the committed pip E2E run), on real FRED event windows of 20, 50, 100 and 500 ms ending at each RGB frame time"),
           "rows": rows, "outputs_threads4": recs}
    Path(a.out).write_text(json.dumps(res, indent=1))


def _worker(args):
    global WS
    onnx, engine, target, threads, idx, q = args
    WS = WS or E.windows()
    cv.setNumThreads(threads)
    d = E.make_detector(onnx, engine, target)
    for w in WS[:3]:
        E.confirm(d, w)
    q.put(time.perf_counter())
    n = 0
    for k in idx:
        E.confirm(d, WS[k])
        n += 1
    return n, time.perf_counter()


WS = None


def tput(a):
    global WS
    WS = E.windows()
    rows = []
    ctx = mp.get_context(a.start)
    for nw in (1, 2, 4):
        th = max(1, os.cpu_count() // nw)
        with ctx.Manager() as m:
            q = m.Queue()
            idx = list(range(len(WS))) * a.reps
            with ctx.Pool(nw) as pool:
                res = pool.map(_worker, [(a.onnx, a.engine, a.target, th, idx, q) for _ in range(nw)])
            starts = [q.get() for _ in range(nw)]
        t0, t1 = min(starts), max(r[1] for r in res)
        n = sum(r[0] for r in res)
        row = {"workers": nw, "cv_threads_per_worker": th, "windows": n, "wall_s": t1 - t0, "windows_per_s": n / (t1 - t0)}
        if a.price_usd_hour:
            row["usd_per_1000_windows"] = a.price_usd_hour / 3600 / row["windows_per_s"] * 1000
            row["windows_per_usd"] = row["windows_per_s"] * 3600 / a.price_usd_hour
        rows.append(row)
        print(json.dumps(row), flush=True)
    res = {"meta": meta(a.label, onnx=os.path.basename(a.onnx), detector_engine=a.engine, detector_target=a.target, price_usd_hour=a.price_usd_hour, start_method=a.start,
                        workload=f"each worker process runs the full E2E window (detector + hum checks + frequency map) over all {len(WS)} windows x reps; wall time from the first worker's start after warm-up to the last worker's end"),
           "rows": rows}
    Path(a.out).write_text(json.dumps(res, indent=1))


def evcmp(a):
    A, B = (json.loads(Path(p).read_text()) for p in (a.a, a.b))
    kA = {(r["window_ms"], r["clip"], r["frame"]): r for r in A["outputs_threads4"]}
    n, act, hum, hz, flips, snr = 0, 0, 0, 0.0, 0, 0.0
    for r in B["outputs_threads4"]:
        q = kA[(r["window_ms"], r["clip"], r["frame"])]
        n += 1
        act += q["active"] != r["active"]
        hum += q["hum_pixels"] != r["hum_pixels"]
        for pa, pb, sa, sb, ca, cb in zip(q["peaks"], r["peaks"], q["snr"], r["snr"], q["clear"], r["clear"]):
            hz = max(hz, abs(pa - pb))
            snr = max(snr, abs(sa - sb) / max(abs(sa), 1e-9))
            flips += ca != cb
    out = {"a": A["meta"]["label"] + " " + A["meta"]["opencv"], "b": B["meta"]["label"] + " " + B["meta"]["opencv"], "windows": n,
           "windows_active_pixels_differ": act, "windows_hum_pixels_differ": hum, "max_peak_hz_diff": hz, "max_snr_rel_diff": snr, "hum_verdict_flips": flips}
    rows = []
    for ra, rb in zip(A["rows"], B["rows"]):
        assert (ra["threads"], ra["window_ms"]) == (rb["threads"], rb["window_ms"])
        rows.append({"threads": ra["threads"], "window_ms": ra["window_ms"], "fmap_mean_ms_a": ra["fmap_mean_ms"], "fmap_mean_ms_b": rb["fmap_mean_ms"],
                     "fmap_speedup_b_over_a": ra["fmap_mean_ms"] / rb["fmap_mean_ms"], "box_mean_ms_a": ra["box_mean_ms"], "box_mean_ms_b": rb["box_mean_ms"],
                     "box_speedup_b_over_a": ra["box_mean_ms"] / rb["box_mean_ms"] if rb["box_mean_ms"] else None})
    out["speed"] = rows
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("det")
    e = sp.add_parser("ev")
    t = sp.add_parser("tput")
    for p in (d, e, t):
        p.add_argument("--label", required=True)
        p.add_argument("--out", required=True)
    for p in (d, t):
        p.add_argument("--onnx", required=True)
    e.add_argument("--boxes", required=True)
    e.add_argument("--reps", type=int, default=2)
    e.add_argument("--stride-500", type=int, default=5)
    t.add_argument("--engine", default="new")
    t.add_argument("--target", default="default")
    t.add_argument("--reps", type=int, default=1)
    t.add_argument("--price-usd-hour", type=float)
    t.add_argument("--start", choices=["fork", "spawn"], default="spawn")
    c = sp.add_parser("evcmp")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--out", required=True)
    a = ap.parse_args()
    {"det": det, "ev": ev, "tput": tput, "evcmp": evcmp}[a.cmd](a)


if __name__ == "__main__":
    main()

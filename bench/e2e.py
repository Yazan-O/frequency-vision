import argparse
import json
import os
import platform
import socket
import sys
import time
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hertz import freq
from hertz.detect import Detector

WIN_US = 100000
CONF = 0.125


def windows():
    out = []
    for c in json.loads((ROOT / "app/static/data/clips.json").read_text())["clips"]:
        z = np.load(ROOT / "app/data" / f"{c['id']}.npz")
        ev = {"x": z["x"].astype(np.int32), "y": z["y"].astype(np.int32), "t": z["t"].astype(np.int64), "p": z["p"].astype(np.int8)}
        origin = float(z["origin_s"])
        for k, f in enumerate(c["frames"]):
            t1 = int(round((f["t"] - origin) * 1e6))
            if t1 - WIN_US < int(ev["t"][0]):
                continue
            img = cv.imread(str(ROOT / "app/static" / f["src"]))
            out.append({"clip": c["id"], "frame": k, "img": img, "ev": ev, "t0": t1 - WIN_US, "t1": t1, "w": c["width"], "h": c["height"]})
    return out


def confirm(det, w):
    boxes, scores, _ = det.detect(w["img"])
    s = w["w"] / w["img"].shape[1]
    ev_boxes = boxes * s
    spec = [freq.box_spectrum(w["ev"], b, w["t0"], w["t1"]) for b in ev_boxes]
    fmap, smap = freq.frequency_map(w["ev"], w["t0"], w["t1"], (0, 0, w["w"], w["h"]))
    return ev_boxes, scores, spec, fmap, smap


def record(w, r):
    ev_boxes, scores, spec, fmap, smap = r
    strong = smap >= freq.CLEAR_SNR
    return {"clip": w["clip"], "frame": w["frame"], "boxes": np.round(ev_boxes, 3).tolist(), "scores": [round(float(v), 6) for v in scores],
            "peaks": [{"peak_hz": round(float(d["peak_hz"]), 4), "snr": round(float(d["snr"]), 4), "n_events": int(d["n_events"]), "clear": d["clear"]} for d in spec],
            "fmap": {"active": int((smap > 0).sum()), "hum_pixels": int(strong.sum()),
                     "hum_median_hz": round(float(np.median(fmap[strong])), 4) if strong.any() else None, "fmap_sum": round(float(fmap.sum()), 3)}}


def run(a):
    cv.setNumThreads(a.threads) if a.threads else None
    det = Detector(a.onnx, conf=CONF)
    ws = windows()
    for w in ws[: a.warmup]:
        confirm(det, w)
    lat, stage, recs = [], {"detect": [], "spectra": [], "fmap": []}, []
    c0, w0 = os.times(), time.perf_counter()
    for rep in range(a.reps):
        for w in ws:
            t = time.perf_counter()
            boxes, scores, _ = det.detect(w["img"])
            t_d = time.perf_counter()
            ev_boxes = boxes * (w["w"] / w["img"].shape[1])
            spec = [freq.box_spectrum(w["ev"], b, w["t0"], w["t1"]) for b in ev_boxes]
            t_s = time.perf_counter()
            fmap, smap = freq.frequency_map(w["ev"], w["t0"], w["t1"], (0, 0, w["w"], w["h"]))
            t_f = time.perf_counter()
            lat.append(t_f - t)
            stage["detect"].append(t_d - t)
            stage["spectra"].append(t_s - t_d)
            stage["fmap"].append(t_f - t_s)
            if rep == 0:
                recs.append(record(w, (ev_boxes, scores, spec, fmap, smap)))
    c1, w1 = os.times(), time.perf_counter()
    wall = w1 - w0
    lat = np.array(lat) * 1e3
    ncpu = os.cpu_count()
    summ = {"windows": len(ws), "reps": a.reps, "timed_windows": len(lat), "wall_s": round(wall, 3),
            "p50_ms": float(np.percentile(lat, 50)), "p95_ms": float(np.percentile(lat, 95)), "mean_ms": float(lat.mean()),
            "windows_per_s": len(lat) / wall, "cpu_pct_of_all_vcpus": (c1.user - c0.user + c1.system - c0.system) / wall / ncpu * 100,
            "stage_p50_ms": {k: float(np.percentile(np.array(v) * 1e3, 50)) for k, v in stage.items()},
            "boxes_total": sum(len(r["boxes"]) for r in recs)}
    if a.price_usd_hour:
        summ["usd_per_1000_windows"] = a.price_usd_hour / 3600 * wall / len(lat) * 1000
    info = cv.getBuildInformation()
    meta = {"label": a.label, "host": socket.gethostname(), "machine": platform.machine(), "cpu_count": ncpu, "cv_threads": cv.getNumThreads(),
            "python": platform.python_version(), "opencv": cv.__version__, "cv2_file": cv.__file__, "numpy": np.__version__,
            "build": [line.strip() for line in info.splitlines() if any(k in line for k in ("HAL", "KleidiCV", "Baseline", "Dispatched", "Parallel framework"))],
            "onnx": os.path.basename(a.onnx), "detector_conf": CONF, "window_us": WIN_US, "price_usd_hour": a.price_usd_hour,
            "frames": "app/static/data/<clip>/fNNN.jpg (640x360 JPEG from FRED RGB); boxes scaled to the 1280x720 event sensor",
            "workload": "per window: hertz.detect.Detector.detect on the RGB frame, hertz.freq.box_spectrum on every proposed box, hertz.freq.frequency_map over the full 1280x720 sensor; 100 ms event window ending at the frame time; JPEG decode excluded",
            "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    Path(a.out).write_text(json.dumps({"meta": meta, "summary": summ, "windows": recs}, indent=1))
    print(json.dumps({"meta": {k: meta[k] for k in ("label", "opencv", "cv2_file", "cv_threads")}, "summary": summ}, indent=1))


def compare(a):
    A, B = (json.loads(Path(p).read_text()) for p in (a.a, a.b))
    n_win = len(A["windows"])
    same_n, box_d, score_d, hz_d, snr_rel, clear_flip, fm = 0, [], [], [], [], 0, {"active": 0, "hum_pixels": 0, "hum_hz": []}
    miss = []
    for ra, rb in zip(A["windows"], B["windows"]):
        assert (ra["clip"], ra["frame"]) == (rb["clip"], rb["frame"])
        if len(ra["boxes"]) != len(rb["boxes"]):
            miss.append({"clip": ra["clip"], "frame": ra["frame"], "n_a": len(ra["boxes"]), "n_b": len(rb["boxes"])})
        else:
            same_n += 1
            for ba, bb, sa, sb, pa, pb in zip(ra["boxes"], rb["boxes"], ra["scores"], rb["scores"], ra["peaks"], rb["peaks"]):
                box_d.append(max(abs(x - y) for x, y in zip(ba, bb)))
                score_d.append(abs(sa - sb))
                hz_d.append(abs(pa["peak_hz"] - pb["peak_hz"]))
                snr_rel.append(abs(pa["snr"] - pb["snr"]) / max(abs(pa["snr"]), 1e-9))
                clear_flip += pa["clear"] != pb["clear"]
        fm["active"] += ra["fmap"]["active"] != rb["fmap"]["active"]
        fm["hum_pixels"] += ra["fmap"]["hum_pixels"] != rb["fmap"]["hum_pixels"]
        if ra["fmap"]["hum_median_hz"] is not None and rb["fmap"]["hum_median_hz"] is not None:
            fm["hum_hz"].append(abs(ra["fmap"]["hum_median_hz"] - rb["fmap"]["hum_median_hz"]))
    mx = lambda v: float(max(v)) if v else 0.0
    out = {"a": A["meta"]["label"] + " " + A["meta"]["opencv"], "b": B["meta"]["label"] + " " + B["meta"]["opencv"], "windows": n_win,
           "windows_same_box_count": same_n, "box_count_mismatch": miss, "boxes_compared": len(box_d),
           "max_box_coord_diff_px": mx(box_d), "max_score_diff": mx(score_d), "max_peak_hz_diff": mx(hz_d),
           "boxes_peak_hz_diff_over_1hz": int(sum(d > 1.0 for d in hz_d)), "max_snr_rel_diff": mx(snr_rel), "hum_verdict_flips": clear_flip,
           "fmap_windows_active_pixels_differ": fm["active"], "fmap_windows_hum_pixels_differ": fm["hum_pixels"], "fmap_max_hum_median_hz_diff": mx(fm["hum_hz"])}
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run")
    r.add_argument("--label", required=True)
    r.add_argument("--onnx", required=True)
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--warmup", type=int, default=10)
    r.add_argument("--threads", type=int, default=0)
    r.add_argument("--price-usd-hour", type=float)
    r.add_argument("--out", required=True)
    c = sp.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--out", required=True)
    a = ap.parse_args()
    run(a) if a.cmd == "run" else compare(a)


if __name__ == "__main__":
    main()

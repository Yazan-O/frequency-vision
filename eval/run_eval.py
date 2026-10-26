import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from fred_rgb import frame_labels
from strobe import freq
from strobe.detect import Detector

FPS = 30.0
MOTION_LAG = 10
MOTION_RADIUS = 150.0


def iou(a, b):
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + ab[None, :] - inter, 1e-9)


def infer_seq(a):
    seq_dir, onnx, out_dir, conf, spec_conf, win_ms, threads, stride = a
    sid = Path(seq_dir).name
    out = Path(out_dir, f"{sid}.npz")
    if out.exists():
        return str(out)
    frames, ts, labels = frame_labels(seq_dir)
    det = Detector(onnx, conf=conf, threads=threads)
    events = None
    h5 = Path(seq_dir, "Event", "events.hdf5")
    if spec_conf is not None and h5.exists():
        from strobe.events import read_events
        events = read_events(h5)
    rows, gts, lat = [], [], []
    idx = list(range(0, len(frames), stride))
    for i in idx:
        for b in labels[i]:
            gts.append([i, *b[:4]])
        im = cv.imread(str(frames[i]))
        if im is None:
            continue
        t0 = time.perf_counter()
        boxes, scores, _ = det.detect(im)
        lat.append(time.perf_counter() - t0)
        for b, s in zip(boxes, scores):
            snr = hz = -1.0
            nev = -1
            if events is not None and s >= spec_conf:
                r = freq.box_spectrum(events, b, int(ts[i]) - int(win_ms * 1000), int(ts[i]))
                snr, hz, nev = r["snr"], r["peak_hz"], r["n_events"]
            rows.append([i, *b, s, snr, hz, nev])
    tmp = out.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, det=np.array(rows, np.float64).reshape(-1, 9), gt=np.array(gts, np.float64).reshape(-1, 5),
                        n_frames=len(idx), n_total=len(frames), stride=stride, ts=ts, lat_s=np.array(lat), frames=np.array([str(f) for f in frames]))
    os.replace(tmp, out)
    return str(out)


def load(npzs):
    D, G, nfr, lat = [], [], 0, []
    for k, p in enumerate(npzs):
        z = np.load(p)
        d, g = z["det"], z["gt"]
        D.append(np.c_[np.full(len(d), k), d])
        G.append(np.c_[np.full(len(g), k), g])
        nfr += int(z["n_frames"])
        lat.append(z["lat_s"])
    return np.concatenate(D), np.concatenate(G), nfr, np.concatenate(lat)


def match(D, G, thr=0.5):
    order = np.argsort(-D[:, 6], kind="stable")
    tp = np.zeros(len(D), bool)
    gkey = {}
    for j, r in enumerate(G):
        gkey.setdefault((int(r[0]), int(r[1])), []).append(j)
    used = np.zeros(len(G), bool)
    dkey = {}
    for j in order:
        dkey.setdefault((int(D[j, 0]), int(D[j, 1])), []).append(j)
    for key, js in dkey.items():
        gj = gkey.get(key, [])
        if not gj:
            continue
        M = iou(D[js, 2:6], G[gj, 2:6])
        for a, j in enumerate(js):
            cand = [(M[a, b], b) for b in range(len(gj)) if not used[gj[b]] and M[a, b] >= thr]
            if cand:
                used[gj[max(cand)[1]]] = True
                tp[j] = True
    return tp


def ap_curve(scores, tp, n_gt):
    o = np.argsort(-scores, kind="stable")
    t = tp[o].astype(np.float64)
    ctp, cfp = np.cumsum(t), np.cumsum(1 - t)
    rec = ctp / max(n_gt, 1)
    prec = ctp / np.maximum(ctp + cfp, 1e-9)
    mrec = np.r_[0, rec, 1]
    mpre = np.r_[1, prec, 0]
    mpre = np.maximum.accumulate(mpre[::-1])[::-1]
    i = np.flatnonzero(mrec[1:] != mrec[:-1])
    return float(np.sum((mrec[i + 1] - mrec[i]) * mpre[i + 1]))


def op_point(keep, tp, n_gt, minutes, D):
    k = keep.astype(bool)
    ntp, nfp = int((tp & k).sum()), int((~tp & k).sum())
    fa_frames = len({(int(r[0]), int(r[1])) for r in D[k & ~tp]})
    p = ntp / max(ntp + nfp, 1)
    r = ntp / max(n_gt, 1)
    return {"tp": ntp, "fp": nfp, "fn": n_gt - ntp, "precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-9),
            "false_alarms": nfp, "false_alarms_per_min": nfp / minutes, "false_alarm_frames_per_min": fa_frames / minutes}


def motion_px(D, s_thr, stride=1, radius=MOTION_RADIUS):
    lag = stride * -(-MOTION_LAG // stride)
    c = np.c_[(D[:, 2] + D[:, 4]) / 2, (D[:, 3] + D[:, 5]) / 2]
    live = D[:, 6] >= s_thr
    by = {}
    for j in np.flatnonzero(live):
        by.setdefault((int(D[j, 0]), int(D[j, 1])), []).append(j)
    out = np.full(len(D), -1.0)
    for j in range(len(D)):
        prev = by.get((int(D[j, 0]), int(D[j, 1]) - lag))
        if not prev:
            continue
        d = np.hypot(*(c[prev] - c[j]).T)
        if d.min() <= radius:
            out[j] = float(d.min())
    return out


def keep_mask(D, v, mot):
    snr, nev = D[:, 7], D[:, 9]
    k = np.ones(len(D), bool)
    if v.get("snr") is not None:
        k &= (nev >= 0) & (snr >= v["snr"]) & (nev >= v.get("min_events", 0))
    if v.get("motion") is not None:
        k &= mot >= v["motion"]
    return k


def evaluate(D, G, tp, minutes, s_thr, v, mot, tp30=None):
    k = keep_mask(D, v, mot)
    r = {"ap50": ap_curve(D[k, 6], tp[k], len(G)), **op_point((D[:, 6] >= s_thr) & k, tp, len(G), minutes, D)}
    if tp30 is not None:
        r["ap30"] = ap_curve(D[k, 6], tp30[k], len(G))
        r["false_alarms_per_min_iou30"] = int(((D[:, 6] >= s_thr) & k & ~tp30).sum()) / minutes
    return r


def choose(npzs):
    D, G, nfr, _ = load(npzs)
    tp = match(D, G)
    minutes = nfr / FPS / 60.0
    s_thr = float(max(np.round(np.arange(0.05, 0.95, 0.025), 3), key=lambda s: op_point(D[:, 6] >= s, tp, len(G), minutes, D)["f1"]))
    mot = motion_px(D, s_thr, int(np.load(npzs[0])["stride"]))
    hum_grid = [{"snr": t, "min_events": m} for t in (3, 5, 7.9, 10, 15, 20, 30, 50, 98) for m in (0, 50, 200)]
    mot_grid = [{"motion": m} for m in (0, 1, 2, 4, 8, 16, 32)]
    f1 = lambda v: evaluate(D, G, tp, minutes, s_thr, v, mot)["f1"]
    best_hum = max(hum_grid, key=f1)
    best_mot = max(mot_grid, key=f1)
    variants = {
        "hum_ambiguous_7.9": {"snr": freq.AMBIGUOUS_SNR},
        "hum_clear_98": {"snr": freq.CLEAR_SNR},
        "hum_train_chosen": best_hum,
        "motion_train_chosen": best_mot,
        "hum_ambiguous_7.9_and_motion": {"snr": freq.AMBIGUOUS_SNR, "motion": best_mot["motion"]},
        "hum_train_chosen_and_motion": {**best_hum, "motion": best_mot["motion"]},
    }
    tv = {"rgb_only": evaluate(D, G, tp, minutes, s_thr, {}, mot), **{n: {"rule": v, **evaluate(D, G, tp, minutes, s_thr, v, mot)} for n, v in variants.items()}}
    web_pick = max((n for n in variants if n.startswith("hum")), key=lambda n: tv[n]["f1"])
    return {"score_thr": s_thr, "variants": variants, "web_pick": web_pick, "trainval": tv, "n_frames": nfr, "n_gt": len(G)}


def render_failures(D, G, tp, npzs, s_thr, keep, out_dir, n=12):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    op = D[:, 6] >= s_thr
    fp = np.flatnonzero(op & ~tp)
    fp_kept = fp[keep[fp]][np.argsort(-D[fp[keep[fp]], 6])][: n // 2]
    fp_removed = fp[~keep[fp]][np.argsort(-D[fp[~keep[fp]], 6])][: n // 4]
    tp_removed = np.flatnonzero(op & tp & ~keep)
    tp_removed = tp_removed[np.argsort(-D[tp_removed, 6])][: n // 4]
    detected = {(int(D[j, 0]), int(D[j, 1])) for j in np.flatnonzero(op & tp & keep)}
    gmiss = [j for j in range(len(G)) if (int(G[j, 0]), int(G[j, 1])) not in detected]
    rng = np.random.default_rng(0)
    gmiss = list(rng.choice(gmiss, size=min(len(gmiss), n // 2), replace=False)) if gmiss else []
    cases = [("fp_kept", j) for j in fp_kept] + [("fp_removed_by_events", j) for j in fp_removed] + [("tp_removed_by_events", j) for j in tp_removed]
    cases += [("missed_gt", int(j)) for j in gmiss]
    meta, cache = [], {}
    for kind, j in cases:
        row = G[j] if kind == "missed_gt" else D[j]
        k, fi = int(row[0]), int(row[1])
        if k not in cache:
            cache[k] = np.load(npzs[k])["frames"]
        im = cv.imread(str(cache[k][fi]))
        for g in G[(G[:, 0] == k) & (G[:, 1] == fi)]:
            cv.rectangle(im, (int(g[2]), int(g[3])), (int(g[4]), int(g[5])), (0, 255, 0), 2)
        for d in D[(D[:, 0] == k) & (D[:, 1] == fi) & (D[:, 6] >= s_thr)]:
            cv.rectangle(im, (int(d[2]), int(d[3])), (int(d[4]), int(d[5])), (0, 0, 255), 2)
            cv.putText(im, f"{d[6]:.2f} hum {d[7]:.1f} {d[8]:.0f}Hz n{int(d[9])}", (int(d[2]), max(int(d[3]) - 6, 12)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        name = f"{kind}_{Path(npzs[k]).stem}_{fi:06d}.jpg"
        cv.imwrite(str(out_dir / name), im, [cv.IMWRITE_JPEG_QUALITY, 85])
        meta.append({"file": name, "kind": kind, "seq": Path(npzs[k]).stem, "frame": fi, "row": [float(v) for v in row]})
    (out_dir / "cases.json").write_text(json.dumps(meta, indent=1))


def run_infer(seq_dirs, onnx, out_dir, conf, spec_conf, win_ms, threads, workers, stride):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    jobs = [(str(s), onnx, out_dir, conf, spec_conf, win_ms, threads, stride) for s in seq_dirs]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(infer_seq, jobs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--trainval_root", required=True)
    ap.add_argument("--test_root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conf", type=float, default=0.01)
    ap.add_argument("--spec_conf", type=float, default=0.01)
    ap.add_argument("--win_ms", type=float, default=100.0)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--stride", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out)
    seqs = lambda r: sorted((p for p in Path(r).iterdir() if (p / "RGB").is_dir()), key=lambda p: int(p.name))
    tv = run_infer(seqs(a.trainval_root), a.onnx, out / "infer_trainval", a.conf, a.spec_conf, a.win_ms, a.threads, a.workers, a.stride)
    te = run_infer(seqs(a.test_root), a.onnx, out / "infer_test", a.conf, a.spec_conf, a.win_ms, a.threads, a.workers, a.stride)
    sel = choose(tv)
    (out / "thresholds_trainval.json").write_text(json.dumps(sel, indent=1))
    D, G, nfr, lat = load(te)
    tp = match(D, G)
    tp30 = match(D, G, 0.3)
    minutes = nfr / FPS / 60.0
    s_thr = sel["score_thr"]
    mot = motion_px(D, s_thr, a.stride)
    res = {"split": "FRED test, all 47 sequences, every frame" if a.stride == 1 else f"FRED test, every {a.stride}th frame",
           "n_seq": len(te), "n_frames": nfr, "minutes": minutes, "n_gt": len(G), "n_det": len(D),
           "detect_ms_median_per_frame": float(np.median(lat) * 1e3), "detect_threads": a.threads,
           "score_thr": s_thr, "win_ms": a.win_ms, "spec_conf": a.spec_conf, "motion_lag_frames": MOTION_LAG, "motion_radius_px": MOTION_RADIUS,
           "onnx": a.onnx, "opencv": cv.__version__, "thresholds_from": "held-out train sequences (thresholds_trainval.json); test never used to choose",
           "a_rgb_only": evaluate(D, G, tp, minutes, s_thr, {}, mot, tp30)}
    base = D[:, 6] >= s_thr
    for n, v in sel["variants"].items():
        k = keep_mask(D, v, mot)
        res[f"b_{n}"] = {"rule": v, **evaluate(D, G, tp, minutes, s_thr, v, mot, tp30),
                         "removed_fp": int((base & ~tp & ~k).sum()), "removed_tp": int((base & tp & ~k).sum())}
    (out / "results_test.json").write_text(json.dumps(res, indent=1))
    pick = sel["web_pick"]
    a_, b_ = res["a_rgb_only"], res[f"b_{pick}"]
    web = {"rgb_only": {"false_alarms": a_["false_alarms"], "false_alarms_per_min": round(a_["false_alarms_per_min"], 2), "recall": round(a_["recall"], 3), "precision": round(a_["precision"], 3), "map50": round(a_["ap50"], 3),
                        "note": f"OpenCV 5 DNN drone detector alone, score >= {s_thr}, false detections over {minutes:.1f} min of FRED test video"},
           "rgb_event": {"false_alarms": b_["false_alarms"], "false_alarms_per_min": round(b_["false_alarms_per_min"], 2), "recall": round(b_["recall"], 3), "precision": round(b_["precision"], 3), "map50": round(b_["ap50"], 3),
                         "note": f"same detector, a box is kept only if its events show a propeller hum ({pick}: {sel['variants'][pick]}), rule chosen on train"},
           "source": f"eval/run_eval.py, {res['split']}; full metrics in results_test.json"}
    (out / "web_result.json").write_text(json.dumps(web, indent=1))
    render_failures(D, G, tp, te, s_thr, keep_mask(D, sel["variants"][pick], mot), out / "failures")
    (out / "DONE").write_text("ok")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

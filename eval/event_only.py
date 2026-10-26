import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from fred_rgb import frame_labels
from run_eval import FPS, ap_curve, load, match, op_point
from strobe.events import HEIGHT, WIDTH, read_events
from strobe.freq import frequency_map


def seq_boxes(a):
    seq_dir, out_dir, stride, win_ms, min_ev, tile = a
    out = Path(out_dir, f"{Path(seq_dir).name}.npz")
    if out.exists():
        return str(out)
    frames, ts, labels = frame_labels(seq_dir)
    ev = read_events(Path(seq_dir, "Event", "events.hdf5"))
    ev["x"] //= tile
    ev["y"] //= tile
    gw, gh = WIDTH // tile, HEIGHT // tile
    rows, gts = [], []
    idx = list(range(stride - 1, len(frames), stride))
    for i in idx:
        for b in labels[i]:
            gts.append([i, *b[:4]])
        t1 = int(ts[i])
        _, smap = frequency_map(ev, t1 - int(win_ms * 1000), t1, (0, 0, gw, gh), min_events=min_ev)
        bw = ((smap > 0) * 255).astype(np.uint8)
        n, lab, st, _ = cv.connectedComponentsWithStats(bw, connectivity=8)
        for c in range(1, n):
            x, y, w, h = st[c, :4]
            s = float(smap[y:y + h, x:x + w][lab[y:y + h, x:x + w] == c].max())
            rows.append([i, x * tile, y * tile, (x + w) * tile, (y + h) * tile, s, s, -1, -1])
    tmp = out.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, det=np.array(rows, np.float64).reshape(-1, 9), gt=np.array(gts, np.float64).reshape(-1, 5),
                        n_frames=len(idx), n_total=len(frames), stride=stride, ts=ts, lat_s=np.zeros(0), frames=np.array([str(f) for f in frames]))
    os.replace(tmp, out)
    return str(out)


def run(root, out_dir, stride, win_ms, min_ev, tile, workers):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    seqs = sorted((p for p in Path(root).iterdir() if (p / "Event" / "events.hdf5").exists()), key=lambda p: int(p.name))
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(seq_boxes, [(str(s), out_dir, stride, win_ms, min_ev, tile) for s in seqs]))


def evaluate(npzs, iou_thr):
    D, G, nfr, _ = load(npzs)
    tp = match(D, G, iou_thr)
    mins = nfr / FPS / 60.0
    return D, G, tp, mins


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trainval_root", required=True)
    ap.add_argument("--test_root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stride", type=int, default=15)
    ap.add_argument("--win_ms", type=float, default=100.0)
    ap.add_argument("--min_events", type=int, default=20)
    ap.add_argument("--tile", type=int, default=8)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    out = Path(a.out)
    tv = run(a.trainval_root, out / "eo_trainval", a.stride, a.win_ms, a.min_events, a.tile, a.workers)
    te = run(a.test_root, out / "eo_test", a.stride, a.win_ms, a.min_events, a.tile, a.workers)
    res = {"n_seq_test": len(te), "stride": a.stride, "win_ms": a.win_ms, "min_events_per_tile": a.min_events, "tile_px": a.tile,
           "method": "strobe.freq.frequency_map on 8x8-pixel tiles over the full 1280x720 sensor; each connected group of active tiles is one box scored by its strongest hum; score threshold chosen on held-out train sequences"}
    for iou_thr in (0.5, 0.1):
        D, G, tp, mins = evaluate(tv, iou_thr)
        cand = sorted(set(np.round(np.quantile(D[:, 6], np.linspace(0, 0.99, 60)), 2))) if len(D) else [0.0]
        s_thr = max(cand, key=lambda s: op_point(D[:, 6] >= s, tp, len(G), mins, D)["f1"])
        D, G, tp, mins = evaluate(te, iou_thr)
        res[f"c_event_only_iou{iou_thr}"] = {"ap": ap_curve(D[:, 6], tp, len(G)), "score_thr_from_trainval": float(s_thr), **op_point(D[:, 6] >= s_thr, tp, len(G), mins, D)}
        res["n_frames"], res["minutes"], res["n_gt"] = int(round(mins * FPS * 60)), mins, len(G)
    (out / "results_event_only.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

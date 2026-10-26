import csv
import json
import sys
from pathlib import Path

import numpy as np

from hertz.freq import MIN_EVENTS

PROPPULSE = {"DJI Mini 3": 223, "DJI Mini 2": 316, "DJI Tello EDU": 539, "Betafpv air75": 738, "DarwinFPV cineape20": 547}
TRAIN_FA = 0.05


def auc(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if len(pos) == 0 or len(neg) == 0:
        return None
    allv = np.concatenate([pos, neg])
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    first = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    ranks = (first + (cnt + 1) / 2)[inv]
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def roc(pos, neg, n=60):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    thr = np.unique(np.quantile(np.concatenate([pos, neg]), np.linspace(0, 1, n)))
    return [[float(t), float((neg >= t).mean()), float((pos >= t).mean())] for t in thr]


def load(d):
    rows = []
    for f in sorted(Path(d).glob("*.csv")):
        with open(f) as fh:
            rows += list(csv.DictReader(fh))
    return rows


def scores(rows, v, kind, W):
    xs = [r for r in rows if r["kind"] == kind and int(r["win_ms"]) == W]
    return xs, np.array([float(r[f"{v}_snr"]) if int(r[f"{v}_n"]) >= MIN_EVENTS else 0.0 for r in xs])


def main(test_dir, train_dir, out_json, out_csv):
    test, train = load(test_dir), load(train_dir)
    variants = sorted({k[:-4] for k in test[0] if k.endswith("_snr")})
    table, models, curves = [], {}, {}
    for W in sorted({int(r["win_ms"]) for r in test}):
        for v in variants:
            _, trd = scores(train, v, "drone", W)
            _, trb = scores(train, v, "busiest", W)
            thr = float(np.quantile(trb, 1 - TRAIN_FA))
            dr, d = scores(test, v, "drone", W)
            _, rn = scores(test, v, "random", W)
            _, bz = scores(test, v, "busiest", W)
            table.append({
                "win_ms": W, "variant": v, "threshold_from_train": round(thr, 3),
                "train_drone_tpr": float((trd >= thr).mean()), "train_busiest_fpr": float((trb >= thr).mean()),
                "n_test_drone": len(d), "n_test_random": len(rn), "n_test_busiest": len(bz),
                "test_drone_tpr": float((d >= thr).mean()), "test_random_fpr": float((rn >= thr).mean()),
                "test_busiest_fpr": float((bz >= thr).mean()),
                "test_auc_drone_vs_random": auc(d, rn), "test_auc_drone_vs_busiest": auc(d, bz),
                "train_auc_drone_vs_busiest": auc(trd, trb)})
            curves[f"{W}|{v}"] = {"drone_vs_busiest": roc(d, bz), "drone_vs_random": roc(d, rn)}
            for m in sorted({r["model"] for r in dr}):
                sel = np.array([r["model"] == m for r in dr])
                hz = np.array([float(r[f"{v}_hz"]) for r in dr])[sel & (d >= thr)]
                models.setdefault(f"{W}|{v}", {})[m] = {
                    "n_boxes": int(sel.sum()), "n_seq": len({r["seq"] for r in dr if r["model"] == m}),
                    "share_above_threshold": float((d[sel] >= thr).mean()),
                    "median_peak_hz": float(np.median(hz)) if len(hz) else None,
                    "iqr_peak_hz": [float(np.percentile(hz, 25)), float(np.percentile(hz, 75))] if len(hz) else None,
                    "proppulse_median_hz": PROPPULSE.get(m),
                    "hist_100hz_bins_100_1100": np.histogram(hz, bins=np.arange(100, 1101, 100))[0].tolist()}
    meta = {"min_events": MIN_EVENTS, "train_fa_target_on_busiest": TRAIN_FA, "n_test_rows": len(test), "n_train_rows": len(train),
            "n_test_seq": len({r["seq"] for r in test}), "n_train_seq": len({r["seq"] for r in train})}
    Path(out_json).write_text(json.dumps({"meta": meta, "table": table, "per_model": models, "roc": curves}, indent=1))
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, list(table[0]))
        w.writeheader()
        w.writerows(table)


if __name__ == "__main__":
    main(*sys.argv[1:5])

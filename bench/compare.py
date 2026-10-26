import argparse
import json

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("other")
    ap.add_argument("--out")
    a = ap.parse_args()
    x, y = np.load(a.base), np.load(a.other)
    rows = []
    for k in sorted(set(x.files) | set(y.files)):
        if k not in x.files or k not in y.files:
            rows.append({"op": k, "status": "missing"})
            continue
        p, q = x[k], y[k]
        if p.shape != q.shape:
            rows.append({"op": k, "status": "shape", "base": list(p.shape), "other": list(q.shape)})
            continue
        d = np.abs(p.astype(np.float64) - q.astype(np.float64))
        scale = float(np.abs(p).max()) or 1.0
        rows.append({"op": k, "status": "identical" if not d.any() else "differs", "max_abs": float(d.max()), "mean_abs": float(d.mean()),
                     "max_rel_to_range": float(d.max() / scale), "frac_elems_diff": float((d > 0).mean()), "frac_elems_diff_gt1": float((d > 1).mean())})
    for r in rows:
        print(json.dumps(r))
    if a.out:
        json.dump({"base": a.base, "other": a.other, "rows": rows}, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()

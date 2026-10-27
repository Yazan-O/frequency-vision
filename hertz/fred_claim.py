import csv
import os
import sys
from pathlib import Path

import cv2 as cv
import h5py
import numpy as np

from hertz.events import HEIGHT, WIDTH, _decode_rows, read_boxes, read_events
from hertz.freq import _window, box_spectrum

WINDOWS_MS = (20, 50, 100, 200)
VARIANTS = (("count", "count", False, False), ("signed", "signed", False, False), ("signed_mask", "signed", True, False),
            ("signed_notch", "signed", False, True), ("signed_mask_notch", "signed", True, True))
MARGIN = 0.5
FIELDS = ["seq", "model", "obj", "t_us", "win_ms", "kind", "x1", "y1", "x2", "y2", "n_box"] + [
    f"{v}_{k}" for v, _, _, _ in VARIANTS for k in ("hz", "snr", "n")]


def dilate(b, frac=MARGIN):
    m = frac * max(b[2] - b[0], b[3] - b[1])
    return (b[0] - m, b[1] - m, b[2] + m, b[3] + m)


def _overlaps(b, others):
    return any(b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3] for o in others)


def random_box(rng, w, h, drones):
    for _ in range(100):
        x = rng.uniform(0, WIDTH - w)
        y = rng.uniform(0, HEIGHT - h)
        b = (x, y, x + w, y + h)
        if not _overlaps(b, drones):
            return b
    return None


def busiest_box(ev, w, h, drones):
    if len(ev["x"]) == 0:
        return None
    xy = np.stack([ev["x"], ev["y"]], 1).astype(np.float32).reshape(-1, 1, 2)
    img = cv.calcHist([xy], [0, 1], None, [WIDTH, HEIGHT], [0, WIDTH, 0, HEIGHT]).T.copy()
    iw, ih = max(int(round(w)), 1), max(int(round(h)), 1)
    s = cv.boxFilter(img, -1, (iw, ih), anchor=(0, 0), normalize=False, borderType=cv.BORDER_CONSTANT)
    s[HEIGHT - ih + 1 :, :] = -1
    s[:, WIDTH - iw + 1 :] = -1
    for d in drones:
        x0, y0 = max(int(d[0] - iw), 0), max(int(d[1] - ih), 0)
        s[y0 : int(np.ceil(d[3])) + 1, x0 : int(np.ceil(d[2])) + 1] = -1
    _, mx, _, (x, y) = cv.minMaxLoc(s)
    if mx <= 0:
        return None
    return (float(x), float(y), float(x + iw), float(y + ih))


def frames_with_events(h5, keys, block_us=10_000_000):
    lead = max(WINDOWS_MS) * 1000
    for b0 in range(0, keys[-1] + 1, block_us):
        ks = [k for k in keys if b0 <= k < b0 + block_us]
        if ks:
            ev = read_events(h5, max(ks[0] - lead, 0), ks[-1] + 1)
            for k in ks:
                yield k, ev


def run(seq_dir, out_csv, stride=5):
    seqp = Path(seq_dir)
    h5 = seqp / "Event" / "events.hdf5"
    boxes = read_boxes(seqp / "coordinates.txt")
    keys = sorted(boxes)[::stride]
    with h5py.File(h5, "r") as h:
        t_first = int(_decode_rows(h["CD/events"], 0, 1)["t"][0])
    seq = seqp.name
    rng = np.random.default_rng(int(seq))
    rows = []
    for tk, ev in frames_with_events(h5, keys):
        objs = boxes[tk]
        drones = [dilate(o[:4]) for o in objs]
        for o in objs:
            w, h = o[2] - o[0], o[3] - o[1]
            if w < 4 or h < 4:
                continue
            for W in WINDOWS_MS:
                t0, t1 = tk - W * 1000, tk
                if t0 < t_first:
                    continue
                cand = [("drone", o[:4]), ("random", random_box(rng, w, h, drones)),
                        ("busiest", busiest_box(_window(ev, t0, t1), w, h, drones))]
                for kind, b in cand:
                    if b is None:
                        continue
                    r = {"seq": seq, "model": o[5], "obj": o[4], "t_us": tk, "win_ms": W, "kind": kind,
                         "x1": round(b[0], 1), "y1": round(b[1], 1), "x2": round(b[2], 1), "y2": round(b[3], 1)}
                    for name, sig, mask, notch in VARIANTS:
                        q = box_spectrum(ev, b, t0, t1, use_mask=mask, signal=sig, notch=notch)
                        r["n_box"] = q["n_box"]
                        r[f"{name}_hz"] = round(q["peak_hz"], 2)
                        r[f"{name}_snr"] = round(q["snr"], 3)
                        r[f"{name}_n"] = q["n_events"]
                    rows.append(r)
    tmp = Path(str(out_csv) + ".tmp")
    with open(tmp, "w", newline="") as f:
        wr = csv.DictWriter(f, FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    tmp.replace(out_csv)
    return len(rows)


if __name__ == "__main__":
    cv.setNumThreads(1)
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for s in sys.argv[3:]:
        dst = out / f"{s}.csv"
        if dst.exists():
            continue
        print(s, run(root / s, dst, int(os.environ.get("HERTZ_STRIDE", 5))), flush=True)

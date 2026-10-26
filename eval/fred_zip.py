import zipfile
from pathlib import PurePosixPath

import numpy as np

from fred_rgb import _EVF, _LINE


def parse_coords_text(text):
    out = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        t = int(round(float(m.group(1)) * 1e6))
        out.setdefault(t, []).append((float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)), int(m.group(6)), m.group(7).strip()))
    return out


def assign_labels(ts, coords, tol_us=5000):
    labels = {i: [] for i in range(len(ts))}
    for t, boxes in coords.items():
        i = int(np.searchsorted(ts, t))
        cand = [j for j in (i - 1, i) if 0 <= j < len(ts)]
        if not cand:
            continue
        j = min(cand, key=lambda k: abs(ts[k] - t))
        if abs(ts[j] - t) <= tol_us:
            labels[j].extend(boxes)
    return labels


def zip_frame_labels(zip_path, tol_us=5000):
    z = zipfile.ZipFile(zip_path)
    names = z.namelist()
    rgb = sorted((n for n in names if "/RGB/" in n and n.endswith(".jpg") and "/._" not in n), key=lambda n: PurePosixPath(n).name)
    ev = np.array(sorted(int(m.group(1)) for n in names if "/Frames/" in n and (m := _EVF.search(n))), np.int64)
    ts = ev if len(ev) == len(rgb) else np.round((np.arange(len(rgb)) + 1) * 1e6 / 30.0).astype(np.int64)
    cn = [n for n in names if n.endswith("/coordinates_rgb.txt")]
    coords = parse_coords_text(z.read(cn[0]).decode()) if cn else {}
    return z, rgb, ts, assign_labels(ts, coords, tol_us), len(ev) == len(rgb)

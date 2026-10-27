import json
import re
import sys
from pathlib import Path

import numpy as np

USED = {"111", "210", "90", "115", "138", "163", "41", "142", "110", "12"}
PER_KIND = 4
SPAN = 3.0


def rgb_span(d):
    st = []
    for f in (d / "RGB").glob("*.jpg"):
        m = re.search(r"_(\d+)_(\d+)_(\d+\.\d+)\.jpg$", f.name)
        st.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))
    st = np.sort(st)
    return float(st[-1] - st[0])


def gt(d):
    rows = []
    for line in (d / "coordinates.txt").read_text().splitlines():
        if line.strip():
            t, rest = line.split(":", 1)
            p = [float(x) for x in rest.split(",")[:4]]
            rows.append((float(t), p[2] - p[0]))
    return sorted(rows)


def covered(ts, a, b, gap=0.1):
    s = ts[(ts >= a) & (ts <= b)]
    return len(s) > 0 and s[0] - a <= gap and b - s[-1] <= gap and (len(s) < 2 or np.diff(s).max() <= gap)


def pick(sid, d, kind):
    dur = rgb_span(d)
    rows = gt(d)
    ts = np.array([r[0] for r in rows])
    ws = np.array([r[1] for r in rows])
    if kind == "late":
        if not len(ts):
            return None
        f = float(ts[0])
        if f >= 4.0 and f + SPAN <= dur - 1.0:
            return {"t0": round(f - 2.0, 3), "t1": round(f + SPAN, 3), "drone": True, "entry": round(f, 3)}
        return None
    for t0 in np.arange(5.0, dur - SPAN - 1.0, 0.5):
        a, b = float(t0), float(t0 + SPAN)
        if kind == "background":
            if not ((ts >= a - 1.0) & (ts <= b + 1.0)).any():
                return {"t0": a, "t1": b, "drone": False, "entry": None}
            continue
        if not covered(ts, a, b):
            continue
        med = float(np.median(ws[(ts >= a) & (ts <= b)]))
        if (kind == "clear" and med >= 60) or (kind == "distant" and med <= 30):
            return {"t0": a, "t1": b, "drone": True, "entry": None}
    return None


def main(seq_root, out):
    seqs = sorted((p.name for p in Path(seq_root).iterdir() if p.is_dir()), key=int)
    taken, scen = set(USED), []
    for kind in ("late", "background", "distant", "clear"):
        n = 0
        for sid in seqs:
            if sid in taken or n >= PER_KIND:
                continue
            s = pick(sid, Path(seq_root) / sid, kind)
            if s:
                taken.add(sid)
                n += 1
                scen.append({"id": f"{kind}_{sid}", "kind": kind, "seq": sid, **s, "held_out": True})
    Path(out).write_text(json.dumps({"scenarios": scen}, indent=1))
    for s in scen:
        print(s)


if __name__ == "__main__":
    main(*sys.argv[1:3])

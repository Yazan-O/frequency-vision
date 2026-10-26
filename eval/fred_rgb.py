import re
from pathlib import Path

import numpy as np

_LINE = re.compile(r"^\s*([0-9.]+)\s*:\s*([-0-9.eE]+),\s*([-0-9.eE]+),\s*([-0-9.eE]+),\s*([-0-9.eE]+),\s*(\d+),\s*(.*)$")
_EVF = re.compile(r"frame_(\d+)\.png$")


def rgb_frames(seq_dir):
    return sorted(Path(seq_dir, "RGB").glob("Video_*.jpg"))


def event_frame_us(seq_dir):
    d = Path(seq_dir, "Event", "Frames")
    if not d.is_dir():
        return None
    return np.array(sorted(int(m.group(1)) for p in d.iterdir() if (m := _EVF.search(p.name))), np.int64)


def frame_times_us(seq_dir, n_rgb):
    us = event_frame_us(seq_dir)
    if us is not None and len(us) == n_rgb:
        return us
    return np.round((np.arange(n_rgb) + 1) * 1e6 / 30.0).astype(np.int64)


def parse_coords(path):
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        t = int(round(float(m.group(1)) * 1e6))
        out.setdefault(t, []).append((float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)), int(m.group(6)), m.group(7).strip()))
    return out


def frame_labels(seq_dir, tol_us=5000):
    frames = rgb_frames(seq_dir)
    ts = frame_times_us(seq_dir, len(frames))
    labels = {i: [] for i in range(len(frames))}
    for t, boxes in parse_coords(Path(seq_dir, "coordinates_rgb.txt")).items():
        i = int(np.searchsorted(ts, t))
        cand = [j for j in (i - 1, i) if 0 <= j < len(ts)]
        if not cand:
            continue
        j = min(cand, key=lambda k: abs(ts[k] - t))
        if abs(ts[j] - t) <= tol_us:
            labels[j].extend(boxes)
    return frames, ts, labels

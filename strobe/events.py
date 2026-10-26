import ctypes
import os
import re
from pathlib import Path

import h5py
import numpy as np

EV = np.dtype({"names": ["x", "y", "p", "t"], "formats": ["<u2", "<u2", "<i2", "<i8"], "offsets": [0, 2, 4, 8], "itemsize": 16})
FRAME_US = 33333
WIDTH, HEIGHT = 1280, 720
_lib = None


def _ecf():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(os.environ.get("STROBE_ECF_LIB", str(Path(__file__).parent / "ecf" / "libecf_shim.so")))
        _lib.ecf_size.restype = ctypes.c_size_t
        _lib.ecf_size.argtypes = [ctypes.c_char_p]
        _lib.ecf_decode.restype = ctypes.c_size_t
        _lib.ecf_decode.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
    return _lib


def _decode_rows(d, i0, i1):
    if "36559" not in d._filters:
        return d[i0:i1]
    c = d.chunks[0]
    out = np.empty(i1 - i0, EV)
    for k in range(i0 // c, (i1 - 1) // c + 1):
        start = k * c
        mask, raw = d.id.read_direct_chunk((start,))
        if mask & 1:
            buf = np.frombuffer(raw, EV)
        else:
            buf = np.empty(_ecf().ecf_size(raw) // 16 + 1, EV)
            buf = buf[: _ecf().ecf_decode(raw, len(raw), buf.ctypes.data) // 16]
        a, b = max(i0, start), min(i1, start + len(buf), d.shape[0])
        out[a - i0 : b - i0] = buf[a - start : b - start]
    return out


def read_events(h5_path, t0_us=None, t1_us=None):
    with h5py.File(h5_path, "r") as h:
        d = h["CD/events"]
        n = d.shape[0]
        idx = h["CD/indexes"]
        off = int(idx.attrs.get("offset", 0))
        idx = idx[:]
        ts, ids = idx["ts"] - off, idx["id"].astype(np.int64)
        i0 = 0 if t0_us is None else int(ids[max(np.searchsorted(ts, t0_us, "right") - 1, 0)])
        j = len(ts) if t1_us is None else np.searchsorted(ts, t1_us, "left") + 1
        i1 = n if j >= len(ts) else int(ids[j])
        ev = _decode_rows(d, i0, max(i1, i0 + 1))
    if t0_us is not None or t1_us is not None:
        lo = -np.inf if t0_us is None else t0_us
        hi = np.inf if t1_us is None else t1_us
        ev = ev[(ev["t"] >= lo) & (ev["t"] < hi)]
    return {"x": ev["x"].astype(np.int32), "y": ev["y"].astype(np.int32), "t": ev["t"].astype(np.int64), "p": ev["p"].astype(np.int8)}


def read_evt2(raw_path):
    data = Path(raw_path).read_bytes()
    pos = 0
    while data.startswith(b"%", pos):
        pos = data.index(b"\n", pos) + 1
    w = np.frombuffer(data, np.uint32, (len(data) - pos) // 4, pos)
    kind = w >> 28
    high = np.where(kind == 0x8, w & 0x0FFFFFFF, 0).astype(np.int64)
    high = np.maximum.accumulate(np.where(kind == 0x8, high, -1))
    cd = (kind <= 1) & (high >= 0)
    t = (high[cd] << 6) | ((w[cd] >> 22) & 0x3F).astype(np.int64)
    o = np.argsort(t, kind="stable")
    return {"x": ((w[cd] >> 11) & 0x7FF).astype(np.int32)[o], "y": (w[cd] & 0x7FF).astype(np.int32)[o],
            "t": t[o], "p": kind[cd].astype(np.int8)[o]}


def read_boxes(txt):
    boxes = {}
    if not Path(txt).exists():
        return boxes
    for line in Path(txt).read_text().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        f = [s.strip() for s in v.split(",")]
        t = int(round(float(k) * 1e6))
        boxes.setdefault(t, []).append((float(f[0]), float(f[1]), float(f[2]), float(f[3]), int(f[4]), f[5]))
    return boxes


def _clock_us(name):
    h, m, s = re.search(r"_(\d+)_(\d+)_(\d+\.\d+)\.jpg$", name).groups()
    return int(round((int(h) * 3600 + int(m) * 60 + float(s)) * 1e6))


def rgb_frames(seq_dir):
    files = sorted(Path(seq_dir, "RGB").glob("*.jpg"), key=lambda p: _clock_us(p.name))
    if not files:
        return []
    c0 = _clock_us(files[0].name)
    return [(_clock_us(p.name) - c0 + FRAME_US, str(p)) for p in files]


def load_sequence(path, t0_us=None, t1_us=None):
    seq = Path(path)
    return {
        "events": read_events(seq / "Event" / "events.hdf5", t0_us, t1_us),
        "frames": rgb_frames(seq),
        "boxes": read_boxes(seq / "coordinates.txt"),
        "rgb_boxes": read_boxes(seq / "coordinates_rgb.txt"),
        "width": WIDTH,
        "height": HEIGHT,
    }

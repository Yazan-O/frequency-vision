import json
from pathlib import Path

import cv2 as cv
import numpy as np

HOT_RATE = 120.0
HOT_MAX_AREA = 8


class Slice:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.meta = json.loads((self.folder / "meta.json").read_text())
        z = np.load(self.folder / "events.npz")
        self.x, self.y, self.p = z["x"], z["y"], z["p"]
        self.t = z["t"].astype(np.int64)
        self.origin = float(self.meta["origin_s"])
        self.t_lo, self.t_hi = float(self.meta["t_lo"]), float(self.meta["t_hi"])
        self.width, self.height = int(self.meta["width"]), int(self.meta["height"])
        self.hot = self._hot_pixels()
        self.frame_t = np.array([f["t"] for f in self.meta["frames"]])
        self.frame_files = [f["file"] for f in self.meta["frames"]]

    def _hot_pixels(self, rate=HOT_RATE, warm=1.0):
        n = int(np.searchsorted(self.t, int(warm * 1e6)))
        pix = self.y[:n].astype(np.int64) * self.width + self.x[:n]
        c = np.bincount(pix, minlength=self.width * self.height) / warm
        m = (c > rate).reshape(self.height, self.width).astype(np.uint8)
        n, lab, st, _ = cv.connectedComponentsWithStats(m, connectivity=8)
        small = np.flatnonzero(st[:, cv.CC_STAT_AREA] <= HOT_MAX_AREA)
        hot = np.flatnonzero(np.isin(lab, small[small > 0]).ravel())
        if len(hot):
            keep = ~np.isin(self.y.astype(np.int64) * self.width + self.x, hot)
            self.x, self.y, self.p, self.t = self.x[keep], self.y[keep], self.p[keep], self.t[keep]
        return [[int(h % self.width), int(h // self.width)] for h in hot]

    def us(self, t):
        return int(round((t - self.origin) * 1e6))

    def window(self, t0, t1):
        i0, i1 = np.searchsorted(self.t, self.us(t0)), np.searchsorted(self.t, self.us(t1))
        return slice(int(i0), int(i1))

    def events(self, t0, t1, box=None):
        s = self.window(t0, t1)
        x, y, t = self.x[s], self.y[s], self.t[s] - self.us(t0)
        if box is not None:
            x0, y0, x1, y1 = box
            m = (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
            x, y, t = x[m], y[m], t[m]
        return x, y, t

    def frame(self, t):
        if not len(self.frame_t):
            return None, None
        i = int(np.searchsorted(self.frame_t, t, side="right")) - 1
        if i < 0:
            return None, None
        return cv.imread(str(self.folder / "rgb" / self.frame_files[i])), float(self.frame_t[i])

    def gt_at(self, t, tol=0.034):
        rows = [r for r in self.meta["gt"] if abs(r["t"] - t) <= tol]
        return [r["box"] for r in rows]


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self._cache = {}
        self.index = {}
        for d in sorted(self.root.glob("*/meta.json")):
            m = json.loads(d.read_text())
            self.index[m["seq"]] = d.parent

    def seqs(self):
        return sorted(self.index)

    def get(self, seq):
        seq = str(seq)
        if seq not in self.index:
            raise KeyError(f"no data for sequence {seq}")
        if seq not in self._cache:
            self._cache[seq] = Slice(self.index[seq])
        return self._cache[seq]

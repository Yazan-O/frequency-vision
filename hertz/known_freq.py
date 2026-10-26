import json
import sys
from pathlib import Path

import h5py
import numpy as np

from hertz.events import read_events, read_evt2
from hertz.freq import box_spectrum, frequency_map


def sensor_size(h5):
    with h5py.File(h5, "r") as h:
        g = h.attrs.get("geometry", "1280x720")
    w, hh = (int(v) for v in str(g).split("x"))
    return w, hh


def measure(name, h5, roi, gt, dur_us=1_000_000, band=(1.0, 2500.0)):
    raw = open(h5, "rb").read(1) == b"%"
    ev = read_evt2(h5) if raw else read_events(h5)
    t0 = int(ev["t"][0])
    t1 = t0 + dur_us
    if roi is None:
        w, h = (int(ev["x"].max()) + 1, int(ev["y"].max()) + 1) if raw else sensor_size(h5)
        roi = (0, 0, w, h)
    out = {"name": name, "gt_hz": gt, "roi": list(roi), "window_ms": dur_us / 1000, "n_events_window": int(np.searchsorted(ev["t"], t1) - np.searchsorted(ev["t"], t0))}
    for sig in ("signed", "count"):
        r = box_spectrum(ev, roi, t0, t1, band=band, use_mask=False, signal=sig)
        out[f"{sig}_hz"] = round(r["peak_hz"], 2)
        out[f"{sig}_snr"] = round(r["snr"], 2)
    fmap, smap = frequency_map(ev, t0, t0 + 500_000, roi, fs=5000, band=band)
    act = fmap[fmap > 0]
    hist = np.round(act).astype(int)
    vals, cnt = np.unique(hist, return_counts=True)
    top = vals[np.argsort(cnt)[::-1][:5]]
    out["map_active_px"] = int(len(act))
    out["map_median_hz"] = round(float(np.median(act)), 2) if len(act) else None
    out["map_top_hz"] = [int(v) for v in top]
    return out


if __name__ == "__main__":
    eeppr, proph, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    cfg = json.loads((eeppr / "config.json").read_text())
    rows = []
    for name in cfg["sequence_names"]:
        info = cfg["sequence_info"][name]
        h5 = eeppr / info["hdf5_filepath"]
        if not h5.exists():
            rows.append({"name": name, "gt_hz": info["gt_freq"], "missing": str(h5.name)})
            continue
        r = info["roi"]
        rows.append(measure(name, h5, (r["x0"], r["y0"], r["x1"], r["y1"]), info["gt_freq"]))
        print(rows[-1], flush=True)
    if proph.exists():
        rows.append(measure("prophesee_monitoring_40_50hz", proph, None, "40 and 50", band=(5.0, 500.0)))
        print(rows[-1], flush=True)
    dst.write_text(json.dumps(rows, indent=1))

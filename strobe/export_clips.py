import json
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

from strobe.events import HEIGHT, WIDTH, read_boxes, read_events, rgb_frames
from strobe.fred_claim import busiest_box
from strobe.freq import BAND, _window, box_spectrum, frequency_map

MAX_EVENTS = 3_000_000


def _boxes(b, t0, t1):
    ks = [k for k in sorted(b) if t0 <= k < t1]
    rows = [(k, *o[:5], o[5]) for k in ks for o in b[k]]
    if not rows:
        return np.zeros(0, np.int32), np.zeros((0, 4), np.float32), np.zeros(0, np.int16), np.zeros(0, "U32")
    return (np.array([r[0] - t0 for r in rows], np.int32), np.array([r[1:5] for r in rows], np.float32),
            np.array([r[5] for r in rows], np.int16), np.array([r[6] for r in rows], "U32"))


def export(seq_dir, t0_s, dur_s, out, note, win_ms=100, threshold=None):
    seq = Path(seq_dir)
    t0, t1 = int(t0_s * 1e6), int((t0_s + dur_s) * 1e6)
    lead = win_ms * 1000
    ev = read_events(seq / "Event" / "events.hdf5", t0 - lead, t1)
    gb = read_boxes(seq / "coordinates.txt")
    gt_t, gt_box, gt_id, gt_model = _boxes(gb, t0, t1)
    rgb_t, rgb_box, rgb_id, rgb_model = _boxes(read_boxes(seq / "coordinates_rgb.txt"), t0, t1)
    spec = {k: [] for k in ("t", "kind", "box", "peak_hz", "snr", "n_events", "power")}
    for i in range(len(gt_t)):
        tk = int(gt_t[i]) + t0
        neg = busiest_box(_window(ev, tk - lead, tk), *(gt_box[i, 2:] - gt_box[i, :2]), [tuple(b) for b in gt_box[gt_t == gt_t[i]]])
        for kind, b in (("drone", tuple(gt_box[i])), ("busiest", neg)):
            if b is None:
                continue
            r = box_spectrum(ev, b, tk - lead, tk)
            m = r["freqs"] <= BAND[1]
            spec["t"].append(tk - t0)
            spec["kind"].append(kind)
            spec["box"].append(b)
            spec["peak_hz"].append(r["peak_hz"])
            spec["snr"].append(r["snr"])
            spec["n_events"].append(r["n_events"])
            pw = r["power"][m]
            spec["power"].append(pw / max(float(pw.max()), 1e-12))
    freqs = r["freqs"][m] if len(gt_t) else np.zeros(0)
    fmap = np.zeros((0, 0), np.float16)
    fmap_box = np.zeros(4, np.float32)
    if len(gt_t):
        i = len(gt_t) // 2
        x1, y1, x2, y2 = gt_box[i]
        fmap_box = np.array([max(x1 - 16, 0), max(y1 - 16, 0), min(x2 + 16, WIDTH), min(y2 + 16, HEIGHT)], np.float32)
        tk = int(gt_t[i]) + t0
        fmap = frequency_map(ev, tk - lead, tk, tuple(fmap_box), min_events=5)[0].astype(np.float16)
    ev = _window(ev, t0, t1)
    roi = np.array([0, 0, WIDTH, HEIGHT], np.float32)
    if len(ev["t"]) > MAX_EVENTS and len(gt_box):
        roi = np.array([max(gt_box[:, 0].min() - 150, 0), max(gt_box[:, 1].min() - 150, 0),
                        min(gt_box[:, 2].max() + 150, WIDTH), min(gt_box[:, 3].max() + 150, HEIGHT)], np.float32)
        m = (ev["x"] >= roi[0]) & (ev["x"] < roi[2]) & (ev["y"] >= roi[1]) & (ev["y"] < roi[3])
        ev = {k: v[m] for k, v in ev.items()}
    frames = [(t, p) for t, p in rgb_frames(seq) if t0 <= t < t1]
    jpgs = [cv.imencode(".jpg", cv.resize(cv.imread(p), (640, 360), interpolation=cv.INTER_AREA), [cv.IMWRITE_JPEG_QUALITY, 80])[1].ravel() for _, p in frames]
    meta = {"seq": seq.name, "t0_us": t0, "dur_s": dur_s, "sensor": [WIDTH, HEIGHT], "events_roi": roi.tolist(), "frame_size": [640, 360],
            "window_ms": win_ms, "band_hz": list(BAND), "threshold_from_train": threshold, "note": note,
            "times": "all *_t arrays are int32 microseconds relative to t0_us", "spec_power": "per-row power divided by its row maximum",
            "source": "FRED test split, Apache-2.0 per its Hugging Face card (huggingface.co/datasets/GabrieleMagrini/FRED)"}
    np.savez_compressed(
        out, meta=np.array(json.dumps(meta)),
        ev_x=ev["x"].astype(np.uint16), ev_y=ev["y"].astype(np.uint16), ev_t=(ev["t"] - t0).astype(np.int32), ev_p=ev["p"].astype(np.uint8),
        frame_t=np.array([t - t0 for t, _ in frames], np.int32), frame_jpg=np.concatenate(jpgs) if jpgs else np.zeros(0, np.uint8),
        frame_jpg_offsets=np.cumsum([0] + [len(j) for j in jpgs]).astype(np.int64),
        gt_t=gt_t, gt_box=gt_box, gt_id=gt_id, gt_model=gt_model, rgb_gt_t=rgb_t, rgb_gt_box=rgb_box, rgb_gt_id=rgb_id, rgb_gt_model=rgb_model,
        spec_t=np.array(spec["t"], np.int32), spec_kind=np.array(spec["kind"], "U8"), spec_box=np.array(spec["box"], np.float32).reshape(-1, 4),
        spec_peak_hz=np.array(spec["peak_hz"], np.float32), spec_snr=np.array(spec["snr"], np.float32),
        spec_n_events=np.array(spec["n_events"], np.int32), spec_freqs=freqs.astype(np.float32),
        spec_power=np.array(spec["power"], np.float32).reshape(len(spec["t"]), -1).astype(np.float16),
        fmap=fmap, fmap_box=fmap_box)


if __name__ == "__main__":
    cv.setNumThreads(4)
    root, out, thr = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    for spec in sys.argv[4:]:
        name, seq, t0, dur, note = spec.split(":", 4)
        export(root / seq, float(t0), float(dur), out / f"{name}.npz", note, threshold=thr)
        print(name, (out / f"{name}.npz").stat().st_size, flush=True)

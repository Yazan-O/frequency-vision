import math
import os
import threading
from pathlib import Path

import cv2 as cv
import numpy as np

try:
    from hertz import freq as L1
except Exception:
    L1 = None

FS = L1.FS if L1 else 10000
BAND = L1.BAND if L1 else (150.0, 1000.0)
CLEAR_SNR = L1.CLEAR_SNR if L1 else 15.0
MIN_EVENTS = L1.MIN_EVENTS if L1 else 200
AMB_SNR = L1.AMBIGUOUS_SNR if L1 else 7.9
MIN_AMB_EVENTS = 100
SOURCE = {"spectrum": "hertz.freq (lane L1)" if L1 else "agent stub (lane L1 missing)", "detect": "not loaded yet"}


def mains_like(f):
    return bool(any(abs(f - k * base) < 2.0 for base in (50.0, 60.0) for k in range(1, 21)))


def verdict(snr, n, clear):
    if clear:
        return "hum"
    if n >= MIN_AMB_EVENTS and snr >= AMB_SNR:
        return "ambiguous"
    return "none"


def _ev(sl, t0, t1):
    s = sl.window(t0, t1)
    return {"x": sl.x[s].astype(np.int32), "y": sl.y[s].astype(np.int32), "t": sl.t[s], "p": sl.p[s].astype(np.int8)}


def _stub_box_spectrum(ev, box, t0_us, t1_us):
    x0, y0, x1, y1 = box
    m = (ev["x"] >= x0) & (ev["x"] < x1) & (ev["y"] >= y0) & (ev["y"] < y1)
    t, p = ev["t"][m] - t0_us, ev["p"][m]
    nb = max(4, int(round((t1_us - t0_us) * FS / 1e6)))
    k = np.minimum(t * nb // max(t1_us - t0_us, 1), nb - 1)
    sig = (np.bincount(k[p > 0], minlength=nb) - np.bincount(k[p <= 0], minlength=nb)).astype(np.float32)[None, :]
    sig = (sig - sig.mean()) * cv.createHanningWindow((nb, 3), cv.CV_32F)[1:2]
    n = cv.getOptimalDFTSize(4 * nb)
    sig = cv.copyMakeBorder(sig, 0, 0, 0, n - nb, cv.BORDER_CONSTANT, value=0)
    f = cv.dft(sig, flags=cv.DFT_COMPLEX_OUTPUT)
    pw = cv.magnitude(f[..., 0], f[..., 1]).ravel()[: n // 2 + 1] ** 2
    hz = np.arange(n // 2 + 1) * FS / n
    band = (hz >= BAND[0]) & (hz <= BAND[1])
    i = int(np.argmax(pw[band]))
    med = float(np.median(pw[band]))
    snr = float(pw[band][i] / med) if med > 0 else 0.0
    return {"peak_hz": float(hz[band][i]), "snr": snr, "n_events": int(m.sum()), "clear": bool(snr >= CLEAR_SNR and m.sum() >= MIN_EVENTS)}


def box_spectrum(sl, box, t0, t1):
    t0_us, t1_us = sl.us(t0), sl.us(t1)
    ev = _ev(sl, t0, t1)
    r = L1.box_spectrum(ev, box, t0_us, t1_us) if L1 else _stub_box_spectrum(ev, box, t0_us, t1_us)
    f, snr, n = float(r["peak_hz"]), float(r["snr"]), int(r["n_events"])
    return {"peak_hz": round(f, 1), "snr": round(snr, 2), "n_events": n, "resolution_hz": round(1.0 / (t1 - t0), 2),
            "mains_like": mains_like(f), "verdict": verdict(snr, n, bool(r["clear"])), "window_ms": round((t1 - t0) * 1000),
            "thresholds": {"hum_snr": CLEAR_SNR, "ambiguous_snr": AMB_SNR, "min_events": MIN_EVENTS}, "source": SOURCE["spectrum"]}


def frequency_map(sl, t0, t1):
    if L1 is None:
        return {"error": "frequency_map needs hertz.freq (lane L1)"}
    ev = _ev(sl, t0, t1)
    fmap, smap = L1.frequency_map(ev, sl.us(t0), sl.us(t1), (0, 0, sl.width, sl.height))
    act = smap > 0
    strong = smap >= CLEAR_SNR
    dom, share = None, 0.0
    if strong.any():
        q = np.round(fmap[strong] / 5) * 5
        vals, c = np.unique(q, return_counts=True)
        dom, share = float(vals[c.argmax()]), float(c.max() / max(1, act.sum()))
    bw = cv.dilate(strong.astype(np.uint8) * 255, cv.getStructuringElement(cv.MORPH_ELLIPSE, (15, 15)))
    n, lab, st, _ = cv.connectedComponentsWithStats(bw)
    spots = []
    for i in range(1, n):
        x, y, w, h, _ = (int(v) for v in st[i])
        m = (lab == i) & strong
        if m.sum() < 3:
            continue
        spots.append({"box": [x, y, x + w, y + h], "hum_pixels": int(m.sum()), "median_hz": round(float(np.median(fmap[m])), 1),
                      "max_snr": round(float(smap[m].max()), 2)})
    spots.sort(key=lambda d: -d["hum_pixels"])
    return {"active_pixels": int(act.sum()), "hum_pixels": int(strong.sum()), "dominant_hz": dom, "dominant_share": round(share, 4),
            "hum_spots": spots[:6], "source": SOURCE["spectrum"]}


DNN_PATH = os.environ.get("HERTZ_DETECTOR_ONNX", str(Path(__file__).resolve().parents[3] / "build" / "models" / "strobe_drone_960x544.onnx"))
DNN_CONF = 0.125
_DNN = {"net": None, "tried": False, "error": None}
_LOCK = threading.Lock()


def _dnn():
    with _LOCK:
        return _dnn_load()


def _dnn_load():
    if not _DNN["tried"]:
        _DNN["tried"] = True
        try:
            from hertz.detect import Detector
            _DNN["net"] = Detector(DNN_PATH, conf=DNN_CONF)
            SOURCE["detect"] = f"hertz.detect.Detector (lane L2, {Path(DNN_PATH).name}, score >= {DNN_CONF})"
        except Exception as e:
            _DNN["error"] = f"{type(e).__name__}: {str(e)[:150]}"
            SOURCE["detect"] = f"FALLBACK event blobs (detector unavailable: {_DNN['error']})"
    return _DNN["net"]


def _blobs(sl, t, win):
    x, y, _ = sl.events(t - win, t)
    img = np.bincount(y.astype(np.int64) * sl.width + x, minlength=sl.width * sl.height).reshape(sl.height, sl.width)
    img = np.minimum(img, 255).astype(np.uint8)
    img = cv.GaussianBlur(img, (5, 5), 0)
    _, bw = cv.threshold(img, 1, 255, cv.THRESH_BINARY)
    bw = cv.morphologyEx(bw, cv.MORPH_CLOSE, cv.getStructuringElement(cv.MORPH_ELLIPSE, (9, 9)))
    n, _, st, _ = cv.connectedComponentsWithStats(bw)
    out = []
    for i in range(1, n):
        bx, by, bw_, bh, area = (int(v) for v in st[i])
        if area < 20 or bw_ > 400 or bh > 400:
            continue
        m = (x >= bx) & (x < bx + bw_) & (y >= by) & (y < by + bh)
        out.append({"box": [bx, by, bx + bw_, by + bh], "score": int(m.sum()), "label": "event_blob (fallback)"})
    out.sort(key=lambda d: -d["score"])
    return out


def detect(sl, t, win=0.033, k=5):
    net = _dnn()
    img, ft = sl.frame(t) if net is not None else (None, None)
    if net is not None and img is not None:
        with _LOCK:
            b, s, _ = net.detect(img)
        z = sl.width / img.shape[1]
        dets = [{"box": [int(v * z) for v in bb], "score": round(float(sc), 3), "label": "drone (dnn)"} for bb, sc in zip(b, s)]
        dets.sort(key=lambda d: -d["score"])
        return {"t": round(t, 4), "frame_t": round(ft, 4), "detections": dets[:k], "n_candidates": len(dets), "source": SOURCE["detect"]}
    why = "no RGB frame at t" if net is not None else SOURCE["detect"]
    out = _blobs(sl, t, win)
    return {"t": round(t, 4), "detections": out[:k], "n_candidates": len(out), "source": f"FALLBACK event blobs ({why})"}


def track(sl, box, t0, t1, step=0.01):
    kf = cv.KalmanFilter(4, 2)
    kf.transitionMatrix = np.array([[1, 0, step, 0], [0, 1, 0, step], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
    kf.measurementMatrix = np.eye(2, 4, dtype=np.float32)
    kf.processNoiseCov = np.eye(4, dtype=np.float32) * 5.0
    kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 4.0
    kf.errorCovPost = np.eye(4, dtype=np.float32) * 100.0
    w, h = box[2] - box[0], box[3] - box[1]
    kf.statePost = np.array([[box[0] + w / 2], [box[1] + h / 2], [0], [0]], np.float32)
    path, misses, t = [], 0, t0
    while t < t1 - 1e-9:
        pr = kf.predict()
        cx, cy = float(pr[0, 0]), float(pr[1, 0])
        sx, sy = w * 0.75 + 4, h * 0.75 + 4
        b = [int(max(0, cx - sx)), int(max(0, cy - sy)), int(min(sl.width, cx + sx)), int(min(sl.height, cy + sy))]
        x, y, _ = sl.events(t, t + step, b)
        if len(x) >= 5:
            pw_, ph_ = b[2] - b[0], b[3] - b[1]
            patch = np.bincount((y - b[1]).astype(np.int64) * pw_ + (x - b[0]), minlength=pw_ * ph_).reshape(ph_, pw_)
            m = cv.moments(patch.astype(np.float32))
            if m["m00"] > 0:
                kf.correct(np.array([[b[0] + m["m10"] / m["m00"]], [b[1] + m["m01"] / m["m00"]]], np.float32))
            else:
                misses += 1
        else:
            misses += 1
        s = kf.statePost
        path.append([round(float(s[0, 0]), 1), round(float(s[1, 0]), 1)])
        t += step
    s = kf.statePost
    cx, cy, vx, vy = (float(s[i, 0]) for i in range(4))
    steps = max(1, len(path))
    disp = math.hypot(path[-1][0] - path[0][0], path[-1][1] - path[0][1]) if path else 0.0
    return {"box": [round(cx - w / 2), round(cy - h / 2), round(cx + w / 2), round(cy + h / 2)],
            "velocity_px_s": [round(vx, 1), round(vy, 1)], "displacement_px": round(disp, 1),
            "miss_rate": round(misses / steps, 3), "lost": misses / steps > 0.6, "steps": steps,
            "path_tail": path[-5:], "method": "cv.KalmanFilter constant-velocity on event centroids (cv.moments)"}

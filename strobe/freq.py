import cv2 as cv
import numpy as np

FS = 10000
BAND = (150.0, 1000.0)
CLEAR_SNR = 15.0
MIN_EVENTS = 200
FLICKER_HZ = 100.0
NOTCH_HZ = 6.0
LOCAL_HZ = 100.0


def _window(ev, t0_us, t1_us):
    t = ev["t"]
    i0, i1 = np.searchsorted(t, [t0_us, t1_us])
    return {k: v[i0:i1] for k, v in ev.items()}


def _in_box(ev, box):
    x1, y1, x2, y2 = (int(round(v)) for v in box[:4])
    m = (ev["x"] >= x1) & (ev["x"] < x2) & (ev["y"] >= y1) & (ev["y"] < y2)
    return {k: v[m] for k, v in ev.items()}, (x1, y1, x2, y2)


def _rel_us(t, t0_us):
    return (t - np.int64(t0_us)).astype(np.int32)


def bin_counts(t, t0_us, t1_us, fs=FS):
    nb = max(int(round((t1_us - t0_us) * fs / 1e6)), 4)
    rel = _rel_us(t, t0_us).astype(np.float32).reshape(-1, 1)
    if len(rel) == 0:
        return np.zeros(nb, np.float32)
    return cv.calcHist([rel], [0], None, [nb], [0, float(t1_us - t0_us)]).ravel()


def spectrum(counts, fs=FS, pad=4):
    nb = len(counts)
    s = counts.astype(np.float32).reshape(1, -1)
    s = cv.subtract(s, float(cv.mean(s)[0]))
    s = cv.multiply(s, cv.createHanningWindow((nb, 3), cv.CV_32F)[1:2])
    n = cv.getOptimalDFTSize(pad * nb)
    s = cv.copyMakeBorder(s, 0, 0, 0, n - nb, cv.BORDER_CONSTANT, value=0)
    re, im = cv.split(cv.dft(s, flags=cv.DFT_COMPLEX_OUTPUT))
    p = cv.magnitude(re, im).ravel()[: n // 2 + 1] ** 2
    return np.arange(n // 2 + 1) * fs / n, p


def local_floor(power, half_bins):
    pad = np.pad(power, half_bins, mode="reflect")
    return np.median(np.lib.stride_tricks.sliding_window_view(pad, 2 * half_bins + 1), axis=1)


def peak(freqs, power, band=BAND, notch=False, pad=4):
    m = (freqs >= band[0]) & (freqs <= band[1])
    if notch:
        m &= np.abs(freqs - np.round(freqs / FLICKER_HZ) * FLICKER_HZ) > NOTCH_HZ
    if not m.any() or power[m].max() <= 0:
        return 0.0, 0.0
    df = freqs[1] - freqs[0]
    half = min(max(int(round(LOCAL_HZ / df)), 12 * pad), (len(power) - 1) // 2)
    idx = np.flatnonzero(m)
    a0, a1 = max(idx[0] - half, 0), min(idx[-1] + half + 1, len(power))
    seg = power[a0:a1].astype(np.float64)
    hs = max(half // pad, 2)
    coarse = local_floor(seg[::pad], min(hs, (len(seg[::pad]) - 1) // 2))
    floor = np.maximum(np.interp(np.arange(len(seg)), np.arange(0, len(seg), pad), coarse), 1e-12)
    white = (seg / floor).astype(np.float32)
    _, _, _, loc = cv.minMaxLoc(white[idx - a0].reshape(1, -1))
    k = idx[loc[0]]
    f = freqs[k]
    if 0 < k < len(power) - 1 and power[k] >= power[k - 1] and power[k] >= power[k + 1]:
        a, b, c = np.log(power[k - 1 : k + 2] + 1e-12)
        d = a - 2 * b + c
        if d < 0:
            f = f + float(np.clip(0.5 * (a - c) / d, -0.5, 0.5)) * df
    return float(np.clip(f, band[0], band[1])), float(white[k - a0])


def activity_mask(ev, box):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if len(ev["x"]) == 0 or w < 2 or h < 2:
        return np.zeros((max(h, 1), max(w, 1)), np.uint8), 0
    xy = np.stack([ev["x"] - x1, ev["y"] - y1], 1).astype(np.float32).reshape(-1, 1, 2)
    img = cv.calcHist([xy], [0, 1], None, [w, h], [0, w, 0, h]).T
    img = cv.GaussianBlur(img, (0, 0), 1.5)
    img8 = cv.normalize(img, None, 0, 255, cv.NORM_MINMAX, cv.CV_8U)
    _, bw = cv.threshold(img8, 0, 255, cv.THRESH_BINARY | cv.THRESH_OTSU)
    n, lab, stats, _ = cv.connectedComponentsWithStats(bw, connectivity=8)
    if n <= 1:
        return bw, 0
    keep = 1 + int(np.argmax(stats[1:, cv.CC_STAT_AREA]))
    return np.where(lab == keep, 255, 0).astype(np.uint8), int(stats[keep, cv.CC_STAT_AREA])


def box_spectrum(events, box, t0_us, t1_us, fs=FS, band=BAND, use_mask=True, signal="signed", notch=False):
    ev, b = _in_box(_window(events, t0_us, t1_us), box)
    n_box = len(ev["t"])
    if use_mask:
        mask, area = activity_mask(ev, b)
        if area > 0:
            keep = mask[ev["y"] - b[1], ev["x"] - b[0]] > 0
            ev = {k: v[keep] for k, v in ev.items()}
    if signal == "signed":
        on = ev["p"] > 0
        sig = cv.subtract(bin_counts(ev["t"][on], t0_us, t1_us, fs), bin_counts(ev["t"][~on], t0_us, t1_us, fs))
    else:
        sig = bin_counts(ev["t"], t0_us, t1_us, fs)
    freqs, power = spectrum(sig.ravel(), fs)
    f, snr = peak(freqs, power, band, notch)
    return {"freqs": freqs, "power": power, "peak_hz": f, "snr": snr, "n_events": len(ev["t"]), "n_box": n_box,
            "clear": bool(snr >= CLEAR_SNR and len(ev["t"]) >= MIN_EVENTS)}


def frequency_map(events, t0_us, t1_us, roi, fs=FS, band=BAND, min_events=20, max_pixels=20000):
    ev, (x1, y1, x2, y2) = _in_box(_window(events, t0_us, t1_us), roi)
    w, h = x2 - x1, y2 - y1
    fmap = np.zeros((h, w), np.float32)
    smap = np.zeros((h, w), np.float32)
    nb = max(int(round((t1_us - t0_us) * fs / 1e6)), 4)
    if len(ev["t"]) == 0:
        return fmap, smap
    pix = (ev["y"] - y1) * w + (ev["x"] - x1)
    tb = np.minimum(_rel_us(ev["t"], t0_us).astype(np.int64) * nb // max(t1_us - t0_us, 1), nb - 1)
    npix = np.bincount(pix, minlength=w * h)
    act = np.flatnonzero(npix >= min_events)
    if len(act) > max_pixels:
        act = np.sort(act[np.argsort(npix[act])[::-1][:max_pixels]])
    if len(act) == 0:
        return fmap, smap
    row = np.full(w * h, -1, np.int64)
    row[act] = np.arange(len(act))
    sel = row[pix] >= 0
    ts = np.bincount(row[pix[sel]] * nb + tb[sel], minlength=len(act) * nb).reshape(len(act), nb).astype(np.float32)
    ts = cv.subtract(ts, cv.repeat(cv.reduce(ts, 1, cv.REDUCE_AVG), 1, nb))
    ts = cv.multiply(ts, cv.repeat(cv.createHanningWindow((nb, 3), cv.CV_32F)[1:2], len(act), 1))
    n = cv.getOptimalDFTSize(2 * nb)
    ts = cv.copyMakeBorder(ts, 0, 0, 0, n - nb, cv.BORDER_CONSTANT, value=0)
    re, im = cv.split(cv.dft(ts, flags=cv.DFT_ROWS | cv.DFT_COMPLEX_OUTPUT))
    p = cv.magnitude(re, im)[:, : n // 2 + 1] ** 2
    freqs = np.arange(n // 2 + 1) * fs / n
    m = (freqs >= band[0]) & (freqs <= band[1])
    pb = p[:, m]
    k = np.argmax(pb, 1)
    fmap.ravel()[act] = freqs[m][k]
    smap.ravel()[act] = pb[np.arange(len(act)), k] / np.maximum(np.median(pb, 1), 1e-12)
    return fmap, smap

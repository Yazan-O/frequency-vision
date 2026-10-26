import numpy as np

from strobe.freq import box_spectrum, frequency_map, peak


def synthetic_hum(f_hz=317.0, t0_us=7_000_000_000, dur_us=200_000, seed=0):
    rng = np.random.default_rng(seed)
    n = 60_000
    t = rng.uniform(0, dur_us, n)
    keep = rng.uniform(0, 1, n) < 0.5 * (1 + 0.8 * np.cos(2 * np.pi * f_hz * t / 1e6))
    t = t[keep]
    x = rng.integers(110, 130, len(t))
    y = rng.integers(110, 130, len(t))
    tb = rng.uniform(0, dur_us, 3000)
    xb = rng.integers(100, 160, 3000)
    yb = rng.integers(100, 160, 3000)
    t = np.concatenate([t, tb]).astype(np.int64) + t0_us
    o = np.argsort(t, kind="stable")
    return {"x": np.concatenate([x, xb]).astype(np.int32)[o], "y": np.concatenate([y, yb]).astype(np.int32)[o],
            "t": t[o], "p": np.ones(len(t), np.int8)}


def test_synthetic_planted_317hz_box_spectrum():
    ev = synthetic_hum()
    t0 = 7_000_000_000
    r = box_spectrum(ev, (100, 100, 160, 160), t0, t0 + 200_000)
    assert abs(r["peak_hz"] - 317.0) < 2.0
    assert r["clear"]


def test_synthetic_no_hum_has_no_clear_peak():
    ev = synthetic_hum()
    rng = np.random.default_rng(1)
    ev["t"] = np.sort(rng.integers(7_000_000_000, 7_000_200_000, len(ev["t"])).astype(np.int64))
    t0 = 7_000_000_000
    assert not box_spectrum(ev, (100, 100, 160, 160), t0, t0 + 200_000)["clear"]


def test_synthetic_planted_317hz_frequency_map():
    ev = synthetic_hum()
    t0 = 7_000_000_000
    fmap, smap = frequency_map(ev, t0, t0 + 200_000, (100, 100, 160, 160))
    hot = fmap[10:30, 10:30]
    assert abs(np.median(hot[hot > 0]) - 317.0) < 5.0


def test_peak_stays_in_band_on_falling_spectrum():
    freqs = np.arange(0, 5001, 2.5)
    power = 1e6 / (1.0 + freqs) ** 2
    f, snr = peak(freqs, power, (150.0, 1000.0))
    assert 150.0 <= f <= 1000.0
    assert snr < 3.0

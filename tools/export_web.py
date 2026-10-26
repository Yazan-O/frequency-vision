import argparse
import json
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strobe import freq
from strobe.agent import vision
from strobe.agent.data import Slice

FMAX = 1200.0
CLOUD_MS = 40
SCENE_MAX = 150000
PROVENANCE = "FRED (real event + RGB recording, Apache-2.0)"


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def evdict(sl, s):
    return {"x": sl.x[s].astype(np.int32), "y": sl.y[s].astype(np.int32), "t": sl.t[s].astype(np.int64), "p": sl.p[s].astype(np.int8)}


def spec(sl, ev, box, t, win_s=0.1):
    r = freq.box_spectrum(ev, box, sl.us(t - win_s), sl.us(t))
    f, p = r["freqs"], r["power"]
    m = (f >= freq.BAND[0]) & (f <= freq.BAND[1])
    med = float(np.median(p[m])) or 1.0
    k = f <= FMAX
    return {"peak_hz": round(r["peak_hz"], 1), "snr": round(r["snr"], 2), "n_events": int(r["n_events"]), "clear": r["clear"],
            "df": round(float(f[1] - f[0]), 3), "power": np.round((p[k] / med).astype(np.float64), 3).tolist()}


def gt_boxes(sl, t):
    out = []
    for b in sl.gt_at(t, 0.017):
        b = [round(v, 1) for v in b]
        if all(iou(b, o) < 0.9 for o in out):
            out.append(b)
    return out


def pack(x, y, t, p):
    return np.stack([x, y, t, p], 1).astype(np.uint16).tobytes()


def hum(sl, ev):
    rows = []
    seen = set()
    for g in sl.meta["gt"]:
        t = round(g["t"], 3)
        if t in seen or t - 0.1 < sl.t_lo or t > sl.t_hi:
            continue
        seen.add(t)
        r = freq.box_spectrum(ev, g["box"], sl.us(t - 0.1), sl.us(t))
        rows.append((r["peak_hz"], r["clear"]))
    pk = np.array([r[0] for r in rows if r[1]])
    if not len(pk):
        return {"n_windows": len(rows), "n_clear": 0, "median_hz": None}
    return {"n_windows": len(rows), "n_clear": int(len(pk)), "median_hz": round(float(np.median(pk)), 1),
            "p25_hz": round(float(np.percentile(pk, 25)), 1), "p75_hz": round(float(np.percentile(pk, 75)), 1), "window_ms": 100}


def export_clip(sl, cid, t0, t1, static, private, title):
    out = static / cid
    out.mkdir(parents=True, exist_ok=True)
    ev = evdict(sl, slice(0, len(sl.t)))
    frames, specs = [], {}
    for i, (ft, fn) in enumerate(zip(sl.frame_t, sl.frame_files)):
        if not t0 <= ft < t1:
            continue
        img = cv.imread(str(sl.folder / "rgb" / fn))
        img = cv.resize(img, (640, 360), interpolation=cv.INTER_AREA)
        name = f"f{len(frames):03d}.jpg"
        cv.imwrite(str(out / name), img, [cv.IMWRITE_JPEG_QUALITY, 72])
        boxes = [{"box": b, "kind": "drone", "label": "drone (FRED box)"} for b in gt_boxes(sl, ft)]
        for d in vision.detect(sl, ft)["detections"]:
            b = [float(v) for v in d["box"]]
            if all(iou(b, o["box"]) == 0 for o in boxes):
                boxes.append({"box": b, "kind": "other", "label": "moving thing (event blob)"})
        for j, b in enumerate(boxes):
            specs[f"{len(frames)}_{j}"] = spec(sl, ev, b["box"], ft)
        frames.append({"t": round(float(ft), 6), "src": f"data/{cid}/{name}", "boxes": boxes})
    if not frames:
        raise SystemExit(f"{cid}: no RGB frames in [{t0}, {t1})")
    th = frames[len(frames) // 2]["t"]
    s = sl.window(th - CLOUD_MS / 1000, th)
    x, y, t, p = sl.x[s], sl.y[s], (sl.t[s] - sl.us(th - CLOUD_MS / 1000)), sl.p[s]
    rng = np.random.default_rng(0)
    keep = np.sort(rng.choice(len(x), SCENE_MAX, replace=False)) if len(x) > SCENE_MAX else np.arange(len(x))
    (out / "scene.bin").write_bytes(pack(x[keep], y[keep], t[keep], p[keep]))
    hero_box = next((b["box"] for b in frames[len(frames) // 2]["boxes"] if b["kind"] == "drone"), None)
    crop = None
    if hero_box:
        pad = 12
        c = [max(0, int(hero_box[0]) - pad), max(0, int(hero_box[1]) - pad), min(sl.width, int(hero_box[2]) + pad), min(sl.height, int(hero_box[3]) + pad)]
        m = (x >= c[0]) & (x < c[2]) & (y >= c[1]) & (y < c[3])
        (out / "crop.bin").write_bytes(pack(x[m], y[m], t[m], p[m]))
        crop = {"box": c, "n_events": int(m.sum()), "src": f"data/{cid}/crop.bin"}
    s1 = sl.window(t0 - 0.5, t1)
    np.savez_compressed(private / f"{cid}.npz", x=sl.x[s1].astype(np.uint16), y=sl.y[s1].astype(np.uint16),
                        p=sl.p[s1].astype(np.uint8), t=sl.t[s1].astype(np.int64), origin_s=np.float64(sl.origin))
    (private / f"{cid}_spec.json").write_text(json.dumps({"window_ms": 100, "fmax": FMAX, "spectra": specs}))
    return {"id": cid, "title": title, "seq": sl.meta["seq"], "drone": bool(sl.meta["scenario"]["drone"]),
            "classes": sorted({g["cls"] for g in sl.meta["gt"]}), "provenance": PROVENANCE, "source": sl.meta["source"],
            "width": sl.width, "height": sl.height, "t0": t0, "t1": t1, "frames": frames,
            "cloud": {"t_end": th, "ms": CLOUD_MS, "scene": {"src": f"data/{cid}/scene.bin", "n_events": int(len(keep)), "n_total": int(len(x))}, "crop": crop},
            "hum": hum(sl, ev) if sl.meta["scenario"]["drone"] else None}


def phase(row):
    if row["kind"] != "step":
        return row["kind"]
    tool = row["tool"]
    if tool in ("detect_frame", "box_spectrum", "event_map", "frequency_map", "track", "request_window"):
        return "perception"
    if tool == "ask_human":
        return "approval"
    return "action"


def export_traces(paths, results):
    scores = {}
    for r in results:
        d = json.loads(Path(r).read_text())
        for planner, eps in d.get("episodes", {}).items():
            for e in eps:
                scores[(planner, e.get("id") or e.get("scenario"))] = {k: e.get(k) for k in ("success", "true_alerts", "false_alerts", "steps", "wall_s")}
    eps = []
    for p in paths:
        rows = [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
        if not rows:
            continue
        start = next((r for r in rows if r["kind"] == "start"), {})
        planner = start.get("planner") or Path(p).stem.split("_")[0]
        for r in rows:
            r["phase"] = phase(r)
        eps.append({"file": Path(p).name, "episode": rows[0]["episode"], "planner": planner, "model": start.get("model"),
                    "score": scores.get((Path(p).stem.split("_")[0], rows[0]["episode"])), "rows": rows})
    return eps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slices", default=str(ROOT / "data" / "fred_slices"))
    ap.add_argument("--clip", action="append", required=True, help="id:t0:t1:title")
    ap.add_argument("--traces", nargs="*", default=[])
    ap.add_argument("--agent-results", nargs="*", default=[])
    ap.add_argument("--false-alarms", default=None)
    ap.add_argument("--static", default=str(ROOT / "app" / "static" / "data"))
    ap.add_argument("--private", default=str(ROOT / "app" / "data"))
    a = ap.parse_args()
    static, private = Path(a.static), Path(a.private)
    static.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    clips = []
    for c in a.clip:
        cid, t0, t1, title = c.split(":", 3)
        clips.append(export_clip(Slice(Path(a.slices) / cid), cid, float(t0), float(t1), static, private, title))
        print(cid, "frames", len(clips[-1]["frames"]), "hum", clips[-1]["hum"], flush=True)
    (static / "clips.json").write_text(json.dumps({"clips": clips, "spectrum_source": vision.SOURCE["spectrum"]}))
    (static / "traces.json").write_text(json.dumps({"episodes": export_traces(a.traces, a.agent_results)}, default=str))
    if a.false_alarms:
        (private / "false_alarms.json").write_text(Path(a.false_alarms).read_text())
    size = sum(f.stat().st_size for f in static.rglob("*") if f.is_file())
    psize = sum(f.stat().st_size for f in private.rglob("*") if f.is_file())
    print(f"static {size / 1e6:.1f} MB, server-side {psize / 1e6:.1f} MB")
    if size > 40e6:
        raise SystemExit("static assets over 40 MB")


if __name__ == "__main__":
    main()

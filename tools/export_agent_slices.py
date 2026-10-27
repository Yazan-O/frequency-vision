import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def export(src, dst, clip, before_s, after_s):
    z = np.load(src)
    m = json.loads(str(z["meta"]))
    origin = m["t0_us"] / 1e6
    t0 = round(max(origin + before_s, clip["frames"][0]["t"] + 0.2), 3)
    lo, hi = round(t0 - before_s, 6), round(t0 + after_s, 6)
    t = z["ev_t"].astype(np.int64)
    i0, i1 = np.searchsorted(t, int(round((lo - origin) * 1e6))), np.searchsorted(t, int(round((hi - origin) * 1e6)))
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "rgb").mkdir(exist_ok=True)
    np.savez_compressed(dst / "events.npz", x=z["ev_x"][i0:i1], y=z["ev_y"][i0:i1], p=z["ev_p"][i0:i1], t=z["ev_t"][i0:i1])
    jpg, off = z["frame_jpg"], z["frame_jpg_offsets"]
    frames = []
    for k, ft in enumerate(z["frame_t"]):
        ts = origin + int(ft) / 1e6
        if lo - 0.1 <= ts <= hi:
            name = f"f{k:03d}.jpg"
            (dst / "rgb" / name).write_bytes(jpg[off[k]:off[k + 1]].tobytes())
            frames.append({"t": round(ts, 6), "file": name})
    gt = [{"t": round(origin + int(gt_t) / 1e6, 6), "box": [round(float(v), 2) for v in b], "id": int(i), "cls": str(c)}
          for gt_t, b, i, c in zip(z["gt_t"], z["gt_box"], z["gt_id"], z["gt_model"]) if lo - 0.1 <= origin + int(gt_t) / 1e6 <= hi]
    seq = str(m["seq"])
    meta = {"scenario": {"id": clip["id"], "kind": "clear", "seq": seq, "t0": t0, "t1": round(hi, 3), "drone": True, "entry": None},
            "seq": seq, "origin_s": origin, "t_lo": lo, "t_hi": hi, "n_events": int(i1 - i0), "width": m["sensor"][0], "height": m["sensor"][1],
            "frame_px": m["frame_size"], "events_roi": m["events_roi"], "clip": clip["id"], "source": m["source"], "frames": frames, "gt": gt,
            "trimmed": f"events and frames cut to {lo:.3f}-{hi:.3f} s from build/demo_clips/{Path(src).name} for the live agent run; events only inside events_roi"}
    (dst / "meta.json").write_text(json.dumps(meta))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default=str(ROOT.parent / "build" / "demo_clips"))
    ap.add_argument("--out", default=str(ROOT / "app" / "data" / "agent"))
    ap.add_argument("--before", type=float, default=1.0)
    ap.add_argument("--after", type=float, default=0.6)
    a = ap.parse_args()
    clips = json.loads((ROOT / "app" / "static" / "data" / "clips.json").read_text())["clips"]
    for c in clips:
        if c.get("role") != "demo":
            continue
        src = Path(a.demo) / f"{c['id']}.npz"
        meta = export(src, Path(a.out) / c["id"], c, a.before, a.after)
        print(c["id"], meta["seq"], meta["scenario"]["t0"], meta["n_events"], len(meta["frames"]), len(meta["gt"]))


if __name__ == "__main__":
    main()

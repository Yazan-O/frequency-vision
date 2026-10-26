import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

PAD = 1.0


def rgb_times(d):
    fs = sorted((d / "RGB").glob("*.jpg"))
    st = []
    for f in fs:
        m = re.search(r"_(\d+)_(\d+)_(\d+\.\d+)\.jpg$", f.name)
        st.append(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))
    o = np.argsort(st)
    st = np.array(st)[o]
    return [fs[i] for i in o], st - st[0] + 1 / 30.0


def gt_rows(d):
    rows = []
    for line in (d / "coordinates.txt").read_text().splitlines():
        if not line.strip():
            continue
        t, rest = line.split(":", 1)
        p = [x.strip() for x in rest.split(",")]
        rows.append({"t": float(t), "box": [float(v) for v in p[:4]], "id": int(float(p[4])), "cls": p[5]})
    return rows


def main(seq_root, ecf_dir, shift_dir, scen_file, out_root):
    sys.path.insert(0, ecf_dir)
    import ecf_read
    seq_root, out_root = Path(seq_root), Path(out_root)
    scen = json.loads(Path(scen_file).read_text())["scenarios"]
    by_seq = {}
    for s in scen:
        by_seq.setdefault(s["seq"], []).append(s)
    for sid, ss in by_seq.items():
        d = seq_root / sid
        ev = ecf_read.read_events(d / "Event/events.hdf5")
        tus = ev["t"].astype(np.int64)
        shift = float(np.load(Path(shift_dir) / f"{sid}.npz")["shift_ms"]) / 1000.0
        files, ft = rgb_times(d)
        ft = ft + shift
        gt = gt_rows(d)
        for s in ss:
            a, b = s["t0"] - PAD, s["t1"] + 0.5
            o = out_root / s["id"]
            if (o / "DONE").exists():
                continue
            (o / "rgb").mkdir(parents=True, exist_ok=True)
            org = int(round(a * 1e6))
            i0, i1 = np.searchsorted(tus, org), np.searchsorted(tus, int(round(b * 1e6)))
            e = ev[i0:i1]
            np.savez_compressed(o / "events.npz", x=e["x"].astype(np.uint16), y=e["y"].astype(np.uint16),
                                p=(e["p"] > 0).astype(np.uint8), t=(tus[i0:i1] - org).astype(np.uint32),
                                origin_us=np.int64(org))
            frames = []
            for f, t in zip(files, ft):
                if a <= t <= b:
                    shutil.copy2(f, o / "rgb" / f.name)
                    frames.append({"t": round(float(t), 6), "file": f.name})
            g = [r for r in gt if a - 1.0 <= r["t"] <= b + 1.0]
            meta = {"scenario": s, "seq": sid, "origin_s": org / 1e6, "t_lo": a, "t_hi": b, "n_events": int(i1 - i0),
                    "rgb_shift_s": shift, "frames": frames, "gt": g, "width": 1280, "height": 720,
                    "source": "FRED test split, Apache-2.0, huggingface.co/datasets/GabrieleMagrini/FRED"}
            (o / "meta.json").write_text(json.dumps(meta))
            (o / "DONE").write_text("ok")
            print(s["id"], "events", i1 - i0, "frames", len(frames), "gt", len(g), flush=True)
        del ev, tus


if __name__ == "__main__":
    main(*sys.argv[1:6])

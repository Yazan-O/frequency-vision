import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fred_zip import zip_frame_labels

W, H = 960, 540


def do_seq(a):
    zip_path, out, split, step = a
    sid = Path(zip_path).stem
    done = Path(out, "done", f"{sid}.json")
    if done.exists():
        return json.loads(done.read_text())
    z, frames, ts, lab, ev_ok = zip_frame_labels(zip_path)
    idir = Path(out, "images", split)
    ldir = Path(out, "labels", split)
    n = npos = nbox = 0
    sizes = []
    for i in range(0, len(frames), step):
        im = cv2.imdecode(np.frombuffer(z.read(frames[i]), np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            continue
        h0, w0 = im.shape[:2]
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
        name = f"{sid}_{i:06d}"
        cv2.imwrite(str(idir / f"{name}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 92])
        rows = []
        for x1, y1, x2, y2, _, _ in lab[i]:
            x1, x2 = max(0.0, min(x1, x2)), min(float(w0), max(x1, x2))
            y1, y2 = max(0.0, min(y1, y2)), min(float(h0), max(y1, y2))
            if x2 - x1 < 1 or y2 - y1 < 1:
                continue
            rows.append(f"0 {(x1 + x2) / 2 / w0:.6f} {(y1 + y2) / 2 / h0:.6f} {(x2 - x1) / w0:.6f} {(y2 - y1) / h0:.6f}")
            sizes.append([round(x2 - x1, 1), round(y2 - y1, 1)])
        (ldir / f"{name}.txt").write_text("\n".join(rows))
        n += 1
        npos += bool(rows)
        nbox += len(rows)
    r = {"seq": sid, "split": split, "n_frames_total": len(frames), "ev_names_match": ev_ok, "n_img": n, "n_pos": npos, "n_box": nbox, "sizes": sizes}
    tmp = done.with_suffix(".tmp")
    tmp.write_text(json.dumps(r))
    tmp.replace(done)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--step", type=int, default=4)
    ap.add_argument("--val_every", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    zips = sorted(Path(a.zips).glob("*.zip"), key=lambda p: int(p.stem))
    jobs = []
    for k, s in enumerate(zips):
        if not s.with_suffix(".done").exists():
            continue
        split = "val" if k % a.val_every == a.val_every - 1 else "train"
        jobs.append((str(s), a.out, split, a.step))
    for d in ("images/train", "images/val", "labels/train", "labels/val", "done"):
        Path(a.out, d).mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(do_seq, jobs))
    summ = {s: {k: sum(r[k] for r in res if r["split"] == s) for k in ("n_img", "n_pos", "n_box")} for s in ("train", "val")}
    summ["n_seq"] = len(res)
    summ["ev_names_mismatch"] = [r["seq"] for r in res if not r["ev_names_match"]]
    summ["val_seqs"] = [r["seq"] for r in res if r["split"] == "val"]
    summ["train_seqs"] = [r["seq"] for r in res if r["split"] == "train"]
    Path(a.out, "summary.json").write_text(json.dumps(summ, indent=1))
    Path(a.out, "data.yaml").write_text(f"path: {a.out}\ntrain: images/train\nval: images/val\nnames:\n  0: drone\n")
    Path(a.out, "DONE").write_text("ok")
    print(json.dumps({k: v for k, v in summ.items() if not k.endswith("seqs")}))


if __name__ == "__main__":
    main()

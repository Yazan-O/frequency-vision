import argparse
import json
import platform
import sys
import time
from pathlib import Path

import cv2 as cv
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strobe.detect import Detector


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d = Detector(a.onnx, threads=a.threads)
    r = np.load(a.ref)
    errs = []
    for b, ref in zip(r["blobs"], r["refs"]):
        d.net.setInput(b[None])
        y = d.net.forward()
        errs.append({"max_abs": float(np.abs(y[0] - ref).max()), "max_abs_box": float(np.abs(y[0, :4] - ref[:4]).max()), "max_abs_score": float(np.abs(y[0, 4:] - ref[4:]).max()), "shape": list(y.shape)})
    res = {"cv_version": cv.__version__, "engine": "ENGINE_NEW", "machine": platform.machine(), "processor": platform.processor(), "threads": cv.getNumThreads(), "n_ref": len(errs), "max_abs_all": max(e["max_abs"] for e in errs), "max_abs_score_all": max(e["max_abs_score"] for e in errs), "per_input": errs}
    if a.images:
        ims = [cv.imread(p) for p in a.images]
        for im in ims[:3]:
            d.detect(im)
        t_fwd, t_det = [], []
        for k in range(a.reps):
            im = ims[k % len(ims)]
            t0 = time.perf_counter()
            d.forward(im)
            t1 = time.perf_counter()
            d.detect(im)
            t2 = time.perf_counter()
            t_fwd.append((t1 - t0) * 1e3)
            t_det.append((t2 - t1) * 1e3)
        res["latency_ms"] = {"input": list(ims[0].shape), "reps": a.reps, "forward_median": float(np.median(t_fwd)), "detect_median": float(np.median(t_det)), "detect_p90": float(np.percentile(t_det, 90))}
        res["detections_first_image"] = [[*map(float, b), float(s)] for b, s in zip(*d.detect(ims[0])[:2])]
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "per_input"}, indent=1))


if __name__ == "__main__":
    main()

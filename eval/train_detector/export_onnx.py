import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO


def blob(im, w, h):
    p = cv2.dnn.Image2BlobParams()
    p.scalefactor = (1 / 255.0,) * 4
    p.size = (w, h)
    p.swapRB = True
    p.paddingmode = cv2.dnn.DNN_PMODE_LETTERBOX
    p.borderValue = (114, 114, 114, 0)
    return cv2.dnn.blobFromImageWithParams(im, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", nargs="+", required=True)
    ap.add_argument("--w", type=int, default=960)
    ap.add_argument("--h", type=int, default=544)
    a = ap.parse_args()
    m = YOLO(a.weights)
    f = m.export(format="onnx", imgsz=[a.h, a.w], opset=17, simplify=True, dynamic=False, batch=1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(f, a.out)
    net = m.model.float().eval()
    blobs, refs = [], []
    with torch.no_grad():
        for fr in a.frames:
            b = blob(cv2.imread(fr), a.w, a.h)
            y = net(torch.from_numpy(b))
            refs.append((y[0] if isinstance(y, (list, tuple)) else y).numpy())
            blobs.append(b)
    np.savez_compressed(Path(a.out).with_suffix(".ref.npz"), blobs=np.concatenate(blobs), refs=np.concatenate(refs), frames=np.array(a.frames))
    print(a.out, np.concatenate(refs).shape)


if __name__ == "__main__":
    main()

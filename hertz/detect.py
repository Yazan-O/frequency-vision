from pathlib import Path

import cv2 as cv
import numpy as np


class Detector:
    def __init__(self, onnx_path, size=(960, 544), conf=0.25, nms=0.5, engine=cv.dnn.ENGINE_NEW, threads=0):
        if threads:
            cv.setNumThreads(threads)
        self.net = cv.dnn.readNetFromONNX(np.fromfile(str(Path(onnx_path)), np.uint8), engine)
        self.size = tuple(size)
        self.conf = conf
        self.nms = nms
        p = cv.dnn.Image2BlobParams()
        p.scalefactor = (1 / 255.0,) * 4
        p.size = self.size
        p.swapRB = True
        p.paddingmode = cv.dnn.DNN_PMODE_LETTERBOX
        p.borderValue = (114, 114, 114, 0)
        self.params = p

    def forward(self, frame_bgr):
        self.net.setInput(cv.dnn.blobFromImageWithParams(frame_bgr, self.params))
        return self.net.forward()

    def detect(self, frame_bgr, conf=None):
        conf = self.conf if conf is None else conf
        out = self.forward(frame_bgr)[0].T
        cls_scores = out[:, 4:]
        classes = cls_scores.argmax(1)
        scores = cls_scores[np.arange(len(out)), classes]
        keep = scores >= conf
        if not keep.any():
            return np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, np.int32)
        xywh = out[keep, :4].copy()
        xywh[:, :2] -= xywh[:, 2:] / 2
        scores, classes = scores[keep], classes[keep]
        idx = np.asarray(cv.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), conf, self.nms), np.int32).reshape(-1)
        h, w = frame_bgr.shape[:2]
        sx, sy = self.size[0] / w, self.size[1] / h
        s = min(sx, sy)
        px, py = (self.size[0] - w * s) / 2, (self.size[1] - h * s) / 2
        b = xywh[idx]
        x1 = np.clip((b[:, 0] - px) / s, 0, w)
        y1 = np.clip((b[:, 1] - py) / s, 0, h)
        x2 = np.clip((b[:, 0] + b[:, 2] - px) / s, 0, w)
        y2 = np.clip((b[:, 1] + b[:, 3] - py) / s, 0, h)
        return np.stack([x1, y1, x2, y2], 1).astype(np.float32), scores[idx].astype(np.float32), classes[idx].astype(np.int32)

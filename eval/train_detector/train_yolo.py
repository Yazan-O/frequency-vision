import argparse
from pathlib import Path

import torch
from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", default="yolov8s_960")
    ap.add_argument("--model", default="yolov8s.pt")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--mem_frac", type=float, default=0.0)
    a = ap.parse_args()
    if a.mem_frac > 0:
        torch.cuda.set_per_process_memory_fraction(a.mem_frac, 0)
    last = Path(a.project, a.name, "weights", "last.pt")
    if last.exists() and not Path(a.project, a.name, "weights", "DONE").exists():
        YOLO(str(last)).train(resume=True)
    else:
        YOLO(a.model).train(data=a.data, imgsz=a.imgsz, epochs=a.epochs, batch=a.batch, workers=a.workers,
                            project=a.project, name=a.name, exist_ok=True, single_cls=True, cos_lr=True,
                            close_mosaic=2, patience=100, seed=0, deterministic=False, plots=True, save_period=1)
    Path(a.project, a.name, "weights", "DONE").write_text("ok")


if __name__ == "__main__":
    main()

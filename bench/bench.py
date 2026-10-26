import argparse
import json
import os
import platform
import socket
import time
import urllib.request

import cv2 as cv
import numpy as np

SAMPLE = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/fruits.jpg"


def imds(path):
    try:
        tok = urllib.request.urlopen(urllib.request.Request("http://169.254.169.254/latest/api/token", method="PUT", headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}), timeout=1).read().decode()
        return urllib.request.urlopen(urllib.request.Request(f"http://169.254.169.254/latest/meta-data/{path}", headers={"X-aws-ec2-metadata-token": tok}), timeout=1).read().decode()
    except OSError:
        return None


def load(src, size):
    buf = urllib.request.urlopen(src, timeout=30).read() if src.startswith("http") else open(src, "rb").read()
    img = cv.imdecode(np.frombuffer(buf, np.uint8), cv.IMREAD_COLOR)
    return cv.resize(img, size, interpolation=cv.INTER_CUBIC) if size else img


def workload(img, onnx, onnx_size):
    g = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    f = np.float32(cv.resize(g, (512, 512)))
    b = cv.threshold(g, 0, 255, cv.THRESH_BINARY | cv.THRESH_OTSU)[1]
    ops = {
        "resize": lambda: cv.resize(img, (640, 640), interpolation=cv.INTER_LINEAR),
        "cvtColor": lambda: cv.cvtColor(img, cv.COLOR_BGR2GRAY),
        "GaussianBlur": lambda: cv.GaussianBlur(img, (5, 5), 0),
        "dft": lambda: cv.dft(f, flags=cv.DFT_COMPLEX_OUTPUT),
        "connectedComponentsWithStats": lambda: cv.connectedComponentsWithStats(b, connectivity=8)[2],
    }
    if onnx:
        net = cv.dnn.readNetFromONNX(np.fromfile(onnx, np.uint8))
        blob = cv.dnn.blobFromImage(img, 1 / 255.0, (onnx_size, onnx_size), swapRB=True)

        def fwd():
            net.setInput(blob)
            return net.forward()
        ops["dnn_forward"] = fwd
    return ops


def measure(fn, iters, warmup):
    for _ in range(warmup):
        out = fn()
    lat = []
    c0, w0 = os.times(), time.perf_counter()
    for _ in range(iters):
        t = time.perf_counter()
        fn()
        lat.append(time.perf_counter() - t)
    c1, w1 = os.times(), time.perf_counter()
    cpu = (c1.user - c0.user + c1.system - c0.system) / (w1 - w0) / os.cpu_count() * 100
    lat = np.array(lat) * 1e3
    return out, {"p50_ms": float(np.percentile(lat, 50)), "p95_ms": float(np.percentile(lat, 95)), "mean_ms": float(lat.mean()),
                 "throughput_per_s": float(iters / (w1 - w0)), "cpu_pct": float(cpu), "iters": iters}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--image", default=SAMPLE)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--onnx")
    ap.add_argument("--onnx-size", type=int, default=640)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--price-usd-hour", type=float)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    size = tuple(int(x) for x in a.size.split("x")) if a.size else None
    img = load(a.image, size)
    ops = workload(img, a.onnx, a.onnx_size)
    rows, outs = [], {}
    for threads in sorted({1, os.cpu_count()}):
        cv.setNumThreads(threads)
        for name, fn in ops.items():
            out, r = measure(fn, a.iters if name != "dnn_forward" else max(20, a.iters // 10), a.warmup)
            if a.price_usd_hour:
                r["usd_per_million"] = a.price_usd_hour / 3600 / r["throughput_per_s"] * 1e6
            rows.append({"op": name, "threads": threads, **r})
            outs[name] = np.asarray(out)
    info = cv.getBuildInformation()
    meta = {"label": a.label, "host": socket.gethostname(), "instance_type": imds("instance-type"), "instance_id": imds("instance-id"),
            "ami": imds("ami-id"), "machine": platform.machine(), "cpu_count": os.cpu_count(), "python": platform.python_version(),
            "opencv": cv.__version__, "cv2_file": cv.__file__, "numpy": np.__version__,
            "build": [line.strip() for line in info.splitlines() if any(k in line for k in ("HAL", "KleidiCV", "Baseline", "Dispatched", "Parallel framework"))],
            "image": a.image, "size": a.size, "onnx": a.onnx, "price_usd_hour": a.price_usd_hour, "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump({"meta": meta, "rows": rows}, open(a.out + ".json", "w"), indent=1)
    np.savez_compressed(a.out + ".npz", **outs)
    for r in rows:
        print(f"{r['op']:30s} t={r['threads']:<3d} p50={r['p50_ms']:.3f} p95={r['p95_ms']:.3f} thr={r['throughput_per_s']:.1f}/s cpu={r['cpu_pct']:.0f}%")


if __name__ == "__main__":
    main()

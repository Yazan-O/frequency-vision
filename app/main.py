import platform
import time

import cv2
from fastapi import FastAPI

app = FastAPI()
STARTED = time.time()


@app.get("/health")
def health():
    return {"ok": True, "uptime_s": round(time.time() - STARTED, 1)}


@app.get("/version")
def version():
    info = cv2.getBuildInformation()
    hal = [line.strip() for line in info.splitlines() if any(k in line for k in ("HAL", "KleidiCV", "NEON", "Baseline", "Dispatched"))]
    return {
        "opencv": cv2.__version__,
        "cv2_file": cv2.__file__,
        "cool": cv2.__file__.startswith("/opt/cool"),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hal": hal,
    }

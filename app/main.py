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
    hal = [line.strip() for line in info.splitlines() if "HAL" in line or "KleidiCV" in line or "NEON" in line]
    return {
        "opencv": cv2.__version__,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hal": hal,
    }

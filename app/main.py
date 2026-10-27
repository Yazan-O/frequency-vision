import platform
import time

import cv2
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import STATIC, router, summary

app = FastAPI(title="Frequency Vision")
STARTED = time.time()
app.include_router(router)
app.mount("/data", StaticFiles(directory=STATIC), name="data")
app.mount("/static", StaticFiles(directory=STATIC.parent), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC.parent / "deck.html", headers={"Cache-Control": "no-cache"})


@app.get("/about", include_in_schema=False)
def about():
    return summary()


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

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

try:
    from hertz import freq
except Exception:
    freq = None

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = HERE / "data"
STATIC = HERE / "static" / "data"
STATE = Path(os.environ.get("HERTZ_STATE") or os.environ.get("STROBE_STATE", str(Path.home() / ".strobe")))
FMAX = 1200.0
MAX_APPROVALS = 20000
LIMITS = {"approve": (10, 60.0), "detect": (30, 60.0)}
DET_PATH = os.environ.get("HERTZ_DETECTOR_ONNX") or os.environ.get("STROBE_DETECTOR_ONNX", str(ROOT.parent / "build" / "models" / "strobe_drone_960x544.onnx"))
DET_CONF = 0.125
router = APIRouter(prefix="/api")
_hits = defaultdict(deque)
_hits_lock = threading.Lock()
_det = {"net": None, "error": None, "lock": threading.Lock()}


def limit(req: Request, kind):
    n, span = LIMITS[kind]
    fwd = req.headers.get("x-forwarded-for")
    ip = fwd.split(",")[-1].strip() if fwd else (req.client.host if req.client else "?")
    now = time.monotonic()
    with _hits_lock:
        q = _hits[(kind, ip)]
        while q and now - q[0] > span:
            q.popleft()
        if len(q) >= n:
            raise HTTPException(429, f"rate limit: {n} {kind} requests per {int(span)} s per IP")
        q.append(now)
        if len(_hits) > 10000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > span]:
                del _hits[k]


@lru_cache(maxsize=1)
def clips():
    return {c["id"]: c for c in json.loads((STATIC / "clips.json").read_text())["clips"]}


@lru_cache(maxsize=4)
def events(cid):
    z = np.load(DATA / f"{cid}.npz")
    return {"x": z["x"].astype(np.int32), "y": z["y"].astype(np.int32), "t": z["t"].astype(np.int64), "p": z["p"].astype(np.int8)}, float(z["origin_s"])


@lru_cache(maxsize=4)
def precomputed(cid):
    return json.loads((DATA / f"{cid}_spec.json").read_text())


class SpecReq(BaseModel):
    clip: str
    box: list[float] = Field(min_length=4, max_length=4)
    t: float
    window_ms: float = 100.0
    frame: int | None = None
    box_index: int | None = None


@router.post("/spectrum")
def spectrum(r: SpecReq):
    c = clips().get(r.clip)
    if c is None:
        raise HTTPException(404, "unknown clip")
    win = min(max(r.window_ms, 10.0), 500.0)
    x0, y0, x1, y1 = r.box
    if not (0 <= x0 < x1 <= c["width"] and 0 <= y0 < y1 <= c["height"]):
        raise HTTPException(422, "box outside the frame")
    if freq is not None and (DATA / f"{r.clip}.npz").exists():
        ev, origin = events(r.clip)
        t1 = int(round((r.t - origin) * 1e6))
        t0 = t1 - int(round(win * 1000))
        tic = time.perf_counter()
        out = freq.box_spectrum(ev, r.box, t0, t1)
        ms = (time.perf_counter() - tic) * 1000
        f, p = out["freqs"], out["power"]
        m = (f >= freq.BAND[0]) & (f <= freq.BAND[1])
        med = float(np.median(p[m])) or 1.0
        k = f <= FMAX
        return {"mode": "live", "source": "computed now: events in the box binned every 0.1 ms with OpenCV calcHist, then OpenCV dft", "compute_ms": round(ms, 2),
                "window_ms": win, "peak_hz": round(out["peak_hz"], 1), "snr": round(out["snr"], 2), "n_events": int(out["n_events"]),
                "clear": out["clear"], "df": round(float(f[1] - f[0]), 3), "power": np.round((p[k] / med).astype(np.float64), 3).tolist(),
                "band": list(freq.BAND), "clear_snr": freq.CLEAR_SNR}
    s = precomputed(r.clip)["spectra"].get(f"{r.frame}_{r.box_index}")
    if s is None:
        raise HTTPException(503, "live spectrum unavailable and no precomputed spectrum for this box")
    return {"mode": "precomputed", "source": "precomputed by the exporter with the same spectrum code", "window_ms": 100.0,
            "band": [150.0, 1000.0], "clear_snr": 15.0, **s}


class Approval(BaseModel):
    episode: str = Field(max_length=64)
    step: int = Field(ge=0, le=1000)
    decision: str


@router.post("/approve")
def approve(a: Approval, req: Request):
    limit(req, "approve")
    if a.decision not in ("approve", "reject") or not re.fullmatch(r"[\w.-]+", a.episode):
        raise HTTPException(422, "decision must be approve or reject")
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / "approvals.jsonl"
    rows = f.read_text().splitlines() if f.exists() else []
    if len(rows) >= MAX_APPROVALS:
        raise HTTPException(429, "approval log full")
    rec = {"episode": a.episode, "step": a.step, "decision": a.decision, "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "effect": "recorded only; no external action"}
    with f.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return {**rec, **tally(a.episode, a.step, rows + [json.dumps(rec)])}


def tally(episode, step, rows):
    n = {"approve": 0, "reject": 0}
    for line in rows:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("episode") == episode and d.get("step") == step:
            n[d["decision"]] += 1
    return {"approvals": n["approve"], "rejections": n["reject"]}


def approval_log():
    f = STATE / "approvals.jsonl"
    n = len(f.read_text().splitlines()) if f.exists() else 0
    return {"kind": "demo log", "rows": n, "rate_limit": f"{LIMITS['approve'][0]} per minute per IP",
            "note": "clicks from the public demo page; no sign-in, so anyone can add a row; nothing external is triggered"}


def detector():
    if _det["net"] is None and _det["error"] is None:
        try:
            from hertz.detect import Detector
            _det["net"] = Detector(DET_PATH, conf=DET_CONF)
        except Exception as e:
            _det["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return _det["net"]


class DetReq(BaseModel):
    clip: str
    frame: int = Field(ge=0, le=10000)


@router.post("/detect")
def detect(r: DetReq, req: Request):
    c = clips().get(r.clip)
    if c is None or r.frame >= len(c["frames"]):
        raise HTTPException(404, "unknown clip or frame")
    limit(req, "detect")
    import cv2 as cv
    net = detector()
    if net is None:
        raise HTTPException(503, f"detector not loaded: {_det['error']}")
    img = cv.imread(str(STATIC.parent / c["frames"][r.frame]["src"]))
    if img is None:
        raise HTTPException(404, "frame image missing")
    with _det["lock"]:
        tic = time.perf_counter()
        b, s, _ = net.detect(img)
        ms = (time.perf_counter() - tic) * 1000
    k = c["width"] / img.shape[1]
    build = next((ln.strip() for ln in cv.getBuildInformation().splitlines() if "General configuration for OpenCV" in ln), "")
    return {"clip": r.clip, "frame": r.frame, "frame_t": c["frames"][r.frame]["t"], "frame_px": [img.shape[1], img.shape[0]],
            "boxes": [[round(float(v) * k, 1) for v in bb] for bb in b], "scores": [round(float(v), 3) for v in s],
            "box_space": f"{c['width']}x{c['height']} event-sensor pixels", "score_min": DET_CONF, "latency_ms": round(ms, 1),
            "model": Path(DET_PATH).name, "call": "cv.dnn.readNetFromONNX + blobFromImageWithParams + forward + NMSBoxes",
            "opencv": cv.__version__, "cv2_build": build, "cv2_file": cv.__file__, "cool": cv.__file__.startswith("/opt/cool")}


def e2e():
    out = []
    for f in sorted((ROOT / "bench" / "results").glob("e2e-*.json")):
        d = json.loads(f.read_text())
        if "summary" in d:
            out.append({"label": d["meta"]["label"], "opencv": d["meta"]["opencv"], "file": f"bench/results/{f.name}",
                        **{k: d["summary"].get(k) for k in ("windows", "timed_windows", "p50_ms", "p95_ms", "windows_per_s", "cpu_pct_of_all_vcpus", "usd_per_1000_windows")}})
    return out or {"status": "pending"}


def bench():
    pick = {}
    for f in sorted((ROOT / "bench" / "results").glob("pip-*.json")):
        d = json.loads(f.read_text())
        meta = d["meta"]
        key = "graviton4" if "graviton4" in meta["label"] else "x86" if meta["machine"] == "x86_64" else None
        if key is None:
            continue
        top = max(r["threads"] for r in d["rows"])
        pick[key] = {"label": meta["label"], "instance": meta["instance_type"], "machine": meta["machine"], "opencv": meta["opencv"],
                     "threads": top, "file": f"bench/results/{f.name}", "time_utc": meta.get("time_utc"),
                     "rows": {r["op"]: {"p50_ms": r["p50_ms"], "usd_per_million": r.get("usd_per_million")} for r in d["rows"] if r["threads"] == top}}
    if len(pick) < 2:
        return {"status": "pending"}
    ops = [o for o in pick["graviton4"]["rows"] if o in pick["x86"]["rows"]]
    return {"status": "ok", "graviton4": {k: v for k, v in pick["graviton4"].items() if k != "rows"},
            "x86": {k: v for k, v in pick["x86"].items() if k != "rows"},
            "ops": [{"op": o, "graviton4_ms": round(pick["graviton4"]["rows"][o]["p50_ms"], 3), "x86_ms": round(pick["x86"]["rows"][o]["p50_ms"], 3),
                     "x86_over_graviton4": round(pick["x86"]["rows"][o]["p50_ms"] / pick["graviton4"]["rows"][o]["p50_ms"], 2),
                     "graviton4_usd_per_m": pick["graviton4"]["rows"][o]["usd_per_million"], "x86_usd_per_m": pick["x86"]["rows"][o]["usd_per_million"]}
                    for o in ops]}


@router.get("/results")
def results():
    fa = DATA / "false_alarms.json"
    return {"false_alarms": json.loads(fa.read_text()) if fa.exists() else {"status": "pending"}, "bench": bench(),
            "end_to_end": e2e(), "live_spectrum": freq is not None, "live_detector": Path(DET_PATH).exists()}


@router.get("/summary")
def summary():
    cs = list(clips().values())
    demo = [c for c in cs if c.get("role") in ("demo", "hard")] or cs
    hero = max((c for c in demo if c.get("hum") and c["hum"].get("median_hz") and c["cloud"].get("crop")), key=lambda c: c["cloud"]["crop"]["n_events"], default=cs[0])
    tr = json.loads((STATIC / "traces.json").read_text())["episodes"]
    return {
        "name": "Frequency Vision",
        "claim": "Frequency Vision confirms drones by their propeller hum: an RGB detector proposes boxes, the event-camera stream inside each box is checked for a blade-pass frequency peak (150-1000 Hz) that a 30 fps camera cannot see, and an agent chooses the next look, alert, or human approval. OpenCV 5 on AWS Graviton.",
        "measured_hum": {"clip": hero["id"], "fred_sequence": hero["seq"], "drone": hero["classes"], **(hero["hum"] or {}),
                         "method": "median peak frequency over the 100 ms event windows inside the FRED drone box that pass the hum test",
                         "source": "app/static/data/clips.json, written by tools/export_web.py"},
        "hum_test": {"band_hz": list(freq.BAND) if freq else [150.0, 1000.0], "clear_score": getattr(freq, "CLEAR_SNR", None),
                     "ambiguous_score": getattr(freq, "AMBIGUOUS_SNR", None), "local_hz": getattr(freq, "LOCAL_HZ", None),
                     "fs_hz": getattr(freq, "FS", None), "min_events": getattr(freq, "MIN_EVENTS", None), "module": "hertz/freq.py, the event-window frequency check",
                     "score": "peak power divided by the median power within local_hz of the peak; thresholds chosen on FRED training sequences"},
        "math": ["30 fps sampling sees at most 15 Hz; a blade-pass f aliases to |f - k*30|", "event counts binned at 1/fs_hz s see up to fs_hz/2",
                 "X(f) = sum_t x(t) w(t) exp(-i 2 pi f t), x = ON minus OFF events in the box, w = Hanning, computed with cv.dft",
                 "frequency resolution 1/T for a window of T s: the agent asks for a longer window T when a spectrum is ambiguous",
                 "OpenCV 5 calls: calcHist, dft, connectedComponentsWithStats, dnn"],
        "clips": [{"id": c["id"], "title": c["title"], "fred_sequence": c["seq"], "drone": c["drone"], "role": c.get("role"), "provenance": c["provenance"], "source": c["source"],
                   "hum": {k: v for k, v in (c.get("hum") or {}).items() if k != "by_class"} or None} for c in cs],
        "clip_roles": {"demo": "clip picker: FRED test segments where every 100 ms window of the drone box passes the hum test", "hard": "clip picker, marked hard case: a drone with no clean peak",
                       "agent": "used by the recorded agent episode only", None: "no-drone reference"},
        "agent_episodes": [{"episode": e["episode"], "planner": e["planner"], "model": e["model"], "score_vs_fred": e["score"], "trace_file": e["file"]} for e in tr],
        "approval": "POST /api/approve records approve or reject in a demo log on the server only; nothing external is triggered. The approval inside recorded runs came from an automatic operator stand-in marked SIMULATED.",
        "approval_log": approval_log(),
        "results": results(),
        "slides": [
            {"title": "the hum", "shows": "30 fps RGB video with a zoom on the drone (blades are a blur) next to the brighter-minus-darker event count in the drone box, one bar per 0.5 ms over 40 ms, with orange ticks one blade pass apart; the big number is the clip's median blade-pass frequency; 'run detector live' sends the shown frame to POST /api/detect, which runs the OpenCV 5 dnn drone detector on the server and draws its boxes"},
            {"title": "events in 3D", "shows": "orbitable x-y-time point cloud of 40 ms of events on the drone; black = pixel got brighter (ON), grey = darker (OFF); orange lines one blade pass apart; 'vs empty' stacks a same-size patch from the no-drone clip"},
            {"title": "spectrum", "shows": "live spectrum of a drone box next to a no-drone box for a chosen event window; shaded band 150-1000 Hz is the propeller band; power relative to the band median, log scale"},
            {"title": "the math", "shows": "aliasing of the blade-pass rate at 30 fps (f_alias = |f - k*30|, Nyquist 15 Hz vs 5 kHz for 0.1 ms event bins); x(t) * Hanning window -> cv.dft; score = peak / median within +-100 Hz; resolution 1/T vs window length"},
            {"title": "agent", "shows": "recorded agent steps as cards in a look -> listen -> decide loop; listen cards are orange when the hum test passes, dashed when ambiguous; the human approval card records Approve or Reject on the server only; nothing plays until Play is pressed"},
            {"title": "results", "shows": "measured median blade-pass frequency per drone clip with the share of 100 ms windows passing; false alarms of the RGB detector alone vs with the hum check over the FRED test split; OpenCV 5 p50 benchmark Graviton4 vs x86"}],
        "routes": {"page": "/", "summary": "/api/summary", "spectrum": "POST /api/spectrum {clip, box[x0,y0,x1,y1], t, window_ms}",
                   "approve": "POST /api/approve {episode, step, decision}", "detect": "POST /api/detect {clip, frame}", "results": "/api/results", "health": "/health", "version": "/version"},
    }

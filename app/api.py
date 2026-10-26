import json
import os
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
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
router = APIRouter(prefix="/api")


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
        return {"mode": "live", "source": "hertz.freq.box_spectrum (OpenCV 5 calcHist + dft)", "compute_ms": round(ms, 2),
                "window_ms": win, "peak_hz": round(out["peak_hz"], 1), "snr": round(out["snr"], 2), "n_events": int(out["n_events"]),
                "clear": out["clear"], "df": round(float(f[1] - f[0]), 3), "power": np.round((p[k] / med).astype(np.float64), 3).tolist(),
                "band": list(freq.BAND), "clear_snr": freq.CLEAR_SNR}
    s = precomputed(r.clip)["spectra"].get(f"{r.frame}_{r.box_index}")
    if s is None:
        raise HTTPException(503, "live spectrum unavailable and no precomputed spectrum for this box")
    return {"mode": "precomputed", "source": "precomputed by tools/export_web.py with hertz.freq", "window_ms": 100.0,
            "band": [150.0, 1000.0], "clear_snr": 15.0, **s}


class Approval(BaseModel):
    episode: str = Field(max_length=64)
    step: int = Field(ge=0, le=1000)
    decision: str


@router.post("/approve")
def approve(a: Approval):
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
                     "graviton4_usd_per_m": pick["graviton4"]["rows"][o]["usd_per_million"], "x86_usd_per_m": pick["x86"]["rows"][o]["usd_per_million"]}
                    for o in ops]}


@router.get("/results")
def results():
    fa = DATA / "false_alarms.json"
    return {"false_alarms": json.loads(fa.read_text()) if fa.exists() else {"status": "pending"}, "bench": bench(),
            "live_spectrum": freq is not None}


@router.get("/summary")
def summary():
    cs = list(clips().values())
    hero = next((c for c in cs if c.get("hum") and c["hum"].get("median_hz")), cs[0])
    tr = json.loads((STATIC / "traces.json").read_text())["episodes"]
    return {
        "name": "Hertz",
        "claim": "Hertz confirms drones by their propeller hum: an RGB detector proposes boxes, the event-camera stream inside each box is checked for a blade-pass frequency peak (150-1000 Hz) that a 30 fps camera cannot see, and an agent chooses the next look, alert, or human approval. OpenCV 5 on AWS Graviton.",
        "measured_hum": {"clip": hero["id"], "fred_sequence": hero["seq"], "drone": hero["classes"], **(hero["hum"] or {}),
                         "method": "median hertz.freq.box_spectrum peak over the FRED-box event windows that pass the hum test",
                         "source": "app/static/data/clips.json, written by tools/export_web.py"},
        "hum_test": {"band_hz": list(freq.BAND) if freq else [150.0, 1000.0], "clear_score": getattr(freq, "CLEAR_SNR", None),
                     "ambiguous_score": getattr(freq, "AMBIGUOUS_SNR", None), "local_hz": getattr(freq, "LOCAL_HZ", None),
                     "fs_hz": getattr(freq, "FS", None), "min_events": getattr(freq, "MIN_EVENTS", None), "module": "hertz.freq",
                     "score": "peak power / median power within +-local_hz of the peak; thresholds chosen by lane L1 on FRED training data"},
        "math": ["30 fps sampling sees at most 15 Hz; a blade-pass f aliases to |f - k*30|", "event counts binned at 1/fs_hz s see up to fs_hz/2",
                 "X(f) = sum_t x(t) w(t) exp(-i 2 pi f t), x = ON minus OFF events in the box, w = Hanning, computed with cv.dft",
                 "frequency resolution 1/T for a window of T s: the agent's request_window lengthens T when a spectrum is ambiguous",
                 "OpenCV 5 calls: calcHist, dft, connectedComponentsWithStats, dnn"],
        "clips": [{"id": c["id"], "title": c["title"], "fred_sequence": c["seq"], "drone": c["drone"], "provenance": c["provenance"], "source": c["source"],
                   "hum": {k: v for k, v in (c.get("hum") or {}).items() if k != "by_class"} or None} for c in cs],
        "agent_episodes": [{"episode": e["episode"], "planner": e["planner"], "model": e["model"], "score_vs_fred": e["score"], "trace_file": e["file"]} for e in tr],
        "approval": "POST /api/approve records approve or reject on the server only; nothing external is triggered. The approval inside recorded runs came from an automatic operator stand-in marked SIMULATED.",
        "results": results(),
        "slides": ["the hum: 30 fps RGB vs event rhythm and the measured Hz", "x-y-time event cloud on the drone", "live event spectrum, drone box vs no-drone box",
                   "agent steps with human approval", "false alarms and Graviton4 vs x86 OpenCV 5 benchmark"],
        "routes": {"page": "/", "summary": "/api/summary", "spectrum": "POST /api/spectrum {clip, box[x0,y0,x1,y1], t, window_ms}",
                   "approve": "POST /api/approve {episode, step, decision}", "results": "/api/results", "health": "/health", "version": "/version"},
    }

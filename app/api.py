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
STATE = Path(os.environ.get("HERTZ_STATE", str(Path.home() / ".hertz")))
FMAX = 1200.0
MAX_APPROVALS = 20000
LIMITS = {"approve": (10, 60.0), "detect": (30, 60.0), "agent": (4, 60.0), "cool": (10, 60.0)}
IMDS = "http://169.254.169.254/latest"
COOL_RUNS = 20
COOL_BUDGET_S = 0.8
AGENT_DATA = DATA / "agent"
LIVE_WAIT_S = 60
LIVE_MAX = 3
LIVE_MAX_S = LIVE_WAIT_S + 30
BEDROCK_DAY_CAP = 3
LIVE_PLANNER = os.environ.get("HERTZ_LIVE_PLANNER", "bedrock")
_live = {"lock": threading.Lock(), "runs": {}, "client": None}
DET_PATH = os.environ.get("HERTZ_DETECTOR_ONNX", str(ROOT.parent / "build" / "models" / "strobe_drone_960x544.onnx"))
DET_CONF = 0.125
HERO = "clear_mini2_seq202"
router = APIRouter(prefix="/api")
_hits = defaultdict(deque)
_hits_lock = threading.Lock()
_det = {"net": None, "error": None, "lock": threading.Lock()}


def limit(req: Request, kind):
    n, span = LIMITS[kind]
    ip = _client_ip(req)
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
            "band": [150.0, 1000.0], "clear_snr": 98.0, **s}


class Approval(BaseModel):
    episode: str = Field(max_length=64)
    step: int = Field(ge=0, le=1000)
    decision: str


@router.post("/approve")
def approve(a: Approval, req: Request):
    limit(req, "approve")
    if a.decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve or reject")
    if not re.fullmatch(r"[\w.-]+", a.episode):
        raise HTTPException(422, "invalid episode id")
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


@lru_cache(maxsize=1)
def agent_store():
    from hertz.agent.data import Store
    return Store(AGENT_DATA)


def live_scenarios():
    return {p.parent.name: json.loads(p.read_text())["scenario"] for p in sorted(AGENT_DATA.glob("*/meta.json"))}


def _client_ip(req):
    fwd = req.headers.get("x-forwarded-for")
    return fwd.split(",")[-1].strip() if fwd else (req.client.host if req.client else "?")


def _bedrock_slot():
    if LIVE_PLANNER != "bedrock":
        return None, f"live planner set to {LIVE_PLANNER}"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = STATE / "bedrock_runs.json"
    with _live["lock"]:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            d = {}
        n = d.get("n", 0) if d.get("day") == day else 0
        if n >= BEDROCK_DAY_CAP:
            return None, f"daily cap of {BEDROCK_DAY_CAP} Bedrock runs reached for {day} UTC"
        STATE.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"day": day, "n": n + 1}))
    try:
        if _live["client"] is None:
            import boto3
            from botocore.config import Config
            _live["client"] = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                                           config=Config(read_timeout=30, connect_timeout=5, retries={"max_attempts": 2}))
        return _live["client"], None
    except Exception as e:
        return None, f"Bedrock client unavailable: {type(e).__name__}: {str(e)[:150]}"


def _live_run(rid, scn):
    from hertz.agent.guard import Budget
    from hertz.agent.runner import run_episode
    run = _live["runs"][rid]

    def approver(seq, box, severity, question, now):
        run["ask"] = {"box": box, "severity": severity, "question": question}
        run["status"] = "waiting"
        answered = run["event"].wait(LIVE_WAIT_S)
        run["ask"], run["status"] = None, "running"
        d = run["decision"] if answered else None
        if d is None:
            return {"approved": False, "timeout": True, "responder": f"no answer within {LIVE_WAIT_S} s"}
        return {"approved": d == "approve", "responder": f"live page visitor: {d}"}

    try:
        client, why = _bedrock_slot()
        run["planner_note"] = why
        name = "bedrock" if client is not None else "rule"
        budget = Budget(max_compute_ms=30000.0 + LIVE_WAIT_S * 1000.0)
        run["summary"], _ = run_episode(scn, agent_store(), name, run["path"], budget=budget, timeout_s=LIVE_WAIT_S + 10.0,
                                        approver=approver, client=client)
    except Exception as e:
        run["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    run["status"] = "done"


class LiveReq(BaseModel):
    clip: str = Field(default="clear_mini2_seq202", max_length=40)


@router.post("/agent/live")
def agent_live(r: LiveReq, req: Request):
    scn = live_scenarios().get(r.clip)
    if scn is None:
        raise HTTPException(404, "no live agent data for this clip")
    ip = _client_ip(req)
    with _live["lock"]:
        now = time.time()
        for k in [k for k, v in _live["runs"].items() if v["status"] == "done" and now - v["started"] > 600]:
            del _live["runs"][k]
        active = [v for v in _live["runs"].values() if v["status"] != "done"]
        mine = [v for v in active if v["ip"] == ip]
        if mine:
            raise HTTPException(429, {"busy": "you", "message": "your live run is still going", "retry_s": _left(mine[0], now)})
        if len(active) >= LIVE_MAX:
            raise HTTPException(429, {"busy": "full", "message": f"{LIVE_MAX} live runs are going", "retry_s": min(_left(v, now) for v in active)})
    limit(req, "agent")
    with _live["lock"]:
        rid = os.urandom(6).hex()
        _live["runs"][rid] = {"status": "running", "ask": None, "decision": None, "event": threading.Event(), "started": time.time(), "ip": ip,
                              "clip": r.clip, "path": STATE / "agent_live" / f"{rid}.jsonl"}
    threading.Thread(target=_live_run, args=(rid, scn), daemon=True).start()
    return {"id": rid, "clip": r.clip, "scenario": scn, "wait_s": LIVE_WAIT_S}


def _left(v, now):
    return max(5, int(v["started"] + LIVE_MAX_S - now))


def _run(rid):
    run = _live["runs"].get(rid) if re.fullmatch(r"[0-9a-f]{12}", rid) else None
    if run is None:
        raise HTTPException(404, "unknown run")
    return run


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def _gt_check(clip, rows):
    try:
        sl = agent_store().get(live_scenarios()[clip]["seq"])
    except Exception:
        return []
    out = []
    for r in rows:
        if r.get("kind") != "step" or r.get("tool") not in ("box_spectrum", "request_window", "track", "ask_human", "raise_alert"):
            continue
        box = (r.get("result") or {}).get("box") if r["tool"] == "track" else (r.get("args_checked") or r.get("args") or {}).get("box")
        t = r.get("now_after") if r.get("now_after") is not None else r.get("now_before")
        gts = [g for g in sl.meta["gt"] if abs(g["t"] - t) <= 0.05] if box and t is not None else []
        if gts:
            g = min(gts, key=lambda g: abs(g["t"] - t))
            out.append({"step": r["step"], "tool": r["tool"], "iou": round(_iou(box, g["box"]), 2), "gt_box": g["box"], "gt_t": g["t"]})
    return out


@router.get("/agent/live/{rid}")
def agent_live_get(rid: str):
    run = _run(rid)
    rows = []
    if run["path"].exists():
        for line in run["path"].read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    start = next((x for x in rows if x.get("kind") == "start"), {})
    fb = [x.get("reason") for x in rows if x.get("kind") == "fallback"]
    s = run.get("summary") or {}
    planner = {"ran": s.get("planner_final") or start.get("planner"), "first": start.get("planner"), "model": start.get("model"),
               "fallback": fb, "note": run.get("planner_note")}
    c = clips().get(run["clip"]) or {}
    hum = c.get("hum") or {}
    expected = {"median_hz": hum.get("median_hz"), "n_clear": hum.get("n_clear"), "n_windows": hum.get("n_windows"), "window_ms": hum.get("window_ms"),
                "seq": c.get("seq"), "what": "median blade-pass frequency of this clip over its 100 ms windows that pass the hum test (app/static/data/clips.json)"}
    return {"status": run["status"], "ask": run["ask"], "rows": rows, "summary": run.get("summary"), "error": run.get("error"),
            "clip": run["clip"], "planner": planner, "expected": expected, "gt": _gt_check(run["clip"], rows),
            "wait_s": LIVE_WAIT_S, "age_s": round(time.time() - run["started"], 1)}


class LiveDecision(BaseModel):
    decision: str


@router.post("/agent/live/{rid}/decide")
def agent_live_decide(rid: str, d: LiveDecision):
    run = _run(rid)
    if d.decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve or reject")
    if run["status"] != "waiting":
        raise HTTPException(409, "the run is not waiting for a decision")
    run["decision"] = d.decision
    run["event"].set()
    return {"ok": True, "decision": d.decision}


LIMITS["vision"] = (300, 60.0)


class StepVisionReq(BaseModel):
    seq: str = Field(max_length=12, pattern=r"^\d+$")
    t: float = Field(ge=0, le=100000)
    box: list[int] | None = Field(default=None, min_length=4, max_length=4)
    t0: float | None = Field(default=None, ge=0, le=100000)
    t1: float | None = Field(default=None, ge=0, le=100000)


def _step_frame(seq, t, tol=0.05):
    import cv2 as cv
    try:
        sl = agent_store().get(seq)
        img, ft = sl.frame(t)
        if img is not None and t - ft <= tol:
            if img.shape[1] != sl.width or img.shape[0] != sl.height:
                img = cv.resize(img, (sl.width, sl.height), interpolation=cv.INTER_LINEAR)
            return img, ft, "agent data slice"
    except KeyError:
        pass
    for c in clips().values():
        if str(c.get("seq")) != seq or not c.get("frames"):
            continue
        f = min(c["frames"], key=lambda f: abs(f["t"] - t))
        if abs(f["t"] - t) <= tol:
            img = cv.imread(str(STATIC.parent / f["src"]))
            if img is not None:
                return cv.resize(img, (c["width"], c["height"]), interpolation=cv.INTER_LINEAR), f["t"], "page clip frames"
    return None, None, None


@lru_cache(maxsize=512)
def _step_crop(seq, t, box):
    import base64
    import cv2 as cv
    img, ft, src = _step_frame(seq, t)
    if img is None:
        return None
    H, W = img.shape[:2]
    x0, y0, x1, y1 = box if box else (0, 0, W, H)
    if box:
        s = max(x1 - x0, y1 - y0, 24) * 0.9
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        x0, y0, x1, y1 = int(max(0, cx - s * 4 / 3)), int(max(0, cy - s)), int(min(W, cx + s * 4 / 3)), int(min(H, cy + s))
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    z = 192 / max(crop.shape[1], 1)
    crop = cv.resize(crop, (192, max(1, int(round(crop.shape[0] * z)))), interpolation=cv.INTER_AREA if z < 1 else cv.INTER_CUBIC)
    ok, buf = cv.imencode(".jpg", crop, [cv.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return None
    return {"jpeg": base64.b64encode(buf.tobytes()).decode(), "rect": [x0, y0, x1, y1], "frame_t": round(float(ft), 4), "source": src}


@lru_cache(maxsize=512)
def _step_spectrum(seq, box, t0, t1):
    from hertz.agent import vision
    if vision.L1 is None:
        return None
    try:
        sl = agent_store().get(seq)
    except KeyError:
        return None
    if t0 < sl.t_lo - 1e-6 or t1 > sl.t_hi + 1e-6 or not 0 < t1 - t0 <= 1.0:
        return None
    r = vision.L1.box_spectrum(vision._ev(sl, t0, t1), list(box), sl.us(t0), sl.us(t1))
    f, p = r["freqs"], r["power"]
    lo, hi = vision.BAND[0] - 50, vision.BAND[1] + 50
    med = float(np.median(p[(f >= vision.BAND[0]) & (f <= vision.BAND[1])])) or 1.0
    k = (f >= lo) & (f <= hi)
    n = 96
    idx = np.clip(((f[k] - lo) / (hi - lo) * n).astype(int), 0, n - 1)
    pooled = np.zeros(n)
    np.maximum.at(pooled, idx, p[k] / med)
    return {"f_lo": lo, "f_hi": hi, "power": np.round(pooled, 3).tolist(), "peak_hz": round(float(r["peak_hz"]), 1), "snr": round(float(r["snr"]), 2),
            "n_events": int(r["n_events"]), "band": list(vision.BAND), "hum_snr": vision.CLEAR_SNR, "ambiguous_snr": vision.AMB_SNR,
            "how": "recomputed from the same events with the agent's box_spectrum (OpenCV calcHist + dft); power over the band median, max-pooled to 96 bins"}


@router.post("/agent/step_vision")
def agent_step_vision(r: StepVisionReq, req: Request):
    limit(req, "vision")
    box = tuple(int(v) for v in r.box) if r.box else None
    if box and not (0 <= box[0] < box[2] <= 1280 and 0 <= box[1] < box[3] <= 720):
        raise HTTPException(422, "box outside the frame")
    spec = _step_spectrum(r.seq, box, round(r.t0, 4), round(r.t1, 4)) if box and r.t0 is not None and r.t1 is not None else None
    return {"seq": r.seq, "t": r.t, "box": box, "crop": _step_crop(r.seq, round(r.t, 4), box), "spectrum": spec}


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


def cool_vs_pip():
    R = ROOT / "bench" / "results"
    try:
        c, p = (json.loads((R / f).read_text()) for f in ("cool-graviton4-c8g.xlarge.json", "pip-graviton4-c8g.xlarge-samehost.json"))
        ec, ep, ex = (json.loads((R / f).read_text())["summary"] for f in ("e2e-cool-best-graviton4-c8g.xlarge-r3.json", "e2e-pip-best-graviton4-c8g.xlarge-r3.json",
                                                                          "e2e-pip-best-x86-c7i.xlarge-r3.json"))
        vc, vp = ({(r["threads"], r["window_ms"]): r for r in json.loads((R / f).read_text())["rows"]}
                  for f in ("ev-cool-graviton4-c8g.xlarge.json", "ev-pip-graviton4-c8g.xlarge.json"))
    except (OSError, ValueError, KeyError):
        return {"status": "pending"}
    top = max(r["threads"] for r in c["rows"])
    pc = {r["op"]: r["p50_ms"] for r in p["rows"] if r["threads"] == top}
    cc = {r["op"]: r["p50_ms"] for r in c["rows"] if r["threads"] == top}
    ops = [{"op": o, "label": lab, "cool_ms": round(cc[o], 3), "pip_ms": round(pc[o], 3), "ratio": round(pc[o] / cc[o], 2), "scope": f"single op, {top} threads"}
           for o, lab in (("GaussianBlur", "blur"), ("dft", "dft"))]
    for w in (100, 500):
        a, b = vc[(4, w)]["fmap_mean_ms"], vp[(4, w)]["fmap_mean_ms"]
        ops.append({"op": "frequency_map", "label": f"frequency map, {w} ms", "cool_ms": round(a, 2), "pip_ms": round(b, 2), "ratio": round(b / a, 2),
                    "scope": f"real FRED events, {w} ms windows, 4 threads"})
    return {"status": "ok", "instance": c["meta"]["instance_type"], "cool": c["meta"]["opencv"], "pip": p["meta"]["opencv"], "ops": ops,
            "end_to_end": {"cool_p50_ms": round(ec["p50_ms"], 1), "pip_p50_ms": round(ep["p50_ms"], 1), "x86_p50_ms": round(ex["p50_ms"], 1),
                           "pip_faster_pct": round(100 * (ec["p50_ms"] / ep["p50_ms"] - 1)), "faster_than_x86_pct": round(100 * (1 - ec["p50_ms"] / ex["p50_ms"]))},
            "files": ["bench/results/cool-graviton4-c8g.xlarge.json", "bench/results/pip-graviton4-c8g.xlarge-samehost.json",
                      "bench/results/ev-cool-graviton4-c8g.xlarge.json", "bench/results/ev-pip-graviton4-c8g.xlarge.json",
                      "bench/results/e2e-cool-best-graviton4-c8g.xlarge-r3.json", "bench/results/e2e-pip-best-graviton4-c8g.xlarge-r3.json",
                      "bench/results/e2e-pip-best-x86-c7i.xlarge-r3.json"]}


def _imds_get(path, token, timeout=0.3):
    import urllib.request
    req = urllib.request.Request(f"{IMDS}/{path}", headers={"X-aws-ec2-metadata-token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


@lru_cache(maxsize=1)
def imds():
    import urllib.request
    try:
        req = urllib.request.Request(f"{IMDS}/api/token", method="PUT", headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        with urllib.request.urlopen(req, timeout=0.3) as r:
            token = r.read().decode()
    except Exception as e:
        return {"source": "not on EC2: instance metadata unreachable", "error": type(e).__name__}
    out = {"source": "EC2 instance metadata (IMDSv2), read by this server"}
    for k, p in (("instance_type", "meta-data/instance-type"), ("instance_id", "meta-data/instance-id"), ("ami_id", "meta-data/ami-id"),
                 ("region", "meta-data/placement/region"), ("product_codes", "meta-data/product-codes")):
        try:
            out[k] = _imds_get(p, token).strip()
        except Exception:
            out[k] = None
    return out


def cpu_features():
    try:
        txt = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None
    for ln in txt.splitlines():
        k, _, v = ln.partition(":")
        if k.strip() in ("Features", "flags"):
            return v.split()
    return None


@lru_cache(maxsize=1)
def cool_window():
    c = clips()[HERO]
    ev, origin = events(HERO)
    t1 = int(round((c["frames"][len(c["frames"]) // 2]["t"] - origin) * 1e6))
    t0 = t1 - 100_000
    m = (ev["t"] >= t0) & (ev["t"] < t1)
    w, h = c["width"], c["height"]
    img = np.bincount(ev["y"][m] * w + ev["x"][m], minlength=w * h).reshape(h, w).astype(np.float32)
    return {"ev": ev, "t0": t0, "t1": t1, "w": w, "h": h, "img": img, "n_events": int(m.sum()), "seq": c["seq"]}


@router.get("/cool")
def cool(req: Request):
    limit(req, "cool")
    import cv2 as cv
    hal = [ln.strip() for ln in cv.getBuildInformation().splitlines() if any(k in ln for k in ("HAL", "KleidiCV", "carotene", "Baseline", "Dispatched"))]
    out = {"opencv": cv.__version__, "cv2_file": cv.__file__, "cool": cv.__file__.startswith("/opt/cool"),
           "kleidicv": any("KleidiCV" in ln for ln in hal), "build_hal": hal, "threads": cv.getNumThreads(),
           "cpu_features_opencv": cv.getCPUFeaturesLine() if hasattr(cv, "getCPUFeaturesLine") else None,
           "cpu_features": cpu_features(), "instance": imds()}
    if freq is None or not (DATA / f"{HERO}.npz").exists():
        out["timing"] = {"status": "unavailable: hertz.freq or event data missing"}
        return out
    win = cool_window()
    img, roi = win["img"], (0, 0, win["w"], win["h"])
    ops = {"GaussianBlur": lambda: cv.GaussianBlur(img, (5, 5), 0),
           "dft": lambda: cv.dft(img, flags=cv.DFT_COMPLEX_OUTPUT),
           "frequency_map": lambda: freq.frequency_map(win["ev"], win["t0"], win["t1"], roi)}
    times = {k: [] for k in ops}
    res = {}
    tic0 = time.perf_counter()
    for k, f in ops.items():
        start = time.perf_counter()
        for _ in range(COOL_RUNS):
            tic = time.perf_counter()
            res[k] = f()
            times[k].append(time.perf_counter() - tic)
            if tic + 2 * times[k][-1] - start > COOL_BUDGET_S / len(ops):
                break
    total = (time.perf_counter() - tic0) * 1000
    smap = res["frequency_map"][1]
    out["timing"] = {"status": "ok", "runs_max": COOL_RUNS, "budget_ms": int(COOL_BUDGET_S * 1000), "total_ms": round(total, 1),
                     "ops": [{"op": k, "runs": len(v), "p50_ms": round(float(np.median(v)) * 1000, 3), "min_ms": round(min(v) * 1000, 3)} for k, v in times.items()],
                     "input": f"real FRED events: clip {HERO} (sequence {win['seq']}), one 100 ms window, {win['n_events']:,} events; "
                              f"GaussianBlur 5x5 and dft on their {win['w']}x{win['h']} float32 count image; frequency_map over the full sensor",
                     "fmap_pixels_passing_hum_test": int((smap >= freq.CLEAR_SNR).sum()),
                     "note": "timed on this server during this request; the COOL vs pip comparison comes from the committed benchmark files, not from this call"}
    return out


@router.get("/results")
def results():
    fa = DATA / "false_alarms.json"
    return {"false_alarms": json.loads(fa.read_text()) if fa.exists() else {"status": "pending"}, "bench": bench(), "cool_vs_pip": cool_vs_pip(),
            "end_to_end": e2e(), "live_spectrum": freq is not None, "live_detector": Path(DET_PATH).exists()}


JUDGING = {
    "overall": [
        {"criterion": "Technical execution", "weight": 30, "evidence": "OpenCV 5 hum engine (calcHist, dft, connectedComponentsWithStats, dnn ENGINE_NEW, KalmanFilter) evaluated on all 47 FRED test sequences: false alarms 412.7 to 308.4 per minute (-25%) at the same recall 0.544; hum-score AUC 0.917 vs random patch, 0.758 vs busiest patch; an OpenCV 5.0.0 int64 defect found and written up for upstream",
         "where": ["results/detector/results_test.json", "results/engine/summary.json", "docs/REPORT.md section 8", "docs/UPSTREAM_ISSUE_int64.md"]},
        {"criterion": "Innovation", "weight": 20, "evidence": "the RGB detector proposes, the event camera confirms by the propeller's blade-pass frequency inside each box, and an agent picks the next measurement", "where": ["docs/REPORT.md section 13", "live page slides 1 to 3"]},
        {"criterion": "Real-world impact", "weight": 20, "evidence": "8,790 of 34,796 false detections removed while 26 of 70,794 true detections are lost; the high-precision setting reaches precision 0.815", "where": ["results/detector/results_test.json", "docs/REPORT.md sections 1 and 2"]},
        {"criterion": "User experience", "weight": 10, "evidence": "live six-slide page with a clip picker, live detector, live spectrum, 3D event cloud and a live agent run that waits for the visitor's Approve or Reject; keyboard navigation, screen-reader text, phone layout", "where": ["/", "app/static/deck.html"]},
        {"criterion": "Documentation and presentation", "weight": 10, "evidence": "README with a results table and figures redrawn from result files, technical report, architecture and agent diagrams, video", "where": ["README.md", "docs/REPORT.md", "docs/architecture.svg", "docs/agent_workflow.svg"]},
        {"criterion": "Cloud delivery, reproducibility, responsible operation", "weight": 10, "evidence": "always-on COOL endpoint on Graviton4 behind HTTPS, deployed by one script, /health and /version, rate limits, no SSH, human approval enforced in code", "where": ["deploy/aws.py", "deploy/README.md", "/health", "/version", "docs/REPORT.md sections 5 and 11"]},
    ],
    "best_use_of_cool": [
        {"criterion": "Verified COOL integration on Graviton", "weight": 30, "evidence": "the live endpoint loads cv2 from /opt/cool (OpenCV 5.1.0-dev, aarch64, KleidiCV HAL); proof file with instance type, AMI and Marketplace product code", "where": ["/version", "/api/cool", "bench/results/cool-proof-live-c8g.medium.json", "bench/results/cool-proof-c8g.xlarge.json"]},
        {"criterion": "Architecture and technical quality", "weight": 25, "evidence": "COOL serves the page, the hum engine, the detector and the agent tools on one Graviton4 host; benchmark hosts are separate", "where": ["docs/architecture.svg", "docs/REPORT.md section 6"]},
        {"criterion": "Measured value", "weight": 20, "evidence": "same Graviton4 host, COOL vs pip OpenCV 5: GaussianBlur 1.89x, dft 1.54x, connectedComponentsWithStats 1.17x faster; frequency map 1.26x faster at 100 ms of events and 1.45x at 500 ms; outputs identical", "where": ["bench/results/cool-graviton4-c8g.xlarge.json", "bench/results/pip-graviton4-c8g.xlarge-samehost.json", "bench/results/E2E.md"]},
        {"criterion": "Innovation", "weight": 15, "evidence": "COOL runs signal processing on event-camera time series: a 10 kHz dft per box and a per-pixel frequency map with dft DFT_ROWS", "where": ["hertz/freq.py"]},
        {"criterion": "Reproducibility and demonstration", "weight": 10, "evidence": "python deploy/aws.py cool deploys the endpoint; python deploy/aws.py cool-bench reruns the same-host benchmark", "where": ["deploy/README.md", "bench/"]},
    ],
    "agentic_vision": [
        {"criterion": "OpenCV 5 and agent integration", "weight": 30, "evidence": "every agent tool is an OpenCV 5 call (detect_frame, box_spectrum, request_window, frequency_map, track); in trace late_142 the detector finds nothing, the frequency map finds a 545 Hz spot and the agent confirms the drone", "where": ["hertz/agent/", "results/agent/eval_v4/traces/bedrock_late_142.jsonl"]},
        {"criterion": "Orchestration and autonomy", "weight": 25, "evidence": "with its OpenCV spectrum blinded, the Bedrock planner solves 6 of 24 scenarios and confirms 0 of 18 drones; a blinded result changes its next action at 39 of 130 vision steps; a guard checks each call against schema, clock and budgets", "where": ["results/agent/eval_v4/vision_ablation.json", "hertz/agent/guard.py"]},
        {"criterion": "Task effectiveness and evaluation", "weight": 20, "evidence": "24 FRED scenarios: Bedrock 12 of 24 with 0 false alerts, rule planner 10 (1 false alert), fixed schedule 9; on the 16 held-out scenarios 8 vs 6 vs 6", "where": ["results/agent/eval_v4/results.json", "results/agent/eval_v4/SUMMARY.json"]},
        {"criterion": "Failure handling, observability, security, human control", "weight": 15, "evidence": "critical alerts need human approval, enforced by the guard; 21 fault cases (20 injected faults plus a no-fault control) all handled with 0 unsafe alerts; every step is logged as JSON lines", "where": ["results/agent/faults/TABLE.md", "tests/", "hertz/agent/guard.py", "POST /api/agent/live"]},
        {"criterion": "User experience, documentation, demonstration", "weight": 10, "evidence": "slide 5 replays real traces and runs the Bedrock agent live on the server on the picked clip with the visitor's Approve or Reject", "where": ["live page slide 5", "docs/agent_workflow.svg"]},
    ],
    "requirements": [
        {"requirement": "OpenCV 5 for substantive analysis", "where": ["hertz/freq.py", "hertz/detect.py", "/version"]},
        {"requirement": "Meaningful AWS component", "where": ["COOL on Graviton4 c8g.medium serves this page", "Amazon Bedrock planner", "docs/architecture.svg"]},
        {"requirement": "Working web endpoint", "where": ["https://100-27-6-111.sslip.io"]},
        {"requirement": "Video of at most five minutes", "where": ["README.md, Video link"]},
        {"requirement": "Technical report", "where": ["docs/REPORT.md"]},
        {"requirement": "Code repository with pinned dependencies and build, deploy and test steps", "where": ["requirements.txt", "requirements-dev.txt", "README.md, Reproduce", "deploy/README.md"]},
        {"requirement": "Architecture diagram with OpenCV 5, AWS, COOL and agent parts", "where": ["docs/architecture.svg", "docs/agent_workflow.svg"]},
        {"requirement": "Evaluation with failure cases", "where": ["docs/REPORT.md sections 8 and 9", "results/"]},
        {"requirement": "Rights to data, models and media", "where": ["THIRD_PARTY.md", "FRED under Apache-2.0", "detector weights not distributed"]},
    ],
}


@router.get("/summary")
def summary():
    cs = list(clips().values())
    demo = [c for c in cs if c.get("role") == "demo"] or cs
    hero = clips().get(HERO) or max((c for c in demo if c.get("hum") and c["hum"].get("median_hz") and c["cloud"].get("crop")), key=lambda c: c["cloud"]["crop"]["n_events"], default=cs[0])
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
        "clip_roles": {"demo": "clip picker: FRED test segments with the drone in view and at least 96% of the 100 ms windows of its box passing the hum test",
                       "agent": "used by the recorded agent episode only", None: "no-drone reference"},
        "default_window_ms": {"value": 100, "why": "best hum-score AUC on the FRED test split against the busiest no-drone patch: 0.758 at 100 ms, 0.753 at 50 ms, 0.702 at 20 ms, 0.727 at 200 ms",
                              "source": "results/engine/summary.json, variant signed_mask_notch"},
        "agent_episodes": [{"episode": e["episode"], "planner": e["planner"], "model": e["model"], "score_vs_fred": e["score"], "trace_file": e["file"]} for e in tr],
        "approval": "POST /api/approve records approve or reject in a demo log on the server only; nothing external is triggered. The approval inside recorded runs came from an automatic operator stand-in marked SIMULATED.",
        "approval_log": approval_log(),
        "results": results(),
        "slides": [
            {"title": "the hum", "shows": "30 fps RGB video played at half speed, with a zoom on the drone (blades are a blur) next to the brighter-minus-darker event count in the drone box, one bar per 0.5 ms over 40 ms, with orange ticks one blade pass apart; the big number is the clip's median blade-pass frequency; 'run detector live' sends the shown frame to POST /api/detect, which runs the OpenCV 5 dnn drone detector on the server and draws its boxes"},
            {"title": "events in 3D", "shows": "orbitable x-y-time point cloud of 40 ms of events on the drone; black = pixel got brighter (ON), grey = darker (OFF); orange lines one blade pass apart; 'vs empty' stacks a same-size patch from the no-drone clip"},
            {"title": "spectrum", "shows": "live spectrum of a drone box next to a no-drone box for a chosen event window; shaded band 150-1000 Hz is the propeller band; power relative to the band median, log scale"},
            {"title": "the math", "shows": "aliasing of the blade-pass rate at 30 fps (f_alias = |f - k*30|, Nyquist 15 Hz vs 5 kHz for 0.1 ms event bins); x(t) * Hanning window -> cv.dft; score = peak / median within +-100 Hz; resolution 1/T vs window length"},
            {"title": "agent", "shows": "recorded agent steps as cards in call order; each card shows what OpenCV returned for that step (the camera crop around its box, a mini spectrum with the peak Hz and score, recomputed on the server by POST /api/agent/step_vision when the events are kept there, and the verdict hum, ambiguous or none) and an arrow naming the result that led to the next call, e.g. ambiguous -> request 300 ms window; listen cards are orange when the hum test passes, dashed when ambiguous; Play shows a step about every 0.9 s and stops at the approval card until Approve or Reject.",
             "default_episode": "the late drone (FRED 142) that the camera detector misses and the frequency map finds.",
             "live_run": "'Run agent live' runs the agent on the picked clip against the live tools: Claude Sonnet 4.6 on Amazon Bedrock, or the rule planner after 3 Bedrock runs a UTC day or on a Bedrock error. It waits up to 60 s for the visitor's approval before a critical alert. With no answer it ends unconfirmed and raises no alert. It reports the clip's expected Hz and the IoU with the FRED box."},
            {"title": "results", "shows": "one card per drone clip, its thumbnail framed on the drone, the measured median blade-pass frequency and the share of 100 ms windows passing; false alarms of the RGB detector alone vs with the hum check over the FRED test split; OpenCV 5 p50 benchmark Graviton4 vs x86"}],
        "judging": JUDGING,
        "routes": {"page": "/", "summary": "/api/summary", "spectrum": "POST /api/spectrum {clip, box[x0,y0,x1,y1], t, window_ms}",
                   "approve": "POST /api/approve {episode, step, decision}",
                   "agent_live": "POST /api/agent/live {clip} starts the agent (Bedrock planner, rule fallback) on the server against the live tools, one run per IP and at most 3 at once; GET /api/agent/live/{id} returns its steps; POST /api/agent/live/{id}/decide {decision} answers its approval question", "detect": "POST /api/detect {clip, frame}", "step_vision": "POST /api/agent/step_vision {seq, t, box, t0, t1}: camera crop around an agent step's box and its box spectrum recomputed with the agent's box_spectrum, for slide 5", "results": "/api/results", "cool": "GET /api/cool: cv2 path, build HAL lines, CPU features, EC2 instance metadata and a live timing of GaussianBlur, dft and frequency_map on a real event window", "health": "/health", "version": "/version"},
    }

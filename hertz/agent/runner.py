import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import datetime, timezone
from pathlib import Path

from .guard import Budget, Reject, State, check
from .planners import BedrockPlanner, FixedPlanner, PlannerError, RulePlanner
from .tools import Toolbox
from . import vision

PLANNERS = {"bedrock": BedrockPlanner, "rule": RulePlanner, "fixed": FixedPlanner}


class Trace:
    def __init__(self, path, episode):
        self.path, self.episode = Path(path), episode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = self.path.open("w", encoding="utf-8")
        self.rows = []

    def log(self, kind, **kw):
        row = {"episode": self.episode, "kind": kind, "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **kw}
        self.rows.append(row)
        self.f.write(json.dumps(row, default=str) + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def _exec(pool, toolbox, name, a, st, timeout_s):
    last = None
    for attempt in (1, 2):
        fut = pool.submit(toolbox.run, name, a, st)
        try:
            return fut.result(timeout=timeout_s), attempt, None
        except FutTimeout:
            last = f"timeout after {timeout_s}s"
        except Reject:
            raise
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:300]}"
    return {"error": last}, 2, last


def run_episode(scn, store, planner_name, trace_path, budget=None, timeout_s=8.0, model=None, approver=None, client=None):
    budget = budget or Budget()
    try:
        sl = store.get(scn["seq"])
    except (KeyError, OSError, ValueError) as e:
        tr = Trace(trace_path, scn["id"])
        tr.log("missing_data", scenario=scn, error=f"{type(e).__name__}: {e}")
        summary = {"verdict": "error_missing_data", "alerts": [], "steps": 0, "rejections": 0, "planner_final": None,
                   "planner_failures": 0, "wall_s": 0.0, "tool_ms": 0.0, "stream_now": None, "asks": 0, "bedrock_usage": None}
        tr.log("end", **summary)
        tr.close()
        return summary, tr.rows
    st = State(seq=str(scn["seq"]), t_start=float(scn["t0"]), t_end=float(scn["t1"]), width=sl.width, height=sl.height)
    tb = Toolbox(store, budget) if approver is None else Toolbox(store, budget, approver)
    tr = Trace(trace_path, scn["id"])
    kw = {}
    if planner_name == "bedrock":
        kw = {"budget": budget, "client": client}
        if model:
            kw["model"] = model
    try:
        planner = PLANNERS[planner_name](st, **kw)
        active = planner_name
        usage = getattr(planner, "usage", None)
    except Exception as e:
        tr.log("fallback", reason=f"planner init failed: {type(e).__name__}: {str(e)[:200]}", to="rule")
        planner, active, usage = RulePlanner(st), "rule", None
    tr.log("start", scenario=scn, planner=active, model=getattr(planner, "model", None), budget=budget.__dict__,
           vision_source=dict(vision.SOURCE), hot_pixels_masked=len(sl.hot), now=st.now)
    t_ep = time.perf_counter()
    results, planner_failures = [], 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        while not st.finished:
            if st.steps >= budget.max_steps or st.compute_ms >= budget.max_compute_ms or st.rejections > budget.max_rejections:
                why = "steps" if st.steps >= budget.max_steps else ("compute" if st.compute_ms >= budget.max_compute_ms else "rejections")
                st.finished = True
                tr.log("forced_finish", reason=f"{why} budget spent", verdict="drone_alerted" if st.alerts else "no_drone", now=st.now)
                break
            t = time.perf_counter()
            try:
                calls = planner.decide(results)
                results = []
            except PlannerError as e:
                results = []
                planner_failures += 1
                tr.log("planner_error", planner=active, error=e.kind, detail=e.detail, failures=planner_failures,
                       latency_ms=round((time.perf_counter() - t) * 1000, 1))
                if planner_failures >= 2 and active != "rule":
                    tr.log("fallback", reason=f"{planner_failures} planner failures ({e.kind})", to="rule", now=st.now)
                    planner, active = RulePlanner(st), "rule"
                continue
            plan_ms = round((time.perf_counter() - t) * 1000, 1)
            for c in calls:
                row = {"step": st.steps + 1, "planner": active, "now_before": round(st.now, 4), "tool": c.name, "args": c.args,
                       "why": c.why, "planner_ms": plan_ms}
                if st.finished:
                    results.append((c, {"error": "episode finished"}))
                    continue
                try:
                    a = check(c.name, c.args, st, budget)
                    t1 = time.perf_counter()
                    r, attempts, err = _exec(pool, tb, c.name, a, st, timeout_s)
                    ms = (time.perf_counter() - t1) * 1000
                    st.compute_ms += ms
                    st.steps += 1
                    tr.log("step", **row, guard="ok", args_checked=a, result=r, tool_ms=round(ms, 1), attempts=attempts,
                           tool_error=err, now_after=round(st.now, 4))
                    results.append((c, r))
                except Reject as e:
                    st.steps += 1
                    st.rejections += 1
                    tr.log("step", **row, guard=f"rejected: {e}", result=None, now_after=round(st.now, 4))
                    results.append((c, {"error": f"guard rejected: {e}"}))
    verdict = next((r["result"]["verdict"] for r in reversed(tr.rows) if r["kind"] == "step" and r["tool"] == "finish" and r["guard"] == "ok"), None)
    if verdict is None:
        verdict = "drone_alerted" if st.alerts else "no_drone"
    summary = {"verdict": verdict, "alerts": st.alerts, "steps": st.steps, "rejections": st.rejections,
               "planner_final": active, "planner_failures": planner_failures, "wall_s": round(time.perf_counter() - t_ep, 3),
               "tool_ms": round(st.compute_ms, 1), "stream_now": round(st.now, 4),
               "asks": len(st.approvals), "bedrock_usage": usage}
    tr.log("end", **summary)
    tr.close()
    return summary, tr.rows

import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from .data import Store
from .guard import Budget, Reject, State, check
from .tools import Toolbox

DATA = os.environ.get("HERTZ_DATA", str(Path(__file__).resolve().parents[2] / "data" / "fred_slices"))
TRACE = os.environ.get("HERTZ_MCP_TRACE", "")

mcp = FastMCP("hertz")
_store = Store(DATA)
_budget = Budget()
_box = {"tb": None, "st": None}


def _log(row):
    if TRACE:
        with open(TRACE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")


def _call(name, args):
    st, tb = _box["st"], _box["tb"]
    if st is None:
        return {"error": "call start_watch first"}
    t = time.perf_counter()
    try:
        a = check(name, args, st, _budget)
        r = tb.run(name, a, st)
        st.steps += 1
        st.compute_ms += (time.perf_counter() - t) * 1000
    except Reject as e:
        st.steps += 1
        st.rejections += 1
        r = {"error": f"guard rejected: {e}"}
    _log({"tool": name, "args": args, "result": r, "ms": round((time.perf_counter() - t) * 1000, 1)})
    return r


@mcp.tool()
def start_watch(seq: str, t_start: float, t_end: float) -> dict:
    sl = _store.get(seq)
    lo, hi = sl.t_lo + _budget.buffer_s, sl.t_hi
    if not (lo <= t_start < t_end <= hi):
        return {"error": f"watch must lie in [{lo:.3f}, {hi:.3f}]"}
    _box["st"] = State(seq=str(seq), t_start=t_start, t_end=t_end, width=sl.width, height=sl.height)
    _box["tb"] = Toolbox(_store, _budget)
    return {"seq": seq, "now": t_start, "t_end": t_end, "budget": _budget.__dict__}


@mcp.tool()
def detect_frame(seq: str, t: float) -> dict:
    return _call("detect_frame", {"seq": seq, "t": t})


@mcp.tool()
def box_spectrum(seq: str, box: list[float], t0: float, t1: float) -> dict:
    return _call("box_spectrum", {"seq": seq, "box": box, "t0": t0, "t1": t1})


@mcp.tool()
def request_window(seq: str, box: list[float], length_ms: float) -> dict:
    return _call("request_window", {"seq": seq, "box": box, "length_ms": length_ms})


@mcp.tool()
def frequency_map(seq: str, t0: float, t1: float) -> dict:
    return _call("frequency_map", {"seq": seq, "t0": t0, "t1": t1})


@mcp.tool()
def track(seq: str, box: list[float], t0: float, t1: float) -> dict:
    return _call("track", {"seq": seq, "box": box, "t0": t0, "t1": t1})


class Approval(BaseModel):
    approve: bool


@mcp.tool()
async def ask_human(seq: str, box: list[float], severity: str, question: str, ctx: Context) -> dict:
    if _box["tb"] is not None:
        try:
            res = await ctx.elicit(f"[{severity}] {question} box={box}", Approval)
            ok = res.action == "accept" and bool(res.data.approve)
            who = f"operator via MCP elicitation ({res.action})"
        except Exception as e:
            ok, who = False, f"no operator reachable ({type(e).__name__}); denied by default"
        _box["tb"].approver = lambda *a, **k: {"approved": ok, "responder": who}
    return _call("ask_human", {"seq": seq, "box": box, "severity": severity, "question": question})


@mcp.tool()
def raise_alert(seq: str, box: list[float], severity: str, reason: str) -> dict:
    return _call("raise_alert", {"seq": seq, "box": box, "severity": severity, "reason": reason})


@mcp.tool()
def finish(verdict: str, reason: str) -> dict:
    return _call("finish", {"verdict": verdict, "reason": reason})


if __name__ == "__main__":
    mcp.run()

import argparse
import asyncio
import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hertz.agent import vision
from hertz.agent.data import Store
from hertz.agent.faults import DownClient, ScriptedClient, TextOnlyClient, slow
from hertz.agent.guard import Budget
from hertz.agent.runner import run_episode

DATA = ROOT / "app" / "data" / "agent"
SCN = {"id": "clear_210", "kind": "clear", "seq": "210", "t0": 20.0, "t1": 20.6, "drone": True, "entry": None}
OUT = ROOT / "results" / "agent" / "faults"
NO_ALERT = {"alert": False}


class TimeoutClient:
    def converse(self, **kw):
        from botocore.exceptions import ReadTimeoutError
        time.sleep(0.05)
        raise ReadTimeoutError(endpoint_url="https://bedrock-runtime.us-east-1.amazonaws.com/model/converse (injected stub, no network)")


class DropoutStore:
    def __init__(self, store):
        self.store, self.cache = store, {}

    def get(self, seq):
        if seq not in self.cache:
            import copy
            sl = copy.copy(self.store.get(seq))
            sl.x, sl.y, sl.p, sl.t = sl.x[:0], sl.y[:0], sl.p[:0], sl.t[:0]
            self.cache[seq] = sl
        return self.cache[seq]


def deny(*a, **k):
    return {"approved": False, "responder": "operator rejected (injected)"}


def no_answer(*a, **k):
    return {"approved": False, "timeout": True, "responder": "no answer within 60 s (injected)"}


def console_crash(*a, **k):
    raise ConnectionError("injected: operator console unreachable")


def _hum_call(store, trace_dir):
    _, rows = run_episode(SCN, store, "rule", Path(trace_dir) / "_probe.jsonl")
    hum = next(r for r in rows if r["kind"] == "step" and isinstance(r["result"], dict) and r["result"].get("verdict") == "hum")
    det = next(r for r in rows if r["kind"] == "step" and r["tool"] == "detect_frame")
    return det, hum


def _first_box(store):
    d = vision.detect(store.get(SCN["seq"]), SCN["t0"])["detections"]
    return d[0]["box"] if d else [220, 343, 281, 373]


def _corrupt_store(tmp, how):
    src = DATA / "clear_mini3_seq93"
    dst = Path(tmp) / "corrupt"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(src / "meta.json", dst / "meta.json")
    b = (src / "events.npz").read_bytes()
    if how == "truncated":
        b = b[: len(b) // 2]
    else:
        b = b[:200] + bytes(x ^ 0xFF for x in b[200:5000]) + b[5000:]
    (dst / "events.npz").write_bytes(b)
    return Store(Path(tmp)), {"id": f"corrupt_{how}", "kind": "clear", "seq": "93", "t0": 88.381, "t1": 88.981, "drone": True, "entry": None}


def episode(store, scn, planner, trace, **kw):
    try:
        s, rows = run_episode(scn, store, planner, trace, **kw)
        return s, rows, None
    except Exception as e:
        return None, [], f"{type(e).__module__}.{type(e).__name__}: {str(e)[:160]}"


def describe(s, rows, crash):
    if crash:
        return "nothing: the runner raised", f"episode crashed ({crash})"
    did, by = [], []
    if any(r["kind"] == "missing_data" for r in rows):
        e = next(r for r in rows if r["kind"] == "missing_data")["error"]
        by.append("data loader")
        did.append(f"stopped before any tool ran ({e.split(':')[0]})")
    pe = [r for r in rows if r["kind"] == "planner_error"]
    if pe:
        by.append("planner error handler")
        did.append(f"{len(pe)} planner errors ({pe[0]['error']})")
    if any(r["kind"] == "fallback" for r in rows):
        did.append("switched to the rule planner")
    steps = [r for r in rows if r["kind"] == "step"]
    rej = [r for r in steps if r["guard"].startswith("rejected")]
    if rej:
        by.append("guard")
        reasons = []
        for r in rej:
            x = re.sub(r"^\d+ ", "", r["guard"][len("rejected: "):].split(";")[0])
            if x not in reasons:
                reasons.append(x)
        did.append(f"guard refused {len(rej)} call(s): " + "; ".join(reasons[:3]))
    terr = [r for r in steps if r.get("tool_error")]
    if terr:
        by.append("tool retry")
        did.append(f"{terr[0]['tool']} failed twice, error returned to the planner")
        if terr[0]["tool"] == "ask_human":
            by.append("approval gate")
            did.append("no approval, so no alert")
    spec = [r for r in steps if r["tool"] in ("box_spectrum", "request_window") and isinstance(r["result"], dict) and "n_events" in r["result"]]
    thin = [r for r in spec if r["result"]["n_events"] < r["result"].get("thresholds", {}).get("min_events", 0)]
    if spec and len(thin) == len(spec):
        dets = sum(len(r["result"].get("detections", [])) for r in steps if r["tool"] == "detect_frame" and isinstance(r["result"], dict))
        by.append("evidence rule")
        did.append(f"detector still proposed {dets} boxes; every spectrum had {max(r['result']['n_events'] for r in thin)} events, below the {thin[0]['result']['thresholds']['min_events']} needed, so no hum")
    dets = [r for r in steps if r["tool"] == "detect_frame" and isinstance(r["result"], dict) and "detections" in r["result"]]
    if not spec and dets and not any(r["result"]["detections"] for r in dets):
        by.append("evidence rule")
        did.append(f"{len(dets)} looks, no candidate box, so nothing to measure and no alert")
    rec = [r for r in steps if r.get("attempts") == 2 and not r.get("tool_error")]
    if rec:
        by.append("tool retry")
        did.append(f"{rec[0]['tool']} timed out once, retry succeeded")
    asks = [r for r in steps if r["tool"] == "ask_human" and r["guard"] == "ok" and isinstance(r["result"], dict)]
    for a in asks:
        if a["result"].get("timeout"):
            by.append("approval gate")
            did.append("operator gave no answer: held as unconfirmed")
        elif a["result"].get("approved") is False:
            by.append("approval gate")
            did.append("operator said no")
    ff = [r for r in rows if r["kind"] == "forced_finish"]
    if ff:
        by.append("budget stop")
        did.append(f"stopped: {ff[0]['reason']}")
    if s and s["alerts"]:
        did.append(f"alert raised ({s['alerts'][0]['severity']})")
    seen = []
    for b in by:
        if b not in seen:
            seen.append(b)
    return (", ".join(seen) or "not needed"), "; ".join(did) or "normal run"


def case_rows(trace_dir):
    store = Store(DATA)
    td = Path(trace_dir)
    box = _first_box(store)
    det, hum = _hum_call(store, td)
    t_det = det["args"]["t"]
    cases = []

    def add(cid, fault, fn, expect):
        cases.append({"id": cid, "fault": fault, "fn": fn, "expect": expect})

    add("baseline", "None (control run)",
        lambda tr: episode(store, SCN, "rule", tr), {"alert": True, "outcome": {"drone_alerted"}})
    add("bedrock_down", "Bedrock unreachable (connection error)",
        lambda tr: episode(store, SCN, "bedrock", tr, client=DownClient()), {"alert": True, "outcome": {"drone_alerted"}, "fallback": True})
    add("bedrock_timeout", "Bedrock read timeout",
        lambda tr: episode(store, SCN, "bedrock", tr, client=TimeoutClient()), {"alert": True, "outcome": {"drone_alerted"}, "fallback": True})
    add("bedrock_no_tool_call", "Bedrock answers in prose, no tool call",
        lambda tr: episode(store, SCN, "bedrock", tr, client=TextOnlyClient()), {"alert": True, "outcome": {"drone_alerted"}, "fallback": True})
    add("bedrock_bad_args", "Bedrock tool calls with bad arguments",
        lambda tr: episode(store, SCN, "bedrock", tr, client=ScriptedClient([
            ("box_spectrum", "not an object"), ("teleport", {}), ("detect_frame", {"seq": "210"}),
            ("detect_frame", {"seq": "210", "t": "soon"}), ("finish", {"verdict": "no_drone", "reason": "after bad calls"})])),
        {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("bedrock_bad_args_forever", "Bedrock repeats a bad call forever",
        lambda tr: episode(store, SCN, "bedrock", tr, client=ScriptedClient([("teleport", {})])),
        {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("tool_raises", "Spectrum tool raises an exception",
        lambda tr: _patched("box_spectrum", _raiser, lambda: episode(store, SCN, "rule", tr)),
        {**NO_ALERT, "outcome": {"no_drone"}})
    add("tool_hangs", "Spectrum tool hangs past its 0.5 s timeout once",
        lambda tr: _patched("box_spectrum", lambda f: slow(f, 1.0, times=1), lambda: episode(store, SCN, "rule", tr, timeout_s=0.5)),
        {"alert": True, "outcome": {"drone_alerted"}})
    add("empty_events", "Event stream empty for the whole watch (sensor dropout)",
        lambda tr: episode(DropoutStore(store), SCN, "rule", tr), {**NO_ALERT, "outcome": {"no_drone"}})
    for how in ("truncated", "bitflip"):
        add(f"corrupt_{how}", f"Event file {'truncated to half' if how == 'truncated' else 'with flipped bytes'}",
            lambda tr, how=how: _with_corrupt(how, tr), {**NO_ALERT, "outcome": {"error_missing_data"}})
    add("missing_sequence", "Sequence not on disk",
        lambda tr: episode(store, {**SCN, "id": "missing", "seq": "404"}, "rule", tr), {**NO_ALERT, "outcome": {"error_missing_data"}})
    add("window_too_long", "Windows past budget or in the future",
        lambda tr: episode(store, SCN, "bedrock", tr, client=ScriptedClient([
            ("request_window", {"seq": "210", "box": box, "length_ms": 5000}),
            ("frequency_map", {"seq": "210", "t0": 19.5, "t1": 20.0}),
            ("box_spectrum", {"seq": "210", "box": box, "t0": 20.0, "t1": 20.5}),
            ("finish", {"verdict": "no_drone", "reason": "after budget refusals"})])),
        {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("too_many_steps", "Step budget of 3 tool calls",
        lambda tr: episode(store, SCN, "rule", tr, budget=Budget(max_steps=3)), {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("event_flood", "Window holds more events than the per-call cap (1,000)",
        lambda tr: episode(store, SCN, "rule", tr, budget=Budget(max_events_per_call=1000)), {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("alert_no_evidence", "Alert with no hum verdict; drone_alerted with no alert",
        lambda tr: episode(store, SCN, "bedrock", tr, client=ScriptedClient([
            ("raise_alert", {"seq": "210", "box": box, "severity": "warning", "reason": "looks like a drone"}),
            ("finish", {"verdict": "drone_alerted", "reason": "no evidence"}),
            ("finish", {"verdict": "no_drone", "reason": "after refusals"})])),
        {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("approval_rejected", "Operator rejects the critical alert",
        lambda tr: episode(store, SCN, "rule", tr, approver=deny), {**NO_ALERT, "outcome": {"no_drone"}})
    hb = hum["args"]["box"]
    add("approval_rejected_bypass", "Operator says no, planner tries a warning alert anyway",
        lambda tr: episode(store, SCN, "bedrock", tr, approver=deny, client=ScriptedClient([
            ("detect_frame", {"seq": "210", "t": t_det}), (hum["tool"], hum["args"]),
            ("ask_human", {"seq": "210", "box": hb, "severity": "critical", "question": "approve?"}),
            ("raise_alert", {"seq": "210", "box": hb, "severity": "warning", "reason": "operator said no, alerting anyway"}),
            ("finish", {"verdict": "no_drone", "reason": "operator rejected"})])),
        {**NO_ALERT, "outcome": {"no_drone"}, "guard": True})
    add("approval_timeout", "Operator never answers",
        lambda tr: episode(store, SCN, "rule", tr, approver=no_answer), {**NO_ALERT, "outcome": {"unconfirmed_waiting_for_operator"}})
    add("approval_console_down", "Operator console crashes",
        lambda tr: episode(store, SCN, "rule", tr, approver=console_crash), {**NO_ALERT, "outcome": {"no_drone"}})
    return cases


def _raiser(f):
    def boom(*a, **k):
        raise RuntimeError("injected: OpenCV dft failed")
    return boom


def _patched(attr, wrap, run):
    orig = getattr(vision, attr)
    setattr(vision, attr, wrap(orig))
    try:
        return run()
    finally:
        setattr(vision, attr, orig)


def _with_corrupt(how, tr):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store, scn = _corrupt_store(tmp, how)
        return episode(store, scn, "rule", tr)


def judge(c, s, rows, crash):
    e = c["expect"]
    alert = bool(s and s["alerts"])
    outcome = s["verdict"] if s else "crash"
    ok = crash is None and alert == e["alert"] and outcome in e["outcome"]
    if e.get("fallback"):
        ok = ok and any(r["kind"] == "fallback" for r in rows)
    guard = any(r["kind"] == "step" and r["guard"].startswith("rejected") for r in rows) or any(r["kind"] == "forced_finish" for r in rows)
    if e.get("guard"):
        ok = ok and guard
    return ok, alert, outcome, guard


def run_case(c, trace_dir):
    tr = Path(trace_dir) / f"{c['id']}.jsonl"
    t = time.perf_counter()
    s, rows, crash = c["fn"](tr)
    ok, alert, outcome, guard = judge(c, s, rows, crash)
    by, did = describe(s, rows, crash)
    return {"id": c["id"], "fault": c["fault"], "caught_by": by, "guard_blocked": guard,
            "fallback": did, "outcome": outcome, "alert_raised": alert, "expected_outcome": sorted(c["expect"]["outcome"]),
            "expected_alert": c["expect"]["alert"], "pass": ok, "crash": crash,
            "steps": s["steps"] if s else None, "rejections": s["rejections"] if s else None,
            "planner_final": s["planner_final"] if s else None, "wall_s": round(time.perf_counter() - t, 2),
            "trace": tr.name if tr.exists() and tr.stat().st_size else None}


def _mcp_text(res):
    txt = "".join(getattr(b, "text", "") for b in res.content)
    try:
        return json.loads(txt)
    except ValueError:
        return {"text": txt[:200]}


async def _mcp_session(calls, trace):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = {**os.environ, "HERTZ_DATA": str(DATA), "HERTZ_MCP_TRACE": str(trace), "PYTHONPATH": str(ROOT)}
    p = StdioServerParameters(command=sys.executable, args=["-m", "hertz.agent.mcp_server"], env=env, cwd=str(ROOT))
    out = {"calls": []}
    async with contextlib.AsyncExitStack() as stack:
        quiet = stack.enter_context(open(os.devnull, "w"))
        r, w = await stack.enter_async_context(stdio_client(p, errlog=quiet))
        s = await stack.enter_async_context(ClientSession(r, w))
        await s.initialize()
        out["tools"] = sorted(t.name for t in (await s.list_tools()).tools)
        for name, args in calls:
            try:
                res = await s.call_tool(name, args)
                body = _mcp_text(res)
                err = bool(res.isError) or "error" in body
            except Exception as e:
                body, err = {"exception": f"{type(e).__name__}: {str(e)[:160]}"}, True
            out["calls"].append({"tool": name, "args": args, "error": err, "result": body})
    return out


def mcp_bad_args(trace_dir):
    box = [220, 343, 281, 373]
    bad = [("detect_frame", {"seq": "210", "t": 20.1}),
           ("start_watch", {"seq": "404", "t_start": 20.0, "t_end": 20.6}),
           ("start_watch", {"seq": "210", "t_start": 5.0, "t_end": 6.0}),
           ("start_watch", {"seq": "210", "t_start": 20.0, "t_end": 20.6}),
           ("teleport", {}),
           ("detect_frame", {"seq": "210", "t": "soon"}),
           ("detect_frame", {"seq": "999", "t": 20.1}),
           ("box_spectrum", {"seq": "210", "box": [1, 2, 3], "t0": 19.9, "t1": 20.0}),
           ("box_spectrum", {"seq": "210", "box": box, "t0": 20.0, "t1": 20.5}),
           ("raise_alert", {"seq": "210", "box": box, "severity": "warning", "reason": "no evidence"}),
           ("ask_human", {"seq": "210", "box": box, "severity": "critical", "question": "approve?"}),
           ("raise_alert", {"seq": "210", "box": box, "severity": "critical", "reason": "no approval"}),
           ("detect_frame", {"seq": "210", "t": 20.1})]
    t = time.perf_counter()
    trace = Path(trace_dir) / "mcp_bad_args.jsonl"
    try:
        out = asyncio.run(_mcp_session(bad, trace))
        crash = None
    except Exception as e:
        out, crash = {"calls": []}, f"{type(e).__name__}: {str(e)[:160]}"
    calls = out["calls"]
    bad_idx = [0, 1, 2, 4, 5, 6, 7, 8, 9, 11]
    refused = [i for i in bad_idx if i < len(calls) and calls[i]["error"]]
    ask = calls[10]["result"] if len(calls) > 10 else {}
    good = len(calls) == len(bad) and not calls[3]["error"] and not calls[12]["error"] and "detections" in calls[12]["result"]
    alert = any(c["tool"] == "raise_alert" and not c["error"] for c in calls)
    ok = crash is None and len(refused) == len(bad_idx) and good and not alert and ask.get("approved") is False
    return {"id": "mcp_bad_args", "fault": "MCP server called with bad arguments", "caught_by": "MCP schema check, guard, approval gate",
            "guard_blocked": len(refused) == len(bad_idx),
            "fallback": f"{len(refused)} of {len(bad_idx)} bad calls refused with a reason; no operator reachable, ask denied by default; server kept serving",
            "outcome": "server alive" if good else "server failed", "alert_raised": alert, "expected_outcome": ["server alive"],
            "expected_alert": False, "pass": ok, "crash": crash, "steps": len(calls), "rejections": len(refused),
            "planner_final": None, "wall_s": round(time.perf_counter() - t, 2), "trace": trace.name if trace.exists() else None,
            "mcp_calls": calls}


TABLE_HEAD = "| # | Fault injected | Caught by | What the agent did | Final verdict | Alert raised | Pass |\n|---|---|---|---|---|---|---|\n"


def table(res, meta):
    n_ok = sum(r["pass"] for r in res)
    false_alerts = sum(r["alert_raised"] and not r["expected_alert"] for r in res)
    lines = [f"# Agent fault injection: {n_ok} of {len(res)} cases pass, {false_alerts} unsafe alerts\n",
             f"Real FRED data (sequence 210, {SCN['t0']}-{SCN['t1']} s, `app/data/agent`), the real agent loop and guard, a stubbed Bedrock (no network). "
             f"Detector: {meta['detector']}. Operator: the simulated auto-approver unless the row injects an operator fault. "
             f"Written by `python eval/fault_eval.py`; raw rows in `results.json`, one JSON-lines trace per case in `traces/`.\n",
             TABLE_HEAD]
    for i, r in enumerate(res, 1):
        did = r["fallback"].replace("|", "/")
        lines.append(f"| {i} | {r['fault']} | {r['caught_by']} | {did} | `{r['outcome']}` | {'yes' if r['alert_raised'] else 'no'} | {'PASS' if r['pass'] else 'FAIL'} |\n")
    return "".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-mcp", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    tdir = out / "traces"
    if tdir.exists():
        shutil.rmtree(tdir)
    tdir.mkdir(parents=True)
    res = [run_case(c, tdir) for c in case_rows(tdir)]
    (tdir / "_probe.jsonl").unlink(missing_ok=True)
    if not a.no_mcp:
        res.append(mcp_bad_args(tdir))
    meta = {"data": "app/data/agent/clear_210", "scenario": SCN, "detector": vision.SOURCE.get("detect"), "spectrum": vision.SOURCE.get("spectrum"),
            "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "python": sys.version.split()[0]}
    (out / "results.json").write_text(json.dumps({"meta": meta, "passed": sum(r["pass"] for r in res), "cases": len(res), "results": res}, indent=1, default=str), encoding="utf-8")
    (out / "TABLE.md").write_text(table(res, meta), encoding="utf-8")
    print(table(res, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())

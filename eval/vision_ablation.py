import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hertz.agent.data import Store
from hertz.agent.guard import Budget, State, iou
from hertz.agent.planners import BedrockPlanner
from hertz.agent.tools import Toolbox

VISION = ("box_spectrum", "request_window", "frequency_map")


def history(rows, k):
    msgs = []
    for r in rows[:k]:
        tid = f"s{r['step']}"
        content = ([{"text": r["why"]}] if r["why"] else []) + [{"toolUse": {"toolUseId": tid, "name": r["tool"], "input": r["args"]}}]
        msgs.append({"role": "assistant", "content": content})
        res = r["result"] if r["guard"] == "ok" else {"error": f"guard {r['guard']}"}
        msgs.append({"role": "user", "content": [{"toolResult": {"toolUseId": tid, "content": [{"json": res}],
                                                                  "status": "error" if "error" in res else "success"}}]})
    return msgs


def variant(tb, sl, row, mode):
    r = dict(row["result"])
    tb.vision_mode = mode
    if row["tool"] == "frequency_map":
        a = row["args_checked"]
        v = tb._map(sl, a["t0"], a["t1"])
    else:
        v = tb._measure(sl, r["box"], r["t0"], r["t1"])
    keep = {k: r[k] for k in ("box", "t0", "t1", "now") if k in r}
    v.update(keep)
    return v


def action(out):
    msg = out["output"]["message"]
    u = next((b["toolUse"] for b in msg["content"] if "toolUse" in b), None)
    return None if u is None else {"tool": u["name"], "input": u.get("input", {})}


def differs(a, b):
    if a is None or b is None:
        return a is not b
    if a["tool"] != b["tool"]:
        return True
    ba, bb = a["input"].get("box"), b["input"].get("box")
    if isinstance(ba, list) and isinstance(bb, list) and len(ba) == 4 and len(bb) == 4 and iou(ba, bb) < 0.5:
        return True
    if a["tool"] == "finish" and a["input"].get("verdict") != b["input"].get("verdict"):
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--data", default=str(root / "data" / "fred_slices"))
    ap.add_argument("--traces", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    store = Store(a.data)
    jobs = []
    for f in sorted(Path(a.traces).glob("bedrock_*.jsonl")):
        if f.stem.count("_") > 2:
            continue
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
        start = next(r for r in rows if r["kind"] == "start")
        steps = [r for r in rows if r["kind"] == "step" and r["planner"] == "bedrock"]
        for k, r in enumerate(steps):
            if r["tool"] in VISION and r["guard"] == "ok" and "error" not in (r["result"] or {}):
                jobs.append((f.stem, start, steps, k))
    usage = {"input": 0, "output": 0, "calls": 0}

    def run(job):
        stem, start, steps, k = job
        scn = start["scenario"]
        sl = store.get(scn["seq"])
        st = State(seq=str(scn["seq"]), t_start=float(scn["t0"]), t_end=float(scn["t1"]), width=sl.width, height=sl.height)
        pl = BedrockPlanner(st, Budget())
        tb = Toolbox(store, Budget(), seed=k + 7 * len(stem))
        base = pl.messages + history(steps, k)
        row = steps[k]
        tid = f"s{row['step']}"
        call = {"role": "assistant", "content": ([{"text": row["why"]}] if row["why"] else []) +
                [{"toolUse": {"toolUseId": tid, "name": row["tool"], "input": row["args"]}}]}
        out = {"trace": stem, "step": row["step"], "tool": row["tool"], "real_verdict": row["result"].get("verdict"),
               "logged_next": steps[k + 1]["tool"] if k + 1 < len(steps) else None}
        for mode in ("real", "blind", "shuffle"):
            res = row["result"] if mode == "real" else variant(tb, sl, row, mode)
            msgs = base + [call, {"role": "user", "content": [{"toolResult": {"toolUseId": tid, "content": [{"json": res}], "status": "success"}}]}]
            o = pl.client.converse(modelId=pl.model, system=[{"text": pl.system}], messages=msgs, toolConfig=pl.tools,
                                   inferenceConfig={"maxTokens": 600, "temperature": 0})
            usage["input"] += o.get("usage", {}).get("inputTokens", 0)
            usage["output"] += o.get("usage", {}).get("outputTokens", 0)
            usage["calls"] += 1
            out[mode] = action(o)
            if mode != "real":
                out[f"{mode}_verdict"] = res.get("verdict")
        out["changed_blind"] = differs(out["real"], out["blind"])
        out["changed_shuffle"] = differs(out["real"], out["shuffle"])
        out["control_matches_log"] = out["real"] is not None and out["real"]["tool"] == out["logged_next"]
        return out

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(run, jobs))
    n = len(res)
    sh = [r for r in res if r["shuffle_verdict"] != r["real_verdict"]]
    summary = {"vision_steps": n, "episodes": len({r["trace"] for r in res}),
               "decision_changed_by_vision_blind": sum(r["changed_blind"] for r in res),
               "decision_changed_by_vision_blind_rate": round(sum(r["changed_blind"] for r in res) / n, 3) if n else None,
               "decision_changed_by_vision_shuffle": sum(r["changed_shuffle"] for r in res),
               "decision_changed_by_vision_shuffle_rate": round(sum(r["changed_shuffle"] for r in res) / n, 3) if n else None,
               "shuffle_steps_where_verdict_differs": len(sh),
               "of_which_decision_changed": sum(r["changed_shuffle"] for r in sh),
               "control_next_tool_matches_logged_run": sum(r["control_matches_log"] for r in res),
               "by_real_verdict": {v: {"steps": sum(str(r["real_verdict"]) == v for r in res),
                                       "changed_blind": sum(r["changed_blind"] for r in res if str(r["real_verdict"]) == v),
                                       "changed_shuffle": sum(r["changed_shuffle"] for r in res if str(r["real_verdict"]) == v)}
                                   for v in sorted({str(r["real_verdict"]) for r in res})},
               "usage": usage}
    report = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "metric": "decision changed by vision: for each vision step (box_spectrum, request_window, frequency_map) of a real Bedrock run, the model is asked for its next action twice with the identical history: once with the real OpenCV result, once with that one result blinded (verdict, peak, snr removed) or shuffled (the same measurement on a random box of the same size). A step counts as changed when the next tool differs, the target box overlaps under IoU 0.5, or the finish verdict differs. Temperature 0.",
              "traces": a.traces, "summary": summary, "steps": res}
    Path(a.out).write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

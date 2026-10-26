import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hertz.agent import vision
from hertz.agent.data import Store
from hertz.agent.guard import Budget, iou
from hertz.agent.runner import run_episode


def gt_box(sl, t):
    rows = sorted(sl.meta["gt"], key=lambda r: abs(r["t"] - t))
    return [r["box"] for r in rows[:3] if abs(r["t"] - t) <= 0.1]


def hit(alert_box, gts, pad=20):
    for g in gts:
        if iou(alert_box, g) >= 0.1:
            return True
        cx, cy = (alert_box[0] + alert_box[2]) / 2, (alert_box[1] + alert_box[3]) / 2
        if g[0] - pad <= cx <= g[2] + pad and g[1] - pad <= cy <= g[3] + pad:
            return True
    return False


def vision_changed(rows):
    steps = [r for r in rows if r["kind"] == "step" and r["guard"] == "ok"]
    out = []
    for a, b in zip(steps, steps[1:]):
        ra, rb = a["result"] or {}, b["result"] or {}
        if a["tool"] in ("box_spectrum", "request_window") and ra.get("verdict") == "ambiguous" and b["tool"] == "request_window" \
                and iou(a["args_checked"]["box"], b["args_checked"]["box"]) > 0.3:
            out.append({"from_step": a["step"], "to_step": b["step"], "before": [ra["window_ms"], ra["snr"], ra["verdict"]],
                        "after": [rb.get("window_ms"), rb.get("snr"), rb.get("verdict")],
                        "decision_changed": rb.get("verdict") != "ambiguous"})
    return out


def transitions(rows):
    steps = [r for r in rows if r["kind"] == "step"]
    out = []
    for a, b in zip(steps, steps[1:]):
        v = (a["result"] or {}).get("verdict") if a["tool"] in ("box_spectrum", "request_window") else None
        if v:
            out.append([v, b["tool"]])
    return out


def score(scn, summary, rows, store):
    sl = store.get(scn["seq"])
    start = scn["entry"] if scn["entry"] is not None else scn["t0"]
    good, bad = [], []
    for al in summary["alerts"]:
        ok = scn["drone"] and al["t"] >= start - 0.05 and hit(al["box"], gt_box(sl, al["t"]))
        (good if ok else bad).append(al)
    success = (len(good) > 0 and not bad) if scn["drone"] else not summary["alerts"]
    steps = [r for r in rows if r["kind"] == "step"]
    return {"id": scn["id"], "kind": scn["kind"], "drone": scn["drone"], "success": success, "true_alerts": len(good),
            "false_alerts": len(bad), "verdict": summary["verdict"], "steps": summary["steps"], "rejections": summary["rejections"],
            "asks": summary["asks"], "wall_s": summary["wall_s"], "tool_ms": summary["tool_ms"],
            "planner_ms": round(sum(r.get("planner_ms", 0) for r in steps if r.get("planner_ms")), 1) if steps else 0,
            "stream_latency_s": round(good[0]["t"] - start, 3) if good else None,
            "planner_final": summary["planner_final"], "planner_failures": summary["planner_failures"],
            "fallbacks": sum(1 for r in rows if r["kind"] == "fallback"),
            "tool_calls": [r["tool"] for r in steps], "vision_changed_next_call": vision_changed(rows), "transitions": transitions(rows),
            "bedrock_usage": summary["bedrock_usage"]}


def agg(rs):
    n = len(rs)
    lat = [r["stream_latency_s"] for r in rs if r["stream_latency_s"] is not None]
    return {"episodes": n, "success": sum(r["success"] for r in rs), "success_rate": round(sum(r["success"] for r in rs) / n, 3) if n else None,
            "false_alerts": sum(r["false_alerts"] for r in rs), "mean_steps": round(statistics.mean(r["steps"] for r in rs), 2) if n else None,
            "mean_wall_s": round(statistics.mean(r["wall_s"] for r in rs), 3) if n else None,
            "median_stream_latency_s": round(statistics.median(lat), 3) if lat else None,
            "vision_changed_next_call": sum(len(r["vision_changed_next_call"]) for r in rs),
            "of_which_decision_changed": sum(sum(v["decision_changed"] for v in r["vision_changed_next_call"]) for r in rs),
            "fallbacks": sum(r["fallbacks"] for r in rs), "asks": sum(r["asks"] for r in rs),
            "next_tool_after_verdict": _tally(rs)}


def _tally(rs):
    t = {}
    for r in rs:
        for v, nxt in r.get("transitions", []):
            t.setdefault(v, {}).setdefault(nxt, 0)
            t[v][nxt] += 1
    return t


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--data", default=str(root / "data" / "fred_slices"))
    ap.add_argument("--scenarios", default=str(root / "eval" / "scenarios.json"))
    ap.add_argument("--planners", default="bedrock,rule,fixed")
    ap.add_argument("--only", default="")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rescore", action="store_true")
    a = ap.parse_args()
    store = Store(a.data)
    scen = json.loads(Path(a.scenarios).read_text())["scenarios"]
    if a.only:
        scen = [s for s in scen if s["id"] in a.only.split(",")]
    out = Path(a.out)
    (out / "traces").mkdir(parents=True, exist_ok=True)
    res = {}
    for p in a.planners.split(","):
        res[p] = []
        for s in scen:
            tp = out / "traces" / f"{p}_{s['id']}.jsonl"
            if a.rescore:
                rows = [json.loads(l) for l in tp.read_text(encoding="utf-8").splitlines()]
                summary = next(r for r in rows if r["kind"] == "end")
            else:
                summary, rows = run_episode(s, store, p, tp, Budget(), model=a.model)
            r = score(s, summary, rows, store)
            res[p].append(r)
            print(p, s["id"], "success" if r["success"] else "FAIL", "true", r["true_alerts"], "false", r["false_alerts"],
                  "steps", r["steps"], "wall", r["wall_s"], "changed", len(r["vision_changed_next_call"]), flush=True)
    report = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "data": a.data, "scenarios": a.scenarios,
              "vision_source": dict(vision.SOURCE), "thresholds": {"hum_snr": vision.CLEAR_SNR, "ambiguous_snr": vision.AMB_SNR,
                                                                   "min_events": vision.MIN_EVENTS, "fs": vision.FS, "band": vision.BAND},
              "budget": Budget().__dict__, "summary": {p: agg(v) for p, v in res.items()},
              "by_kind": {p: {k: agg([r for r in v if r["kind"] == k]) for k in sorted({r["kind"] for r in v})} for p, v in res.items()},
              "episodes": res}
    (out / "results.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()

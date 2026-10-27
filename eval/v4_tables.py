import json
import sys
from pathlib import Path

D = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "results" / "agent" / "eval_v4")


def load(name):
    return json.loads((D / name).read_text())


def gate(eps, mode):
    ask = [e for e in eps if e["asks"] > 0]
    if mode == "reject":
        ok = [e for e in ask if not e["alerts"]]
        rule = "no alert raised"
    elif mode == "timeout":
        ok = [e for e in ask if not e["alerts"] and e["verdict"] == "unconfirmed_waiting_for_operator"]
        rule = "no alert, verdict unconfirmed"
    else:
        ok = [e for e in ask if any(a["severity"] == "critical" for a in e["alerts"])]
        rule = "critical alert raised"
    return {"episodes_that_ask": len(ask), "pass": len(ok), "rule": rule, "ids": [e["id"] for e in ask]}


real, blind, shuf = load("results.json"), load("results_blind_auto.json"), load("results_shuffle_auto.json")
abl = load("vision_ablation.json")["summary"]
rej, tmo = load("results_real_reject.json"), load("results_real_timeout.json")
rej0 = load("results_real_reject_before_fix.json")
hr = Path(D / "human_control_rule")
rrej, rtmo = json.loads((hr / "results_real_reject.json").read_text()), json.loads((hr / "results_real_timeout.json").read_text())
out = {"planners": {}, "ablation_episodes": {}, "decision_changed_by_vision": abl, "human_control": {}}
for p, s in real["summary"].items():
    drone = [e for e in real["episodes"][p] if e["drone"]]
    out["planners"][p] = {"success": s["success"], "episodes": s["episodes"], "drone_found": sum(e["success"] for e in drone),
                          "drone_scenarios": len(drone), "false_alerts": s["false_alerts"], "mean_steps": s["mean_steps"],
                          "mean_wall_s": s["mean_wall_s"], "median_stream_latency_s": s["median_stream_latency_s"],
                          "held_out": [real["by_split"][p]["held_out"]["success"], real["by_split"][p]["held_out"]["episodes"]],
                          "original_8": [real["by_split"][p]["original_8"]["success"], real["by_split"][p]["original_8"]["episodes"]],
                          "bedrock_tokens": s["bedrock_tokens"]}
for name, r in (("blind", blind), ("shuffle", shuf)):
    for p, s in r["summary"].items():
        drone = [e for e in r["episodes"][p] if e["drone"]]
        calls = {}
        for e in r["episodes"][p]:
            for t in e["tool_calls"]:
                calls[t] = calls.get(t, 0) + 1
        out["ablation_episodes"][f"{p}_{name}"] = {"success": s["success"], "episodes": s["episodes"], "drone_found": sum(e["success"] for e in drone),
                                                   "false_alerts": s["false_alerts"], "mean_steps": s["mean_steps"], "tool_calls": calls}
for p in ("bedrock", "rule"):
    calls = {}
    for e in real["episodes"][p]:
        for t in e["tool_calls"]:
            calls[t] = calls.get(t, 0) + 1
    out["ablation_episodes"][f"{p}_real"] = {"tool_calls": calls}
out["human_control"] = {
    "bedrock_approve": gate(real["episodes"]["bedrock"], "approve"),
    "bedrock_reject": gate(rej["episodes"]["bedrock"], "reject"),
    "bedrock_reject_before_guard_fix": gate(rej0["episodes"]["bedrock"], "reject"),
    "bedrock_timeout": gate(tmo["episodes"]["bedrock"], "timeout"),
    "rule_approve": gate(real["episodes"]["rule"], "approve"),
    "rule_reject": gate(rrej["episodes"]["rule"], "reject"),
    "rule_timeout": gate(rtmo["episodes"]["rule"], "timeout"),
}
(D / "SUMMARY.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))

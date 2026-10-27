import json
import os
import time
from dataclasses import dataclass, field

from .tools import schemas

MODEL = os.environ.get("HERTZ_MODEL", "us.anthropic.claude-sonnet-4-6")


class PlannerError(Exception):
    def __init__(self, kind, detail):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


@dataclass
class Call:
    name: str
    args: dict
    why: str = ""
    id: str = ""
    extra: dict = field(default_factory=dict)


class GeneratorPlanner:
    name = "rule"

    def __init__(self, st):
        self.st = st
        self.gen = self.policy(st)
        self.pending = None

    def decide(self, results):
        r = results[-1][1] if results else None
        try:
            c = next(self.gen) if self.pending is None else self.gen.send(r)
        except StopIteration:
            c = ("finish", {"verdict": "drone_alerted" if self.st.alerts else "no_drone", "reason": "policy exhausted"}, "end")
        self.pending = c
        return [Call(c[0], c[1], c[2], f"{self.name}-{self.st.steps}")]


def _ok(r):
    return isinstance(r, dict) and "error" not in r


class RulePlanner(GeneratorPlanner):
    name = "rule"
    first_ms, ladder, step_s, top_k = 100, (300, 1000), 0.25, 3

    def policy(self, st):
        seq, t = st.seq, st.now
        while True:
            det = yield ("detect_frame", {"seq": seq, "t": round(t, 4)}, "look at the newest frame")
            cands = det["detections"][: self.top_k] if _ok(det) else []
            for c in cands:
                box = c["box"]
                now = st.now
                sp = yield ("box_spectrum", {"seq": seq, "box": box, "t0": round(now - self.first_ms / 1000, 4), "t1": round(now, 4)},
                            f"check candidate {box} for a blade-pass peak")
                for ms in self.ladder:
                    if not (_ok(sp) and sp["verdict"] == "ambiguous"):
                        break
                    sp = yield ("request_window", {"seq": seq, "box": box, "length_ms": ms},
                                f"spectrum ambiguous (snr {sp['snr']}) at {sp['window_ms']} ms; re-check with {ms} ms")
                if not (_ok(sp) and sp["verdict"] == "hum"):
                    continue
                if sp["mains_like"]:
                    fm = yield ("frequency_map", {"seq": seq, "t0": round(st.now - 0.2, 4), "t1": round(st.now, 4)},
                                f"peak {sp['peak_hz']} Hz is mains-like; check if the whole scene flickers")
                    if _ok(fm) and fm["dominant_hz"] is not None and abs(fm["dominant_hz"] - sp["peak_hz"]) < 6 and fm["dominant_share"] > 0.3:
                        continue
                tr = yield ("track", {"seq": seq, "box": box, "t0": round(st.now, 4), "t1": round(min(st.t_end, st.now + 0.2), 4)},
                            f"hum at {sp['peak_hz']} Hz; follow the target before alerting")
                if not _ok(tr) or tr["lost"] or tr["displacement_px"] < 3.0:
                    continue
                ap = yield ("ask_human", {"seq": seq, "box": tr["box"], "severity": "critical",
                                          "question": f"Drone hum {sp['peak_hz']} Hz (snr {sp['snr']}) at {tr['box']}. Approve critical alert?"},
                            "critical alert needs approval")
                sev = "critical" if _ok(ap) and ap.get("approved") else "warning"
                yield ("raise_alert", {"seq": seq, "box": tr["box"], "severity": sev,
                                       "reason": f"blade-pass {sp['peak_hz']} Hz snr {sp['snr']}, tracked {tr['displacement_px']} px"},
                       "confirmed")
                yield ("finish", {"verdict": "drone_alerted", "reason": "alert raised"}, "done")
                return
            t = st.now + self.step_s
            if t > st.t_end:
                yield ("finish", {"verdict": "no_drone", "reason": "no humming target in the watch window"}, "done")
                return


class FixedPlanner(GeneratorPlanner):
    name = "fixed"
    every_s, window_ms = 0.5, 100

    def policy(self, st):
        seq, t = st.seq, st.t_start
        while t <= st.t_end + 1e-9:
            det = yield ("detect_frame", {"seq": seq, "t": round(t, 4)}, "fixed schedule")
            if _ok(det) and det["detections"]:
                box = det["detections"][0]["box"]
                sp = yield ("box_spectrum", {"seq": seq, "box": box, "t0": round(t - self.window_ms / 1000, 4), "t1": round(t, 4)}, "fixed schedule")
                if _ok(sp) and sp["verdict"] == "hum":
                    yield ("raise_alert", {"seq": seq, "box": box, "severity": "warning", "reason": f"hum {sp['peak_hz']} Hz"}, "fixed rule")
                    yield ("finish", {"verdict": "drone_alerted", "reason": "alert raised"}, "done")
                    return
            t = round(t + self.every_s, 4)
        yield ("finish", {"verdict": "no_drone", "reason": "schedule ended"}, "done")


SYSTEM = """You are Hertz, an active-perception agent that watches one FRED event-camera sequence for drones.
A drone is confirmed by its propeller hum: a blade-pass peak (hundreds of Hz to kHz) in the event-count spectrum inside its box. Birds, people, trees and flicker do not hum, or hum everywhere at mains multiples.
Your tools run OpenCV 5 on the real event stream. The clock starts at t_start; detect_frame and track move it forward; spectra can only look back at most 1 s.
Decide what to look at next from what the tools return:
- Start a new box with a short window (100-200 ms): a moving target stays inside its box and the check is cheap. Escalate with request_window (e.g. 300, then 1000 ms) only when the verdict is ambiguous.
- A hum source that does not move under track (displacement under 3 px over 0.5 s or more) is a fixed lamp, screen or sensor defect, not a flying drone: do not alert on it.
- verdict hum: confirm with track (target persists, not lost) before alerting. If mains_like is true, run frequency_map first; a frequency that fills much of the scene is flicker, not a drone.
- verdict ambiguous: do not alert and do not drop it; call request_window on the same box with a longer window (e.g. 300 then 1000 ms) for finer resolution and more events, or a tighter one if the target moves fast.
- verdict none on every candidate: move on in time (detect_frame later) or use frequency_map to search for a hum the detector missed.
- raise_alert is refused unless that box (or the start box of a track ending there) had a hum verdict in the last 1.5 s. Ambiguous evidence never justifies an alert: re-check, or move on.
- A critical alert needs ask_human approval on the same box first; warning does not.
- Do not repeat a measurement already made (same box, same window).
- Finish with drone_alerted after an alert, or no_drone when the watch window ends without a confirmed hum. Do not alert on non-humming movers.
Budgets: at most {max_steps} tool calls; windows {min_w}-{max_w} ms; frequency_map at most {max_map} ms. Call exactly one tool per turn. Keep any text before the tool call to one short sentence of reasoning."""


class BedrockPlanner:
    name = "bedrock"

    def __init__(self, st, budget, model=MODEL, profile="opencv26", region="us-east-1", client=None, timeout_s=30):
        import boto3
        from botocore.config import Config
        self.st, self.model = st, model
        self.client = client or boto3.Session(profile_name=profile, region_name=region).client(
            "bedrock-runtime", config=Config(read_timeout=timeout_s, connect_timeout=5, retries={"max_attempts": 2}))
        self.system = SYSTEM.format(max_steps=budget.max_steps, min_w=int(budget.min_window_ms), max_w=int(budget.max_window_ms),
                                    max_map=int(budget.max_map_ms))
        self.tools = {"tools": [{"toolSpec": {"name": s["name"], "description": s["description"], "inputSchema": {"json": s["input_schema"]}}}
                                for s in schemas()], "toolChoice": {"any": {}}}
        self.messages = [{"role": "user", "content": [{"text": json.dumps({
            "task": "Watch for drones and act.", "seq": st.seq, "t_start": st.t_start, "t_end": st.t_end, "now": st.now,
            "frame": [st.width, st.height]})}]}]
        self.usage = {"input": 0, "output": 0, "calls": 0, "latency_ms": 0.0}

    def decide(self, results):
        if results:
            self.messages.append({"role": "user", "content": [
                {"toolResult": {"toolUseId": c.id, "content": [{"json": r}], "status": "error" if "error" in r else "success"}}
                for c, r in results]})
        t = time.perf_counter()
        try:
            out = self.client.converse(modelId=self.model, system=[{"text": self.system}], messages=self.messages,
                                       toolConfig=self.tools, inferenceConfig={"maxTokens": 600, "temperature": 0})
        except Exception as e:
            raise PlannerError("bedrock_unavailable", f"{type(e).__name__}: {str(e)[:300]}")
        ms = (time.perf_counter() - t) * 1000
        self.usage["calls"] += 1
        self.usage["latency_ms"] += ms
        self.usage["input"] += out.get("usage", {}).get("inputTokens", 0)
        self.usage["output"] += out.get("usage", {}).get("outputTokens", 0)
        msg = out["output"]["message"]
        self.messages.append(msg)
        why = " ".join(b["text"] for b in msg["content"] if "text" in b).strip()
        uses = [b["toolUse"] for b in msg["content"] if "toolUse" in b]
        if not uses:
            self.messages.append({"role": "user", "content": [{"text": "You must call exactly one tool."}]})
            raise PlannerError("malformed_output", f"no tool call; text={why[:200]!r}")
        return [Call(u["name"], u.get("input"), why, u["toolUseId"], {"planner_ms": round(ms, 1)}) for u in uses]

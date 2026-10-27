import time

import numpy as np

from . import vision
from .guard import Reject, iou

BOX = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
       "description": "[x0, y0, x1, y1] in pixels of the 1280x720 event sensor"}
SEQ = {"type": "string", "description": "FRED sequence id under watch"}
SEV = {"type": "string", "enum": ["info", "warning", "critical"]}

SPECS = [
    ("detect_frame", "Run the detector on the frame at stream time t (seconds). Moves the clock forward to t. Returns candidate boxes.",
     {"seq": SEQ, "t": {"type": "number"}}),
    ("box_spectrum", "Event-count spectrum inside a box over [t0, t1] (seconds, t1 <= now). Returns the blade-pass peak in Hz, its strength snr (peak power over the local spectral floor within +-100 Hz, 150-1000 Hz band; hum at 98 or more, ambiguous from 7.9), and a verdict hum / ambiguous / none.",
     {"seq": SEQ, "box": BOX, "t0": {"type": "number"}, "t1": {"type": "number"}}),
    ("request_window", "Re-check a box with a longer or tighter event window of length_ms ending now. Longer windows give finer frequency resolution and more events; tighter windows follow a fast mover. Returns the new spectrum and how it differs from the last check on that box.",
     {"seq": SEQ, "box": BOX, "length_ms": {"type": "number"}}),
    ("frequency_map", "Per-pixel spectrum of the whole frame over [t0, t1] (at most 300 ms). Returns humming spots (boxes) the detector may have missed, the dominant frequency and the share of active pixels humming at it; one frequency filling the whole scene means flicker, not a drone.",
     {"seq": SEQ, "t0": {"type": "number"}, "t1": {"type": "number"}}),
    ("track", "Follow a box over [t0, t1] with an OpenCV Kalman filter on event centroids. t1 may be in the future: the watch waits until t1 and the clock moves there. Returns the end box at t1, velocity, displacement and whether the target was lost.",
     {"seq": SEQ, "box": BOX, "t0": {"type": "number"}, "t1": {"type": "number"}}),
    ("ask_human", "Ask the operator to approve an alert. Required before a critical alert.",
     {"seq": SEQ, "box": BOX, "severity": SEV, "question": {"type": "string"}}),
    ("raise_alert", "Raise a drone alert on a box. Needs a hum verdict on this box, or on the start box of a track that ended here, within the last 1.5 s. critical also needs prior human approval on the same box.",
     {"seq": SEQ, "box": BOX, "severity": SEV, "reason": {"type": "string"}}),
    ("finish", "End the watch. verdict drone_alerted only after an alert; otherwise no_drone.",
     {"verdict": {"type": "string", "enum": ["drone_alerted", "no_drone"]}, "reason": {"type": "string"}}),
]


def schemas():
    return [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p, "required": list(p)}} for n, d, p in SPECS]


def auto_approver(seq, box, severity, question, now):
    return {"approved": True, "responder": "auto-approve (evaluation stand-in for the operator, SIMULATED)"}


class Toolbox:
    def __init__(self, store, budget, approver=auto_approver, vision_mode="real", seed=0):
        self.store, self.budget, self.approver = store, budget, approver
        self.vision_mode, self.rng = vision_mode, np.random.default_rng(seed)
        self.last_spec = []
        self.hum_boxes = []

    def _measure(self, sl, box, t0, t1):
        if self.vision_mode == "shuffle":
            w, h = box[2] - box[0], box[3] - box[1]
            x0, y0 = int(self.rng.integers(0, max(1, sl.width - w))), int(self.rng.integers(0, max(1, sl.height - h)))
            return vision.box_spectrum(sl, [x0, y0, x0 + w, y0 + h], t0, t1)
        r = vision.box_spectrum(sl, box, t0, t1)
        if self.vision_mode == "blind":
            r.update({"peak_hz": None, "snr": None, "mains_like": None, "verdict": "unavailable"})
        return r

    def _map(self, sl, t0, t1):
        r = vision.frequency_map(sl, t0, t1)
        if self.vision_mode == "blind":
            r.update({"hum_pixels": None, "dominant_hz": None, "dominant_share": None, "hum_spots": []})
        elif self.vision_mode == "shuffle":
            for s in r.get("hum_spots", []):
                b = s["box"]
                w, h = b[2] - b[0], b[3] - b[1]
                x0, y0 = int(self.rng.integers(0, max(1, sl.width - w))), int(self.rng.integers(0, max(1, sl.height - h)))
                s["box"] = [x0, y0, x0 + w, y0 + h]
        return r

    def _cap(self, sl, t0, t1):
        s = sl.window(t0, t1)
        n = s.stop - s.start
        if n > self.budget.max_events_per_call:
            raise Reject(f"{n} events in window exceeds the per-call cap {self.budget.max_events_per_call}; use a shorter window")

    def _spec(self, sl, box, t0, t1, st):
        self._cap(sl, t0, t1)
        for p in self.last_spec:
            if p["box"] == box and abs(p["t0"] - round(t0, 4)) < 1e-3 and abs(p["t1"] - round(t1, 4)) < 1e-3:
                raise Reject("this exact window on this box was already measured; change length_ms, box or time")
        r = self._measure(sl, box, t0, t1)
        r.update({"box": box, "t0": round(t0, 4), "t1": round(t1, 4)})
        prev = next((p for p in reversed(self.last_spec) if iou(p["box"], box) > 0.3), None)
        if prev is not None:
            r["previous"] = {k: prev[k] for k in ("window_ms", "peak_hz", "snr", "verdict")}
            r["verdict_changed"] = prev["verdict"] != r["verdict"]
        self.last_spec.append(r)
        if r["verdict"] == "hum":
            self.hum_boxes.append({"box": box, "now": st.now, "peak_hz": r["peak_hz"]})
        return r

    def evidence(self, box, now, horizon=1.5):
        return any(now - h["now"] <= horizon and iou(h["box"], box) > 0.1 for h in self.hum_boxes)

    def run(self, name, a, st):
        sl = self.store.get(a["seq"]) if "seq" in a else None
        if name == "detect_frame":
            st.now = max(st.now, a["t"])
            self._cap(sl, a["t"] - 0.033, a["t"])
            r = vision.detect(sl, a["t"])
        elif name == "box_spectrum":
            r = self._spec(sl, a["box"], a["t0"], a["t1"], st)
        elif name == "request_window":
            r = self._spec(sl, a["box"], st.now - a["length_ms"] / 1000.0, st.now, st)
        elif name == "frequency_map":
            self._cap(sl, a["t0"], a["t1"])
            r = self._map(sl, a["t0"], a["t1"])
        elif name == "track":
            self._cap(sl, a["t0"], a["t1"])
            st.now = max(st.now, a["t1"])
            r = vision.track(sl, a["box"], a["t0"], a["t1"])
            if not r["lost"] and self.evidence(a["box"], a["t0"]):
                self.hum_boxes.append({"box": r["box"], "now": st.now, "peak_hz": None, "tracked_from": a["box"]})
        elif name == "ask_human":
            r = dict(self.approver(a["seq"], a["box"], a["severity"], a["question"], st.now))
            st.approvals.append({"box": a["box"], "approved": bool(r["approved"]), "now": st.now, "severity": a["severity"]})
            if r.get("timeout"):
                st.unconfirmed = st.finished = True
                r["status"] = "unconfirmed, waiting for operator: no answer in time, so no alert is raised"
        elif name == "raise_alert":
            if not self.evidence(a["box"], st.now):
                raise Reject("no hum verdict on this box (or on a track that started from a hum box) in the last 1.5 s; an alert needs that evidence")
            al = {"box": a["box"], "severity": a["severity"], "reason": a["reason"], "t": round(st.now, 4),
                  "wall": time.time()}
            st.alerts.append(al)
            r = {"alert_id": len(st.alerts), **al}
        elif name == "finish":
            st.finished = True
            r = {"verdict": a["verdict"], "reason": a["reason"]}
        r["now"] = round(st.now, 4)
        return r

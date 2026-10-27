import json
import math
from dataclasses import dataclass, field

TOOLS = {
    "detect_frame": {"seq": "str", "t": "num"},
    "box_spectrum": {"seq": "str", "box": "box", "t0": "num", "t1": "num"},
    "request_window": {"seq": "str", "box": "box", "length_ms": "num"},
    "frequency_map": {"seq": "str", "t0": "num", "t1": "num"},
    "track": {"seq": "str", "box": "box", "t0": "num", "t1": "num"},
    "ask_human": {"seq": "str", "box": "box", "severity": "str", "question": "str"},
    "raise_alert": {"seq": "str", "box": "box", "severity": "str", "reason": "str"},
    "finish": {"verdict": "str", "reason": "str"},
}
SEVERITIES = ("info", "warning", "critical")
VERDICTS = ("drone_alerted", "no_drone")


@dataclass
class Budget:
    max_steps: int = 24
    max_rejections: int = 4
    max_compute_ms: float = 30000.0
    max_events_per_call: int = 6_000_000
    min_window_ms: float = 20.0
    max_window_ms: float = 1000.0
    max_map_ms: float = 300.0
    buffer_s: float = 1.0
    max_alerts: int = 3


@dataclass
class State:
    seq: str
    t_start: float
    t_end: float
    width: int = 1280
    height: int = 720
    now: float = 0.0
    steps: int = 0
    rejections: int = 0
    compute_ms: float = 0.0
    approvals: list = field(default_factory=list)
    alerts: list = field(default_factory=list)
    calls: set = field(default_factory=set)
    finished: bool = False
    unconfirmed: bool = False

    def __post_init__(self):
        if not self.now:
            self.now = self.t_start


class Reject(Exception):
    pass


def _num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise Reject(f"{name} must be a number")
        if not math.isfinite(v):
            raise Reject(f"{name} must be finite")
    return float(v)


def _box(v, st):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise Reject("box must be [x0, y0, x1, y1]")
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise Reject("box must be [x0, y0, x1, y1]")
    x0, y0, x1, y1 = (_num(c, "box") for c in v)
    x0, x1 = max(0.0, x0), min(float(st.width), x1)
    y0, y1 = max(0.0, y0), min(float(st.height), y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        raise Reject("box is empty or outside the frame")
    if (x1 - x0) * (y1 - y0) > 0.25 * st.width * st.height:
        raise Reject("box covers more than a quarter of the frame; use frequency_map for wide search")
    return [int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def check(name, args, st, budget):
    if st.finished:
        raise Reject("episode already finished")
    if st.steps >= budget.max_steps:
        raise Reject(f"step budget {budget.max_steps} spent; call finish")
    if st.compute_ms >= budget.max_compute_ms:
        raise Reject(f"compute budget {budget.max_compute_ms:.0f} ms spent; call finish")
    if name not in TOOLS:
        raise Reject(f"unknown tool {name!r}")
    if not isinstance(args, dict):
        raise Reject("arguments must be an object")
    spec = TOOLS[name]
    extra = set(args) - set(spec)
    if extra:
        raise Reject(f"unexpected arguments {sorted(extra)}")
    missing = [k for k in spec if k not in args]
    if missing:
        raise Reject(f"missing arguments {missing}")
    a = {}
    for k, kind in spec.items():
        v = args[k]
        if kind == "num":
            a[k] = _num(v, k)
        elif kind == "box":
            a[k] = _box(v, st)
        else:
            if not isinstance(v, (str, int)) or isinstance(v, bool):
                raise Reject(f"{k} must be a string")
            a[k] = str(v)[:500]
    if "seq" in a and a["seq"] != st.seq:
        raise Reject(f"sequence {a['seq']} is not the one under watch ({st.seq})")
    lo = st.t_start - budget.buffer_s
    if name == "detect_frame":
        if a["t"] < st.now - budget.buffer_s or a["t"] > st.t_end:
            raise Reject(f"t must be in [{st.now - budget.buffer_s:.3f}, {st.t_end:.3f}]")
    if name in ("box_spectrum", "frequency_map", "track"):
        if name == "track" and a["t1"] > st.t_end + 1e-6:
            raise Reject(f"t1 is past the end of the watch ({st.t_end:.3f})")
        if name != "track" and a["t1"] > st.now + 1e-6:
            raise Reject(f"t1={a['t1']:.3f} is in the future (now={st.now:.3f})")
        if a["t0"] < lo or a["t0"] < st.now - budget.buffer_s - 1e-6:
            raise Reject("t0 is older than the 1 s event buffer")
        ms = (a["t1"] - a["t0"]) * 1000
        cap = budget.max_map_ms if name == "frequency_map" else budget.max_window_ms
        if ms < budget.min_window_ms or ms > cap + 1e-6:
            raise Reject(f"window {ms:.0f} ms outside [{budget.min_window_ms:.0f}, {cap:.0f}] ms")
    if name == "request_window":
        if a["length_ms"] < budget.min_window_ms or a["length_ms"] > budget.max_window_ms:
            raise Reject(f"length_ms outside [{budget.min_window_ms:.0f}, {budget.max_window_ms:.0f}]")
    if name in ("ask_human", "raise_alert") and a["severity"] not in SEVERITIES:
        raise Reject(f"severity must be one of {SEVERITIES}")
    if name == "raise_alert":
        if len(st.alerts) >= budget.max_alerts:
            raise Reject("alert budget spent")
        if a["severity"] == "critical" and not any(ap["approved"] and iou(ap["box"], a["box"]) > 0.3 and ap["now"] >= st.now - 0.5 for ap in st.approvals):
            raise Reject("critical alert needs an approved ask_human on this box first")
    if name == "finish" and a["verdict"] not in VERDICTS:
        raise Reject(f"verdict must be one of {VERDICTS}")
    if name == "finish" and a["verdict"] == "drone_alerted" and not st.alerts:
        raise Reject("verdict drone_alerted without any raised alert")
    key = (name, json.dumps(a, sort_keys=True), round(st.now, 3))
    if key in st.calls:
        raise Reject("identical call already made at this time; change the window, box or time")
    st.calls.add(key)
    return a

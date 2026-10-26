import pytest

from strobe.agent.guard import Budget, Reject, State, check


def st(**kw):
    s = State(seq="111", t_start=25.0, t_end=28.0)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


B = Budget()
BOX = [100, 100, 150, 140]


def test_valid_detect_moves_nothing_itself():
    s = st()
    a = check("detect_frame", {"seq": "111", "t": 25.5}, s, B)
    assert a == {"seq": "111", "t": 25.5}


@pytest.mark.parametrize("name,args,msg", [
    ("teleport", {}, "unknown tool"),
    ("detect_frame", {"seq": "111"}, "missing"),
    ("detect_frame", {"seq": "111", "t": 25.5, "x": 1}, "unexpected"),
    ("detect_frame", {"seq": "999", "t": 25.5}, "not the one under watch"),
    ("detect_frame", {"seq": "111", "t": 99.0}, "t must be in"),
    ("detect_frame", {"seq": "111", "t": "soon"}, "number"),
    ("detect_frame", {"seq": "111", "t": float("nan")}, "finite"),
    ("box_spectrum", {"seq": "111", "box": BOX, "t0": 24.9, "t1": 25.5}, "future"),
    ("box_spectrum", {"seq": "111", "box": BOX, "t0": 24.995, "t1": 25.0}, "outside"),
    ("box_spectrum", {"seq": "111", "box": BOX, "t0": 23.5, "t1": 25.0}, "older than"),
    ("box_spectrum", {"seq": "111", "box": [5, 5, 3, 3], "t0": 24.9, "t1": 25.0}, "empty"),
    ("box_spectrum", {"seq": "111", "box": [0, 0, 1280, 720], "t0": 24.9, "t1": 25.0}, "quarter"),
    ("box_spectrum", {"seq": "111", "box": [1, 2, 3], "t0": 24.9, "t1": 25.0}, "box must be"),
    ("request_window", {"seq": "111", "box": BOX, "length_ms": 5000}, "length_ms outside"),
    ("frequency_map", {"seq": "111", "t0": 24.5, "t1": 25.0}, "outside"),
    ("track", {"seq": "111", "box": BOX, "t0": 25.0, "t1": 29.0}, "past the end"),
    ("raise_alert", {"seq": "111", "box": BOX, "severity": "doom", "reason": "x"}, "severity"),
    ("raise_alert", {"seq": "111", "box": BOX, "severity": "critical", "reason": "x"}, "approved ask_human"),
    ("finish", {"verdict": "maybe", "reason": "x"}, "verdict must be"),
    ("finish", {"verdict": "drone_alerted", "reason": "x"}, "without any raised alert"),
    ("detect_frame", "not a dict", "object"),
])
def test_rejections(name, args, msg):
    with pytest.raises(Reject, match=msg):
        check(name, args, st(), B)


def test_critical_alert_after_approval_on_same_box():
    s = st(approvals=[{"box": [102, 101, 151, 141], "approved": True, "now": 25.0, "severity": "critical"}])
    assert check("raise_alert", {"seq": "111", "box": BOX, "severity": "critical", "reason": "hum"}, s, B)["severity"] == "critical"


def test_critical_alert_refused_when_approval_denied_or_other_box():
    s = st(approvals=[{"box": BOX, "approved": False, "now": 25.0, "severity": "critical"},
                      {"box": [600, 600, 650, 640], "approved": True, "now": 25.0, "severity": "critical"}])
    with pytest.raises(Reject):
        check("raise_alert", {"seq": "111", "box": BOX, "severity": "critical", "reason": "hum"}, s, B)


def test_box_is_clipped_and_string_box_parsed():
    a = check("box_spectrum", {"seq": "111", "box": "[-10, -5, 40, 30]", "t0": 24.9, "t1": 25.0}, st(), B)
    assert a["box"] == [0, 0, 40, 30]


def test_budgets():
    with pytest.raises(Reject, match="step budget"):
        check("detect_frame", {"seq": "111", "t": 25.5}, st(steps=B.max_steps), B)
    with pytest.raises(Reject, match="compute budget"):
        check("detect_frame", {"seq": "111", "t": 25.5}, st(compute_ms=B.max_compute_ms), B)
    with pytest.raises(Reject, match="alert budget"):
        check("raise_alert", {"seq": "111", "box": BOX, "severity": "warning", "reason": "x"}, st(alerts=[{}] * B.max_alerts), B)
    with pytest.raises(Reject, match="finished"):
        check("detect_frame", {"seq": "111", "t": 25.5}, st(finished=True), B)


def test_identical_call_rejected_once_repeated():
    s = st()
    args = {"seq": "111", "box": BOX, "t0": 24.9, "t1": 25.0}
    check("box_spectrum", args, s, B)
    with pytest.raises(Reject, match="identical"):
        check("box_spectrum", dict(args), s, B)


def test_track_may_wait_into_future_within_watch():
    a = check("track", {"seq": "111", "box": BOX, "t0": 25.0, "t1": 25.2}, st(), B)
    assert a["t1"] == 25.2

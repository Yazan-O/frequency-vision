from pathlib import Path

import pytest

from strobe.agent import vision
from strobe.agent.data import Store
from strobe.agent.faults import DownClient, ScriptedClient, TextOnlyClient, slow
from strobe.agent.guard import Budget
from strobe.agent.runner import run_episode

DATA = Path(__file__).resolve().parents[1] / "data" / "fred_slices"
SCN = {"id": "clear_111", "kind": "clear", "seq": "111", "t0": 25.0, "t1": 28.0, "drone": True, "entry": None}
pytestmark = pytest.mark.skipif(not (DATA / "clear_111" / "meta.json").exists(), reason="FRED slices not exported")


@pytest.fixture(scope="module")
def store():
    return Store(DATA)


def kinds(rows):
    return [r["kind"] for r in rows]


def test_bedrock_down_falls_back_to_rule(store, tmp_path):
    s, rows = run_episode(SCN, store, "bedrock", tmp_path / "t.jsonl", Budget(), client=DownClient())
    assert kinds(rows).count("planner_error") == 2 and "fallback" in kinds(rows)
    assert s["planner_final"] == "rule" and s["verdict"] in ("drone_alerted", "no_drone")


def test_malformed_output_falls_back(store, tmp_path):
    s, rows = run_episode(SCN, store, "bedrock", tmp_path / "t.jsonl", Budget(), client=TextOnlyClient())
    errs = [r for r in rows if r["kind"] == "planner_error"]
    assert errs and all(e["error"] == "malformed_output" for e in errs) and s["planner_final"] == "rule"


def test_guard_rejections_are_fed_back_and_bounded(store, tmp_path):
    bad = [("raise_alert", {"seq": "111", "box": [0, 0, 50, 50], "severity": "critical", "reason": "x"}),
           ("box_spectrum", {"seq": "111", "box": [0, 0, 50, 50], "t0": 26.0, "t1": 27.0}),
           ("teleport", {}), ("detect_frame", {"seq": "999", "t": 25.5}), ("finish", {"verdict": "maybe", "reason": "x"}),
           ("detect_frame", {"seq": "111"})]
    s, rows = run_episode(SCN, store, "bedrock", tmp_path / "t.jsonl", Budget(max_rejections=4), client=ScriptedClient(bad))
    rej = [r for r in rows if r["kind"] == "step" and r["guard"].startswith("rejected")]
    assert len(rej) == 5 and "forced_finish" in kinds(rows) and not s["alerts"]


def test_tool_timeout_retried_once(store, tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "box_spectrum", slow(vision.box_spectrum, 1.0, times=1))
    calls = [("box_spectrum", {"seq": "111", "box": [100, 100, 200, 200], "t0": 24.9, "t1": 25.0}),
             ("finish", {"verdict": "no_drone", "reason": "test"})]
    s, rows = run_episode(SCN, store, "bedrock", tmp_path / "t.jsonl", Budget(), timeout_s=0.5, client=ScriptedClient(calls))
    st = [r for r in rows if r["kind"] == "step" and r["tool"] == "box_spectrum"][0]
    assert st["attempts"] == 2 and st["tool_error"] is None and "verdict" in st["result"]


def test_missing_data(store, tmp_path):
    s, rows = run_episode({**SCN, "seq": "404", "id": "missing"}, store, "rule", tmp_path / "t.jsonl")
    assert s["verdict"] == "error_missing_data" and rows[0]["kind"] == "missing_data"


def test_alert_without_hum_evidence_is_refused(store, tmp_path):
    calls = [("raise_alert", {"seq": "111", "box": [100, 100, 150, 150], "severity": "warning", "reason": "looks like a drone"}),
             ("finish", {"verdict": "no_drone", "reason": "test"})]
    s, rows = run_episode(SCN, store, "bedrock", tmp_path / "t.jsonl", Budget(), client=ScriptedClient(calls))
    st = [r for r in rows if r["kind"] == "step" and r["tool"] == "raise_alert"][0]
    assert st["guard"].startswith("rejected: no hum verdict") and not s["alerts"]

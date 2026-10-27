import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import fault_eval as fe
from hertz.agent import vision
from hertz.agent.data import Store

CORRUPT_BUG = "runner.py run_episode catches only KeyError/OSError/ValueError around store.get, so zipfile.BadZipFile and zlib.error escape"


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    d = tmp_path_factory.mktemp("faults")
    return {c["id"]: c for c in fe.case_rows(d)}, d


IDS = ["baseline", "bedrock_down", "bedrock_timeout", "bedrock_no_tool_call", "bedrock_bad_args", "bedrock_bad_args_forever",
       "tool_raises", "tool_hangs", "empty_events", "missing_sequence", "window_too_long", "too_many_steps", "event_flood",
       "alert_no_evidence", "approval_rejected", "approval_rejected_bypass", "approval_timeout", "approval_console_down"]


@pytest.mark.parametrize("cid", IDS)
def test_fault_is_handled(cases, cid):
    cs, d = cases
    r = fe.run_case(cs[cid], d)
    assert r["crash"] is None, r["crash"]
    assert r["alert_raised"] == r["expected_alert"], r
    assert r["outcome"] in r["expected_outcome"], r
    assert r["pass"], r


def test_case_list_is_complete(cases):
    assert set(cases[0]) == set(IDS) | {"corrupt_truncated", "corrupt_bitflip"}


@pytest.mark.parametrize("cid", ["corrupt_truncated", "corrupt_bitflip"])
def test_corrupt_event_file_never_alerts(cases, cid):
    cs, d = cases
    assert fe.run_case(cs[cid], d)["alert_raised"] is False


@pytest.mark.xfail(reason=CORRUPT_BUG, strict=False)
@pytest.mark.parametrize("cid", ["corrupt_truncated", "corrupt_bitflip"])
def test_corrupt_event_file_ends_as_missing_data(cases, cid):
    cs, d = cases
    r = fe.run_case(cs[cid], d)
    assert r["crash"] is None and r["outcome"] == "error_missing_data", r


def test_mcp_bad_arguments(tmp_path):
    pytest.importorskip("mcp")
    r = fe.mcp_bad_args(tmp_path)
    assert r["crash"] is None, r["crash"]
    assert r["pass"], json.dumps(r["mcp_calls"], indent=1)[:2000]


async def _e2e(trace):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = {**os.environ, "HERTZ_DATA": str(fe.DATA), "HERTZ_MCP_TRACE": str(trace), "PYTHONPATH": str(ROOT)}
    p = StdioServerParameters(command=sys.executable, args=["-m", "hertz.agent.mcp_server"], env=env, cwd=str(ROOT))
    with open(os.devnull, "w") as quiet:
        async with stdio_client(p, errlog=quiet) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = sorted(t.name for t in (await s.list_tools()).tools)
                start = fe._mcp_text(await s.call_tool("start_watch", {"seq": "210", "t_start": 20.0, "t_end": 20.6}))
                det = fe._mcp_text(await s.call_tool("detect_frame", {"seq": "210", "t": 20.1}))
                box = det["detections"][0]["box"]
                spec = fe._mcp_text(await s.call_tool("box_spectrum", {"seq": "210", "box": box, "t0": 20.0, "t1": 20.1}))
                return tools, start, det, box, spec


def test_mcp_end_to_end_on_real_data(tmp_path):
    pytest.importorskip("mcp")
    tools, start, det, box, spec = asyncio.run(_e2e(tmp_path / "mcp.jsonl"))
    assert tools == sorted(["start_watch", "detect_frame", "box_spectrum", "request_window", "frequency_map", "track",
                            "ask_human", "raise_alert", "finish"])
    assert start["seq"] == "210" and start["now"] == 20.0
    assert det["n_candidates"] >= 1 and det["now"] == 20.1
    assert spec["verdict"] in ("hum", "ambiguous", "none") and spec["n_events"] > 0 and spec["box"] == box
    local = vision.box_spectrum(Store(fe.DATA).get("210"), box, 20.0, 20.1)
    assert (spec["peak_hz"], spec["snr"], spec["n_events"], spec["verdict"]) == (local["peak_hz"], local["snr"], local["n_events"], local["verdict"])
    rows = [json.loads(l) for l in (tmp_path / "mcp.jsonl").read_text().splitlines()]
    assert [r["tool"] for r in rows] == ["detect_frame", "box_spectrum"]

# Strobe

Strobe confirms drones by their propeller hum: an OpenCV 5 detector proposes a box, the event camera inside that box shows a 200 to 750 Hz blade-pass peak that 30 fps video cannot see, and an agent on AWS Graviton4 with COOL decides the next look, the alert, or the question to a human.

**On the full FRED test split, the hum check cuts the detector's false alarms by 25% at the same recall, and the hum frequencies it measures match an independent published estimate (DJI Mini 2: 320 Hz vs 316 Hz).**

- Live endpoint: https://100-27-6-111.sslip.io (no login), served by COOL on Graviton4
- Technical report: [`docs/REPORT.md`](docs/REPORT.md)
- Architecture: [`docs/architecture.svg`](docs/architecture.svg) · Agent loop: [`docs/agent_workflow.svg`](docs/agent_workflow.svg)
- Video: [X] <!-- fill with the video URL -->

![Architecture](docs/architecture.png)

## Try it in 90 seconds

1. Open https://100-27-6-111.sslip.io. Each slide has a one-line headline. Slide 1 plays a real FRED clip of a DJI Mini 2: at 30 fps the propellers are a blur.
2. Use the clip picker to switch drones: DJI Mini 2 (321 Hz), DJI Tello EDU (565 Hz), DarwinFPV Cineape20 (a hard case with no clean peak) and DJI Mini 3 (211 Hz, next to a flickering patch).
3. Slide 2 shows the drone as raw events in x, y and time, with a no-drone patch beside it.
4. Slide 3 computes the spectrum live on the server with COOL's OpenCV 5 (`calcHist` + `dft`). The drone box peaks at the blade-pass frequency; the no-drone box stays flat.
5. Slide 5 replays the agent on a real FRED sequence, including the human approval step. Press approve or reject; the server records your answer and triggers nothing external.
6. Slide 6 shows the measured results.

The same check from a terminal:

```bash
curl -s https://100-27-6-111.sslip.io/version
curl -s -X POST https://100-27-6-111.sslip.io/api/spectrum \
  -H 'content-type: application/json' \
  -d '{"clip":"clear_210","box":[226,324,320,376],"t":20.5,"window_ms":100}'
```

`/version` reports `"cool": true`, OpenCV `5.1.0-dev` loaded from `/opt/cool`, `aarch64` and the KleidiCV 0.7.0 HAL. The spectrum call returns the Mini 2's peak: on 2026-10-26 it gave 314.3 Hz with a score of 3,013 from 3,781 events, computed in 1.6 ms on the Graviton4 `c8g.medium`.

Clip frequencies: `app/static/data/clips.json`.

## Measured on FRED (real event + RGB drone recordings)

| Result | Number | Source |
|---|---|---|
| False alarms per minute, RGB detector alone vs RGB + hum (47 test sequences, every frame, 84.3 min) | **412.7 vs 308.4 (−25%)**, recall 0.544 vs 0.544, precision 0.670 vs 0.731, mAP@0.5 0.505 vs 0.516 | `results/detector/results_test.json` |
| False detections removed by the hum check | 8,790 of 34,796, while losing 26 of 70,794 true detections | same |
| Blade-pass medians, Strobe vs published PropPulse estimate | DJI Mini 2 320 vs 316 Hz, DJI Tello 564 vs 539 Hz, DJI Mini 3 245 vs 223 Hz | `results/engine/per_model_youden.json` |
| Hum score, drone box vs random background, AUC (26,911 vs 26,909 test boxes) | 0.917 | `results/engine/summary.json` |
| COOL vs pip OpenCV 5, same Graviton4 host, 4 threads | GaussianBlur 1.89x, dft 1.54x, connectedComponentsWithStats 1.17x faster; resize 0.87x, DNN 0.92x | `bench/results/cool-graviton4-c8g.xlarge.json`, `bench/results/pip-graviton4-c8g.xlarge-samehost.json` |
| Agent, 8 pre-registered FRED scenarios, clean run | Bedrock planner 4 of 8, 0 false alerts, 30% fewer steps than the rule planner (also 4 of 8); fixed schedule 3 of 8. Approval is SIMULATED in the evaluation | `results/agent/eval_v3/results.json` |

Every number, its denominator and its source file are in [`docs/REPORT.md`](docs/REPORT.md).

## Run locally

Python 3.12 or 3.13. All dependencies are pinned; locally Strobe uses pip OpenCV 5.0.0.

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8080
```

Open http://127.0.0.1:8080. The demo clips ship in `app/data` and `app/static/data`, so no download is needed.

## Tests

```bash
pytest -q
python tools/int64_repro.py
```

`pytest -q` runs 39 tests: the hum engine, the endpoint, the agent guard, and injected planner and tool failures. CI runs them on x86 and Arm (`.github/workflows/ci.yml`). `tools/int64_repro.py` reproduces the OpenCV 5.0.0 int64 truncation we found ([`docs/UPSTREAM_ISSUE_int64.md`](docs/UPSTREAM_ISSUE_int64.md)).

The agent runs offline with the deterministic planners:

```bash
pip install -r strobe/agent/requirements.txt
python eval/agent_eval.py --planners rule,fixed --out runs/agent
```

This needs the FRED event slices from `eval/export_fred_slices.py`. The Bedrock planner (`--planners bedrock`) needs AWS credentials with Bedrock access in us-east-1.

## Deploy on AWS

See [`deploy/README.md`](deploy/README.md). The live endpoint runs on COOL:

```bash
python deploy/aws.py cool
python deploy/aws.py cool-bench
```

`cool` launches or updates a Graviton4 instance from the COOL Marketplace AMI and serves the app from COOL's OpenCV. `cool-bench` measures COOL against pip OpenCV 5 on the same instance.

## Reproduce the evaluation and benchmarks

- Hum engine on FRED: `strobe/fred_claim.py`, then `strobe/fred_claim_report.py` (report §8.2, results in `results/engine/`).
- Known-frequency check: `strobe/known_freq.py` (EEPPR is GPL-3.0 and is downloaded at run time, never committed).
- Detector training and full pipeline: `eval/train_detector/`, `eval/check_onnx.py`, `eval/get_fred_eval_data.sh`, `eval/run_eval.py`, `eval/event_only.py` (report §8.3, results in `results/detector/`).
- Agent: `eval/export_fred_slices.py`, `eval/agent_eval.py`, scenarios fixed in `eval/scenarios.json` (report §8.4, results and traces in `results/agent/`).
- Benchmarks: `python deploy/aws.py cool-bench`, `python deploy/aws.py bench ...`, `bench/table.py`, `bench/compare.py`; results in `bench/results/` (report §6).

Full commands are in report §12.

## Licence

Apache-2.0, see [`LICENSE`](LICENSE). Third-party code, models and data and their licences are listed in [`THIRD_PARTY.md`](THIRD_PARTY.md). FRED is used under Apache-2.0 per its Hugging Face card. The detector was trained with Ultralytics (AGPL-3.0) in a separate training environment; Strobe's runtime uses only OpenCV.

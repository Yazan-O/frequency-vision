# Frequency Vision: Devpost write-up

**Video:** https://youtu.be/KSkdlCEsu84 · **Repo:** https://github.com/Yazan-O/frequency-vision · **Live:** https://100-27-6-111.sslip.io

**Tagline:** A bird and a drone look the same at 30 fps. A drone hums at its blade-pass frequency; a bird does not.

**Name:** Frequency Vision: it sees the frequencies a camera cannot.

**One line:** Frequency Vision confirms drones by their propeller hum. An OpenCV 5 detector proposes a box, the event camera inside that box shows the blade-pass frequency, and an agent decides what to look at next.

- **The drone hums, a bird does not.** A propeller passes hundreds of times a second; a 30 fps camera cannot see it, an event camera can.
- **−25% false alarms at the same recall** on 84 minutes of real drone video (FRED test split), losing 26 of 70,794 true detections. A stricter threshold reaches precision 0.815.
- **An agent on Amazon Bedrock whose decisions come from OpenCV 5 vision.** Blind its spectrum and it falls from 12 to 6 of 24 scenarios and finds 0 of 18 drones.
- **Live on COOL on AWS Graviton4, verifiable in one click:** https://100-27-6-111.sslip.io/api/cool, or the **Verify COOL live** button on slide 6.

## The stakes

In December 2018, reported drone sightings at Gatwick closed the runway for about 33 hours. About 1,000 flights were cancelled and about 140,000 passengers were affected. In the US, the FAA receives more than 100 reports of drones near airports each month (FAA UAS sightings report page, faa.gov/uas/resources/public_records/uas_sightings_report).

The hard part is not seeing the dot. It is knowing what the dot is. At 30 frames per second a far drone is a few pixels, and its propellers are invisible: they pass the camera's view hundreds of times a second, far faster than the 15 Hz a 30 fps camera can represent. A bird has no rotor. A drone always does.

An event camera records every pixel's brightness change with microsecond timing. A spinning propeller writes its rhythm straight into that stream. Frequency Vision reads it.

## Try it in 90 seconds

Live, no login, served by COOL on Graviton4: **https://100-27-6-111.sslip.io**

1. Slide 1: a real FRED recording of a DJI Mini 2 at 30 fps. The rotor is a blur. Every slide states its point in one headline.
2. Pick a clip. The demo clip on the page gives its own median over its 100 ms windows: DJI Mini 2 316 Hz (sequence 202), DJI Tello EDU 584.8 Hz (sequence 230), DJI Mini 3 247.4 Hz (sequence 93) and DarwinFPV Cineape20 (GER) 225.2 Hz (sequence 64). The default event window is 100 ms, the best setting on the FRED test split. The engine medians over all FRED test sequences of each model, a different population, are 320 Hz for the Mini 2 (median over all Mini 2 test sequences; 316 Hz is the demo clip), 564 Hz (Tello EDU) and 245 Hz (Mini 3).
3. Slide 2: the same drone as raw events in x, y and time, beside a patch with no drone.
4. Slide 3: the server computes the spectrum live with COOL's OpenCV 5. The drone box peaks at its blade-pass frequency. The empty box stays flat.
5. Slide 4: why 30 fps misses the hum (a 316 Hz propeller folds down to 14 Hz) and how the spike is scored: the windowed signal, `cv.dft`, the score against the local floor, and the window length, all computed live.
6. Slide 5: the agent. Play replays a real evaluation trace. **Run agent live** runs Claude Sonnet 4.6 on Amazon Bedrock on the server now, on the clip you picked, against the live OpenCV 5 tools. It asks you before a critical alert and waits 60 s; with no answer the run ends unconfirmed, waiting for an operator, and no alert is raised. The page names the planner that ran (the fixed-rule planner takes over after 15 Bedrock runs a UTC day or on a Bedrock error) and shows the clip's expected frequency and the IoU of the agent's box with the FRED ground-truth box.
7. Slide 6: the measured results: false alarms with and without the hum check, COOL vs pip on one Graviton4 host, Graviton4 vs x86, and each drone's pitch.

Or from a terminal:

```bash
curl -s https://100-27-6-111.sslip.io/version
curl -s -X POST https://100-27-6-111.sslip.io/api/spectrum \
  -H 'content-type: application/json' \
  -d '{"clip":"clear_mini2_seq202","box":[791,469,917,504],"t":1.767,"window_ms":100}'
```

`/version` shows `"cool": true` and OpenCV 5.1.0-dev with KleidiCV 0.7.0 from `/opt/cool`. On 2026-10-26 the spectrum call returned the DJI Mini 2's peak at 315.9 Hz with a score of 26,655 from 38,845 events, computed in 4.6 ms on a Graviton4 `c8g.medium`.

## How Frequency Vision meets the judging criteria

Frequency Vision enters the overall awards and both featured paths: Best Use of COOL and Agentic Vision. Each rubric line below points to its evidence. The same map is machine-readable at `/api/summary` (https://100-27-6-111.sslip.io/api/summary) under `judging`.

**Overall rubric**

| Criterion (weight) | Evidence | Where |
|---|---|---|
| Technical execution (30%) | OpenCV 5 hum engine (`calcHist`, `dft`, `connectedComponentsWithStats`, `dnn` `ENGINE_NEW`, `KalmanFilter`) on all 47 FRED test sequences: false alarms **412.7 → 308.4 per minute (−25%) at the same recall 0.544**; hum-score AUC 0.917 vs a random patch, 0.758 vs the busiest patch. An OpenCV 5.0.0 int64 defect found and written up for upstream. | `results/detector/results_test.json`, `results/engine/summary.json`, `docs/REPORT.md` §8, `docs/UPSTREAM_ISSUE_int64.md` |
| Innovation (20%) | The RGB detector proposes. The event camera confirms each box by the propeller's blade-pass frequency, which 30 fps cannot see. An agent picks the next measurement. | Live page slides 1 to 3, `docs/REPORT.md` §13 |
| Real-world impact (20%) | 8,790 of 34,796 false detections removed while 26 of 70,794 true detections are lost. High-precision setting: precision 0.815. | `results/detector/results_test.json`, `docs/REPORT.md` §1 and §2 |
| User experience (10%) | Six-slide live page: clip picker, detector run live, spectrum computed live, 3D event cloud, and an agent run live that waits for your Approve or Reject. Keyboard navigation, screen-reader text and a phone layout. | Live page (https://100-27-6-111.sslip.io), `app/static/` |
| Documentation and presentation (10%) | The README, the technical report, architecture and agent diagrams, figures redrawn from result files, and the video. | `docs/REPORT.md`, `docs/architecture.svg`, `docs/agent_workflow.svg` |
| Cloud delivery, reproducibility, responsible operation (10%) | Always-on COOL endpoint on Graviton4 behind HTTPS, deployed by one script, `/health` and `/version`, rate limits, no SSH, human approval enforced in code. | `deploy/aws.py`, `deploy/README.md`, `docs/REPORT.md` §5 and §11 |

**Best Use of COOL**

| Criterion (weight) | Evidence | Where |
|---|---|---|
| Verified COOL integration on Graviton (30%) | The live endpoint loads `cv2` from `/opt/cool`: OpenCV 5.1.0-dev, `aarch64`, KleidiCV HAL. Proof file with instance type, AMI and Marketplace product code. | `/version` (https://100-27-6-111.sslip.io/version), `bench/results/cool-proof-c8g.xlarge.json` |
| Architecture and technical quality (25%) | COOL serves the page, the hum engine, the detector and the agent tools on one Graviton4 host. Benchmark hosts are separate. | `docs/architecture.svg`, `docs/REPORT.md` §6 |
| Measured value (20%) | Same Graviton4 host, COOL vs pip OpenCV 5: GaussianBlur **1.89x**, `dft` **1.54x**, connected components **1.17x** faster. Frequency map 1.13x faster end to end, outputs identical. | `bench/results/cool-graviton4-c8g.xlarge.json`, `pip-graviton4-c8g.xlarge-samehost.json`, `bench/results/E2E.md` |
| Innovation (15%) | COOL runs signal processing on event-camera time series: a 10 kHz `dft` per box and a per-pixel frequency map with `DFT_ROWS`. | `hertz/freq.py` |
| Reproducibility and demonstration (10%) | `python deploy/aws.py cool` deploys the endpoint. `python deploy/aws.py cool-bench` reruns the same-host benchmark. | `deploy/README.md`, `bench/` |

**Agentic Vision**

| Criterion (weight) | Evidence | Where |
|---|---|---|
| OpenCV 5 and agent integration (30%) | Every agent tool is an OpenCV 5 call. In trace `late_142` the detector finds nothing, the frequency map finds a 545 Hz spot, and the agent confirms the drone. | `hertz/agent/`, `results/agent/eval_v3/traces/bedrock_late_142.jsonl` |
| Orchestration and autonomy (25%) | Vision drives the decisions. Blind the OpenCV spectrum and Bedrock falls from 12 to 6 of 24, finding 0 of 18 drones. With the same history, a blinded result changes its next action at 39 of 130 vision steps (30%), a shuffled result at 53 of 130 (41%), and after a hum at 10 of 10. A guard checks every call against its schema, the clock and the budgets. | `results/agent/eval_v4/vision_ablation.json`, `results/agent/eval_v4/SUMMARY.json`, `hertz/agent/guard.py` |
| Task effectiveness and evaluation (20%) | 24 FRED scenarios, 16 of them held out and never used for any fix: Bedrock **12 of 24 with 0 false alerts**, against 10 (1 false alert) for the rule planner and 9 for a fixed schedule. On the held-out 16: 8 vs 6 vs 6. | `results/agent/eval_v4/results.json`, `eval/scenarios.json` |
| Failure handling, observability, security, human control (15%) | Critical alerts need a human's approval, enforced by the guard: operator approve, reject and timeout each held in 6 of 6 Bedrock episodes (operator scripted in the evaluation). This test found one guard gap, now fixed: after a Reject, every alert is blocked until a later approval. 21 injected faults (planner, tools, data, budgets, operator, MCP): **21 of 21 handled, 0 unsafe alerts**. Every step is logged as a JSON line. | `results/agent/faults/TABLE.md`, `tests/`, `hertz/agent/guard.py` |
| User experience, documentation, demonstration (10%) | Slide 5 replays real traces and runs the agent live on the server with your Approve or Reject. | Live page slide 5, `docs/agent_workflow.svg` |

**Submission requirements**

| Requirement | Where it is met |
|---|---|
| OpenCV 5 for substantive image or video analysis | `hertz/freq.py`, `hertz/detect.py`, `/version` (https://100-27-6-111.sslip.io/version) |
| A meaningful component on AWS | COOL on Graviton4 `c8g.medium` serves the live page and the engine; Amazon Bedrock plans the agent |
| Working web endpoint | 100-27-6-111.sslip.io (https://100-27-6-111.sslip.io) |
| Video, five minutes or less | Video link at the top of this write-up |
| Technical report | `docs/REPORT.md` |
| Repository with pinned dependencies and build, deploy and test steps | `requirements.txt`, `requirements-dev.txt`, `docs/REPORT.md` §12, `deploy/README.md` |
| Architecture diagram with OpenCV 5, AWS, COOL and agent parts | `docs/architecture.svg`, `docs/agent_workflow.svg` |
| Evaluation with failure cases | `docs/REPORT.md` §8 and §9 |
| Rights to data, models and media | FRED under Apache-2.0, detector weights not distributed, `THIRD_PARTY.md` |

## What it does

1. **Propose.** A drone detector (YOLOv8n fine-tuned on FRED) runs in the OpenCV 5 DNN engine and proposes boxes in the 30 fps RGB frame.
2. **Confirm.** Inside each box, Frequency Vision turns the events of the last 100 ms into a 10 kHz signal (brighter-minus-darker counts), takes its spectrum with `cv.dft`, and scores the strongest peak between 150 and 1,000 Hz against its local floor.
3. **Decide.** An agent on Amazon Bedrock reads the result and picks the next action: re-check with a longer or tighter window, map frequencies across the whole frame, follow the box with a Kalman filter, ask a human, or raise an alert.
4. **Guard.** Every agent action passes a deterministic guard: valid arguments, no peeking into the future, budgets on steps and compute, and an evidence rule: no alert without a hum on that box in the last 1.5 seconds. A critical alert also needs a human's approval on the same box.
5. **Record.** Every step is logged as one line of JSON and stored in S3, with logs in CloudWatch.

What it does **not** do: it never jams, intercepts or chases anything. It confirms and alerts, and a human approves the serious alerts.

## How it uses OpenCV 5, COOL and AWS

**OpenCV 5 does all the image and event work:**

- Detector: `cv.dnn.readNetFromONNX` with the new graph engine `cv.dnn.ENGINE_NEW`, `blobFromImageWithParams` letterbox, `NMSBoxes`. The ONNX model in OpenCV 5.0.0 matches PyTorch to 4.6e-4.
- Events to signal: `cv.calcHist` on relative microsecond times, `cv.subtract` for brighter-minus-darker.
- Spectrum: `cv.createHanningWindow`, `cv.getOptimalDFTSize`, `cv.copyMakeBorder`, `cv.dft`, `cv.magnitude`, `cv.minMaxLoc`.
- Whole-frame frequency map: one `cv.dft(DFT_ROWS)` call computes up to 20,000 per-pixel spectra at once.
- Rotor mask inside a box: 2-D `calcHist`, `GaussianBlur`, Otsu `threshold`, `connectedComponentsWithStats`.
- Tracking: `cv.KalmanFilter` on event centroids from `cv.moments`.
- Build proof: `cv.getBuildInformation` on `/version`, so anyone can see which OpenCV build and HAL served the request.

**We found and documented an OpenCV 5.0.0 defect:** the Python binding silently cuts NumPy int64 arrays to their low 32 bits. Microsecond timestamps break without any error: `cv.minMaxLoc` on `[1.7e15, 5e12]` returns `(404635649, 658067456)`. Repro: `tools/int64_repro.py`. Frequency Vision works around it with relative int32 times, and we wrote an upstream issue draft.

**COOL runs the live demo.** The endpoint is a Graviton4 `c8g.medium` launched from the COOL Graviton4 AMI; the app imports COOL's OpenCV 5.1.0-dev with the KleidiCV 0.7.0 HAL from `/opt/cool`, and `/version` proves it on every call. On the same `c8g.xlarge` host, COOL speeds up the event engine's own operations over pip OpenCV 5: GaussianBlur 1.89x, `dft` 1.54x and `connectedComponentsWithStats` 1.17x at 4 threads, and the event frequency map 1.13x. Resize (0.87x) and the DNN forward pass (0.92x) are slower on this COOL build, so the full confirm step (detector, hum checks and frequency map on 210 FRED windows) is 7% slower under COOL: p50 106.2 vs 98.9 ms per window, with identical boxes, scores, hum peaks and verdicts. COOL ships 5.1.0-dev and PyPI has no 5.1 wheel, so the comparison mixes the build with the version. The live `POST /api/detect` runs the detector through `cv.dnn` on COOL in about 403 ms on 1 vCPU. In the single-op test, COOL's outputs differ slightly from pip's: at most one grey level on 0.005% of pixels for blur, resize and color conversion, and a different label for at least one connected component. All of it is in `bench/results/`.

**AWS:** EC2 Graviton4 with the COOL AMI behind Caddy HTTPS, systemd and a health timer; SSM Session Manager instead of SSH; a least-privilege IAM role; S3 for bundles, benchmarks and traces; CloudWatch logs, metrics and an auto-recover alarm; Amazon Bedrock (Claude Sonnet 4.6) as the planner; an AWS Budget alert. `c8g.xlarge` and `c7i.xlarge` instances were launched only for benchmarks. With pip OpenCV 5 on both, Graviton4 beat x86 on 5 of 6 operations, up to 2.07x (cvtColor).

**Agent and MCP:** the eight tools (five of them OpenCV 5 vision tools) are exposed both to the Bedrock planner and as an MCP server, so any MCP client can drive the same guarded tools.

## Measured results on real data

All numbers are on FRED, a public dataset of real event-camera and RGB drone recordings (Apache-2.0). Every rule and threshold was chosen on training sequences and reported on the 47 test sequences.

- **25% fewer false alarms, same recall.** On every frame of the 47 test sequences (151,768 frames, 84.3 minutes), the detector alone raises 412.7 false alarms per minute. Keeping only boxes whose events hum cuts that to 308.4. It removes 8,790 of 34,796 false detections and only 26 of 70,794 true ones: recall stays at 0.544, precision rises from 0.670 to 0.731 and mAP@0.5 from 0.505 to 0.516. A stricter hum threshold (score ≥ 98) gives precision 0.815 at recall 0.146, with 51.2 false alarms per minute.
- **The frequencies are physically right.** Frequency Vision's median blade-pass frequency per drone model matches the independent PropPulse estimates on the same data: DJI Mini 2 320 Hz (median over all Mini 2 test sequences, 1,951 boxes; the demo clip gives 316 Hz) vs PropPulse 316 Hz, DJI Tello 564 Hz vs 539 Hz (11,068 boxes), DJI Mini 3 245 Hz vs 223 Hz (2,405 boxes). For the DJI Mini 2, 99.2% of test boxes hum above the train-chosen threshold.
- **The hum separates drones from background.** AUC 0.917 for drone boxes against random same-size patches (26,911 vs 26,909 boxes).
- **The agent finds what the detector missed.** In FRED sequence 142 the detector proposed nothing for three frames. The agent mapped frequencies across the whole frame, found one spot humming at 545 Hz, confirmed a hum at 542.6 Hz, tracked it, asked for approval and raised the alert. The ground truth is a DJI Tello EDU, whose median hum over the test split is 564 Hz.
- **The agent beats hand-tuned rules, behind a human gate.** On 24 FRED scenarios, 16 of them held out, the Bedrock planner solved 12 with 0 false alerts; the hand-written rule planner solved 10 with 1 false alert and a fixed schedule 9. On the held-out 16: 8 vs 6 vs 6.
- **Its decisions come from the vision.** Blind the OpenCV spectrum and Bedrock falls to 6 of 24 and finds 0 of 18 drones. Replayed with the same history, a blinded result changes its next action at 39 of 130 vision steps, a shuffled one at 53 of 130, and after a hum at 10 of 10.
- **Human control holds.** Operator approve, reject and timeout each held in 6 of 6 Bedrock episodes; the operator is scripted in the evaluation and labelled SIMULATED in every trace. This test found one guard gap, now fixed: after a Reject, every alert is blocked until a later approval. 21 of 21 injected faults were handled with 0 unsafe alerts.

## A known failure: flickering lights hum too

Screens and lamps driven by mains power flicker at multiples of 100 Hz, and the event camera sees that flicker as clearly as a propeller. On the training sequences, 35% of the 2,806 strong false peaks on busy non-drone patches sat on multiples of 100 Hz. The clearest case is a phone screen in FRED sequence 212. Most of the rest sat at 300 to 350 Hz in sequences 211 to 216, right in the DJI Mini 2 band.

Our fix: a notch at multiples of 100 Hz cut false alarms on the busiest patch from 4.3% to 2.6% at the strict threshold. The agent also has a whole-frame frequency map: if one frequency fills the whole scene, it is lighting, not a rotor. Flicker still causes false peaks, and the hum alone is a weak detector (event-only AP 0.066). That is why Frequency Vision uses the hum to confirm what the detector proposes, and lets the agent gather more evidence before it alerts.

## What's next: a pilot

1. **Site.** One small airfield or prison yard with an existing camera mast. Add one off-the-shelf event camera beside the RGB camera.
2. **Four weeks of shadow mode.** Frequency Vision runs next to the current process and alerts nobody. Every operator drone report is matched against Frequency Vision's trace.
3. **Measure.** False drone alarms per day with and without the hum check, and the time from first detection to a confirmed or dismissed verdict.
4. **Hand over.** If the false alarms drop as they did on FRED, turn on the approval step for the operators, with the same guard and audit trail.
5. **Scale on COOL.** One Graviton4 instance with COOL per site, sized from the benchmark.

## Built with

opencv-5, opencv-dnn, cool, kleidicv, aws, amazon-ec2, aws-graviton, amazon-bedrock, claude, amazon-s3, amazon-cloudwatch, aws-ssm, aws-iam, aws-budgets, python, numpy, fastapi, uvicorn, caddy, mcp, onnx, yolov8, ultralytics, prophesee, event-camera, fred-dataset, kalman-filter, pytest, github-actions

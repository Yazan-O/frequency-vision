# Frequency Vision: Devpost write-up

**Video:** [VIDEO_URL] · **Repo:** [REPO_URL] · **Live:** https://100-27-6-111.sslip.io

**Tagline:** A bird and a drone look the same at 30 fps. A drone hums at its blade-pass frequency; a bird does not.

**Name:** Frequency Vision: it sees the frequencies a camera cannot.

**One line:** Frequency Vision confirms drones by their propeller hum. An OpenCV 5 detector proposes a box, the event camera inside that box shows the blade-pass frequency, and an agent running on COOL on AWS Graviton4 decides what to look at next. On 84 minutes of real drone video the hum check removes 25% of the detector's false alarms at the same recall, losing 26 of 70,794 true detections. A stricter hum threshold (score ≥ 98) reaches precision 0.815.

## The stakes

In December 2018, reported drone sightings at Gatwick closed the runway for about 33 hours. About 1,000 flights were cancelled and about 140,000 passengers were affected. In the US, the FAA receives more than 100 reports of drones near airports every month.

The hard part is not seeing the dot. It is knowing what the dot is. At 30 frames per second a far drone is a few pixels, and its propellers are invisible: they pass the camera's view hundreds of times a second, far faster than the 15 Hz a 30 fps camera can represent. A bird has no rotor. A drone always does.

An event camera records every pixel's brightness change with microsecond timing. A spinning propeller writes its rhythm straight into that stream. Frequency Vision reads it.

## Try it in 90 seconds

Live, no login, served by COOL on Graviton4: **https://100-27-6-111.sslip.io**

1. Slide 1: a real FRED recording of a DJI Mini 2 at 30 fps. The rotor is a blur. Every slide states its point in one headline.
2. Pick a clip. The demo clip on the page gives its own median over its 100 ms windows: DJI Mini 2 316 Hz (sequence 202), DJI Tello EDU 555.8 Hz (sequence 195), DJI Mini 3 247.4 Hz (sequence 93) and DarwinFPV cineape20ger 225.2 Hz (sequence 64). A DarwinFPV Cineape20 (sequence 20) shows no clean peak in any of its 50 windows: our hard case. The engine medians over all test boxes, a different population, are 320 Hz (Mini 2, median over all test boxes), 564 Hz (Tello EDU) and 245 Hz (Mini 3).
3. Slide 2: the same drone as raw events in x, y and time, beside a patch with no drone.
4. Slide 3: the server computes the spectrum live with COOL's OpenCV 5. The drone box peaks at its blade-pass frequency. The empty box stays flat.
5. Slide 5: a recorded replay of the agent's real evaluation traces on FRED sequences. Approve or Reject records your decision on the server and triggers nothing else.
6. Slide 6: the measured results.

Or from a terminal:

```bash
curl -s https://100-27-6-111.sslip.io/version
curl -s -X POST https://100-27-6-111.sslip.io/api/spectrum \
  -H 'content-type: application/json' \
  -d '{"clip":"clear_mini2_seq202","box":[791,469,917,504],"t":1.767,"window_ms":100}'
```

`/version` shows `"cool": true` and OpenCV 5.1.0-dev with KleidiCV 0.7.0 from `/opt/cool`. On 2026-10-26 the spectrum call returned the DJI Mini 2's peak at 315.9 Hz with a score of 26,655 from 38,845 events, computed in 4.6 ms on a Graviton4 `c8g.medium`.

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
- **The frequencies are physically right.** Frequency Vision's median blade-pass frequency per drone model matches the independent PropPulse estimates on the same data: DJI Mini 2 320 Hz (median over all 1,951 test boxes) vs 316 Hz, DJI Tello 564 Hz vs 539 Hz (11,068 boxes), DJI Mini 3 245 Hz vs 223 Hz (2,405 boxes). For the DJI Mini 2, 99.2% of test boxes hum above the train-chosen threshold.
- **The hum separates drones from background.** AUC 0.917 for drone boxes against random same-size patches (26,911 vs 26,909 boxes).
- **The agent finds what the detector missed.** In FRED sequence 142 the detector proposed nothing for three frames. The agent mapped frequencies across the whole frame, found one spot humming at 545 Hz, confirmed a hum at 542.6 Hz, tracked it, asked for approval and raised the alert. The ground truth is a DJI Tello EDU, whose median hum over the test split is 564 Hz.
- **The agent matches hand-tuned rules with fewer calls, behind a human gate.** On 8 FRED scenarios fixed before any run, the Bedrock planner solved 4 of 8 with 0 false alerts, the same score as a hand-written rule planner (4 of 8, 0 false alerts), using 30% fewer tool calls (12.25 vs 17.38 per episode); a fixed schedule solved 3 of 8. Every critical alert waits for a human approval. In this evaluation that approval is a SIMULATED automatic operator, labelled so in every trace. Two earlier development runs on the same scenarios are kept in `results/agent/dev_runs/`.

## One honest failure: flickering lights hum too

Screens and lamps driven by mains power flicker at multiples of 100 Hz, and the event camera sees that flicker as clearly as a propeller. On the training sequences, 35% of the 2,806 strong false peaks on busy non-drone patches sat on multiples of 100 Hz. The clearest case is a phone screen in FRED sequence 212. Most of the rest sat at 300 to 350 Hz in sequences 211 to 216, right in the DJI Mini 2 band.

What we did: a notch at multiples of 100 Hz cut false alarms on the busiest patch from 4.3% to 2.6% at the strict threshold. The agent also has a whole-frame frequency map: if one frequency fills the whole scene, it is lighting, not a rotor. Flicker still causes false peaks, and the hum alone is a weak detector (event-only AP 0.066). That is why Frequency Vision uses the hum to confirm what the detector proposes, and lets the agent gather more evidence before it alerts.

## What's next: a pilot

1. **Site.** One small airfield or prison yard with an existing camera mast. Add one off-the-shelf event camera beside the RGB camera.
2. **Four weeks of shadow mode.** Frequency Vision runs next to the current process and alerts nobody. Every operator drone report is matched against Frequency Vision's trace.
3. **Measure.** False drone alarms per day with and without the hum check, and the time from first detection to a confirmed or dismissed verdict.
4. **Hand over.** If the false alarms drop as they did on FRED, turn on the approval step for the operators, with the same guard and audit trail.
5. **Scale on COOL.** One Graviton4 instance with COOL per site, sized from the benchmark.

## Built with

opencv-5, opencv-dnn, cool, kleidicv, aws, amazon-ec2, aws-graviton, amazon-bedrock, claude, amazon-s3, amazon-cloudwatch, aws-ssm, aws-iam, aws-budgets, python, numpy, fastapi, uvicorn, caddy, mcp, onnx, yolov8, ultralytics, prophesee, event-camera, fred-dataset, kalman-filter, pytest, github-actions

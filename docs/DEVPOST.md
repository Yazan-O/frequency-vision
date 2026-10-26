# Strobe: Devpost write-up

**Tagline:** A bird and a drone look the same at 30 fps. Only one of them hums at 320 Hz.

**One line:** Strobe confirms drones by their propeller hum: an OpenCV 5 detector proposes a box, the event camera inside that box shows the blade-pass frequency, and an agent on AWS Graviton decides what to look at next.

## The stakes

It is a December evening at Gatwick. Someone on the airfield reports a drone near the runway. Nobody can say for sure whether the dot on the camera is a drone, a bird or a bag, so the runway closes. It stays closed for about 33 hours. About 1,000 flights are cancelled and about 140,000 passengers are stranded (Gatwick, December 2018). In the US, the FAA receives more than 100 reports of drones near airports every month.

The hard part is not seeing the dot. It is knowing what the dot is. At 30 frames per second a far drone is a few pixels, and its propellers are invisible: they pass the camera's view hundreds of times a second, far faster than the 15 Hz a 30 fps camera can represent. A bird has no rotor. A drone always does.

An event camera records every pixel's brightness change with microsecond timing. A spinning propeller writes its rhythm straight into that stream. Strobe reads it.

## Try it in 90 seconds

Live, no login: **https://100-27-6-111.sslip.io**

1. Slide 1: a real FRED recording of a DJI Mini 2 at 30 fps. The rotor is a blur.
2. Slide 2: the same drone as raw events in x, y and time.
3. Slide 3: pick the drone box. The server on AWS Graviton computes the spectrum live with OpenCV 5. It peaks near 320 Hz. A box with no drone stays flat.
4. Slide 5: watch the agent work a real FRED sequence: an ambiguous box, a longer look, a whole-frame frequency map, a hum, a track, then a human approval before the alert. Press approve or reject yourself.
5. Slide 6: the measured results.

Or from a terminal:

```bash
curl -s -X POST https://100-27-6-111.sslip.io/api/spectrum \
  -H 'content-type: application/json' \
  -d '{"clip":"clear_210","box":[226,324,320,376],"t":20.5,"window_ms":100}'
```

On 2026-10-26 that call returned a 314.3 Hz peak with a score of 3,013 from 3,781 events, in 2.7 ms on a Graviton2 `t4g.small`. `/version` shows `aarch64` and OpenCV 5.0.0.

## What it does

1. **Propose.** A drone detector fine-tuned on FRED runs in the OpenCV 5 DNN engine and proposes boxes in the 30 fps RGB frame.
2. **Confirm.** Inside each box, Strobe turns the events of the last 100 ms into a 10 kHz signal (brighter-minus-darker counts), takes its spectrum with `cv.dft`, and scores the strongest peak between 150 and 1,000 Hz against its local floor.
3. **Decide.** An agent on Amazon Bedrock reads the result and picks the next action: re-check with a longer or tighter window, map frequencies across the whole frame, follow the box with a Kalman filter, ask a human, or raise an alert.
4. **Guard.** Every agent action passes a deterministic guard: valid arguments, no peeking into the future, budgets on steps and compute, and an evidence rule: no alert without a hum on that box in the last 1.5 seconds. A critical alert also needs a human's approval on the same box.
5. **Record.** Every step is logged as one line of JSON and stored in S3, with logs in CloudWatch.

What it does **not** do: it never jams, intercepts or chases anything. It confirms and alerts, and a human approves the serious alerts.

## How it uses OpenCV 5, AWS and COOL

**OpenCV 5 does all the image and event work** (`opencv-contrib-python-headless==5.0.0.93`):

- Detector: `cv.dnn.readNetFromONNX` with the new graph engine `cv.dnn.ENGINE_NEW`, `blobFromImageWithParams` letterbox, `NMSBoxes`.
- Events to signal: `cv.calcHist` on relative microsecond times, `cv.subtract` for brighter-minus-darker.
- Spectrum: `cv.createHanningWindow`, `cv.getOptimalDFTSize`, `cv.copyMakeBorder`, `cv.dft`, `cv.magnitude`, `cv.minMaxLoc`.
- Whole-frame frequency map: one `cv.dft(DFT_ROWS)` call computes up to 20,000 per-pixel spectra at once.
- Rotor mask inside a box: 2-D `calcHist`, `GaussianBlur`, Otsu `threshold`, `connectedComponentsWithStats`.
- Tracking: `cv.KalmanFilter` on event centroids from `cv.moments`.
- Build proof: `cv.getBuildInformation` on `/version`, so anyone can see which OpenCV build and HAL served the request.

**We found and documented an OpenCV 5.0.0 defect:** the Python binding silently cuts NumPy int64 arrays to their low 32 bits. Microsecond timestamps break without any error: `cv.minMaxLoc` on `[1.7e15, 5e12]` returns `(404635649, 658067456)`. Repro: `tools/int64_repro.py`. Strobe works around it with relative int32 times, and we wrote an upstream issue draft.

**AWS:** EC2 Graviton2 `t4g.small` endpoint with Caddy HTTPS, systemd and a health timer; SSM Session Manager instead of SSH; a least-privilege IAM role; S3 for bundles, benchmarks and traces; CloudWatch logs, metrics and an auto-recover alarm; Amazon Bedrock (Claude Sonnet 4.6) as the planner; an AWS Budget alert. One command, `python deploy/aws.py web`, builds or updates everything.

**COOL:** the Graviton4 COOL AMI (OpenCV 5.0 with Arm KleidiCV) runs the same app on `c8g.xlarge`, and `python deploy/aws.py cool-bench` measures COOL against pip OpenCV 5 on the same instance. COOL vs pip: [X] <!-- fill from bench/results/cool-*.json written by deploy/aws.py cool-bench -->

**Agent and MCP:** the eight tools (five of them OpenCV 5 vision tools) are exposed both to the Bedrock planner and as an MCP server, so any MCP client can drive the same guarded tools.

## Measured results on real data

All numbers are on FRED, a public dataset of real event-camera and RGB drone recordings (Apache-2.0). Thresholds were chosen on 184 train sequences and reported on 47 test sequences.

- **The hum separates drones from background.** AUC 0.917 for drone boxes against random same-size background patches (26,911 drone boxes vs 26,909 patches), and 0.758 against the busiest non-drone patch in the same frame.
- **The frequencies are physically right.** Strobe's median blade-pass frequency per drone model matches the independent PropPulse estimates on the same data: DJI Mini 2 320 Hz vs 316 Hz (1,951 boxes), DJI Tello 564 Hz vs 539 Hz (11,068 boxes), DJI Mini 3 245 Hz vs 223 Hz (2,405 boxes). For the DJI Mini 2, 99.2% of test boxes show a hum above the train-chosen threshold.
- **It reads known frequencies.** On 12 event clips with stated true frequencies (EEPPR), the estimate lands within 0.5% on 6, including a 2,000 Hz LED and a 240 Hz screen.
- **The agent beats fixed rules.** On 8 FRED scenarios fixed before any run, the Bedrock planner solved 4 of 8 with 0 false alerts. A hand-written rule planner solved 2 of 8 with 2 false alerts, and a fixed schedule 3 of 8 with 1. In one trace an ambiguous 720 Hz peak made the agent take a longer window, then map the whole frame, then find a 586 Hz hum on a new box, track it, and ask a human before alerting.
- **Graviton4 is the right home.** With the same pip OpenCV 5.0.0 at 4 threads, Graviton4 `c8g.xlarge` beat x86 `c7i.xlarge` on 5 of 6 operations, up to 2.06x on `cvtColor` and 2.04x on `connectedComponentsWithStats`, and was cheaper per call on the same 5.
- **The detector with and without the hum.** RGB only vs RGB + hum, false alarms per minute on the 47 test sequences: [X] vs [X]. <!-- fill from results_test.json written by eval/run_eval.py -->

## One honest failure: flickering lights hum too

Screens and lamps driven by mains power flicker at multiples of 100 Hz, and the event camera sees that flicker as clearly as a propeller. On the training sequences, 35% of the 2,806 strong false peaks on busy non-drone patches sat on multiples of 100 Hz. The clearest case is a phone screen in FRED sequence 212. Most of the rest sat at 300 to 350 Hz in sequences 211 to 216, right in the DJI Mini 2 band.

What we did: a notch at multiples of 100 Hz cut false alarms on the busiest patch from 4.3% to 2.6% at the strict threshold. The agent also has a whole-frame frequency map: if one frequency fills the whole scene, it is lighting, not a rotor. Flicker still causes false peaks, and the strict threshold passes only 20% of drone boxes. That is why Strobe uses the hum to confirm what the detector proposes, and lets the agent gather more evidence before it alerts.

## What's next: a pilot

1. **Site.** One small airfield or prison yard with an existing camera mast. Add one off-the-shelf event camera beside the RGB camera.
2. **Four weeks of shadow mode.** Strobe runs next to the current process and alerts nobody. Every operator drone report is matched against Strobe's trace.
3. **Measure.** False drone alarms per day with and without the hum check, and the time from first detection to a confirmed or dismissed verdict.
4. **Hand over.** If the false alarms drop, turn on the approval step for the operators, with the same guard and audit trail.
5. **Scale on Graviton with COOL.** One Graviton instance per site, sized from the COOL benchmark.

## Built with

opencv-5, opencv-dnn, cool, aws, amazon-ec2, aws-graviton, amazon-bedrock, claude, amazon-s3, amazon-cloudwatch, aws-ssm, aws-iam, aws-budgets, python, numpy, fastapi, uvicorn, caddy, mcp, onnx, yolov8, ultralytics, prophesee, event-camera, fred-dataset, kalman-filter, pytest, github-actions

# End-to-end confirm step: COOL vs pip OpenCV on one Graviton4 host

## COOL value at a glance (round 2, 2026-10-27)

Same workload as below, on the current demo set (6 FRED clips, 180 windows, 147 detector boxes), each runtime at its own fastest correct setting. Every number comes from a JSON in this folder, written on AWS.

| | Graviton4 c8g.xlarge + COOL 5.1.0-dev | Graviton4 c8g.xlarge + pip 5.0.0 | x86 c7i.xlarge + pip 5.0.0 |
|---|---|---|---|
| Detector, one window (mean ms) | 55.0 (was 103.5 on the default engine) | 51.2 | 67.9 |
| End to end, one window (p50 ms, two runs) | 60.4, 60.4 | 57.6, 57.6 | 77.1, 72.6 |
| Frequency map, 500 ms of events, 4 threads (mean ms) | 149.9 | 217.9 | 433.3 |
| Frequency map, 100 ms of events, 4 threads (mean ms) | 7.15 | 9.05 | 12.84 |
| USD per 1,000 windows, one stream | 0.00297 | 0.00289 | 0.00423 to 0.00441 |
| Same boxes, scores and hum verdicts as pip | yes, 0.0 px and 0.0 score difference | reference | not compared |

What this says:
- Tuning the detector under COOL nearly halved its time: 103.5 to 55.0 ms. The fix is the classic DNN engine, loaded from the model path.
- On COOL's own workload, the event engine, COOL is faster than pip on the same host: 1.45x on 500 ms windows and 1.26x on 100 ms windows at 4 threads, with identical outputs. At 1 thread the two are equal within 4%.
- Against x86, Graviton4 + COOL takes 17 to 22% less time per window and is 30 to 33% cheaper per window in one stream. On 500 ms event windows it is 2.9x faster than x86.
- pip 5.0.0 on the same Graviton4 is still 5% faster end to end (57.6 vs 60.4 ms), because its detector forward is 7% faster (51.2 vs 55.0 ms).
- Prices are on-demand EC2 from the AWS Price List API (c8g.xlarge 0.15952, c7i.xlarge 0.1785 USD per hour). The COOL Marketplace software fee is not included.

## Round 2 details

### 1. Detector setting sweep (`det-*.json`)

Each setting ran once over all 180 windows after 5 warm-up windows. "Correct" means the same number of boxes in every window and every box corner and score within 1e-3 of the current setting (new engine, default target, 4 threads).

| Setting | COOL mean ms | pip Graviton4 mean ms | pip x86 mean ms | Largest difference vs current |
|---|---|---|---|---|
| new engine, default target, 4 threads (current) | 103.5 | 99.8 | 73.4 | 0 |
| new engine, CPU target, 4 threads | 103.3 | 95.4 | 72.6 | 0 |
| classic engine, default target, 4 threads | **55.0** | **51.2** | **67.9** | 9.2e-5 |
| classic engine, CPU target, 4 threads | 56.3 | 51.3 | 70.6 | 9.2e-5 |
| classic engine, default target, 2 threads | 96.8 | 91.0 | 86.7 | 9.2e-5 |
| new engine, default target, 2 threads | 177.2 | 166.0 | 78.4 | 0 |

- Every setting tried was correct. The best on all three hosts is the classic engine, default target, 4 threads.
- The only DNN target either build offers on these CPUs is CPU (`getAvailableTargets` returns [0]). CPU_FP16 is not offered by COOL 5.1.0-dev or pip 5.0.0 on Graviton4, so FP16 could not be tried. The new engine ignores the target setting and warns.
- `readNetFromONNX` from an in-memory buffer ignores the engine argument and always builds the new graph (161 layers). Loading from the file path honours `ENGINE_CLASSIC` (181 layers). `bench/e2e.py --engine classic` loads by path.

### 2. Same-host E2E, best against best (`e2e-*-best-*.json`)

Both runtimes on one c8g.xlarge (Neoverse-V2), classic engine, 4 threads, 3 passes over 180 windows after 10 warm-up windows, alternating COOL, pip, COOL, pip. The x86 peer ran the same script with pip at its own best setting.

| Runtime | p50 ms | p95 ms | windows/s | detector p50 ms | hum checks p50 ms | frequency map p50 ms | USD per 1,000 windows |
|---|---|---|---|---|---|---|---|
| COOL, run 3 | 60.44 | 83.37 | 14.94 | 55.48 | 0.77 | 4.06 | 0.00297 |
| COOL, run 4 | 60.42 | 83.45 | 14.94 | 55.53 | 0.78 | 3.84 | 0.00297 |
| pip Graviton4, run 3 | 57.55 | 85.11 | 15.34 | 51.82 | 0.74 | 4.61 | 0.00289 |
| pip Graviton4, run 4 | 57.64 | 85.90 | 15.25 | 51.89 | 0.73 | 4.51 | 0.00290 |
| pip x86 c7i.xlarge, run 3 | 77.05 | 120.10 | 11.23 | 69.14 | 1.05 | 6.78 | 0.00441 |
| pip x86 c7i.xlarge, run 4 | 72.61 | 115.79 | 11.71 | 65.05 | 1.04 | 6.57 | 0.00423 |

Output equality, COOL run 3 against pip run 3 (`e2e-diff-cool-vs-pip-best-graviton4-c8g.xlarge.json`): 180 of 180 windows with the same box count, 147 boxes, 0.0 px largest corner difference, 0.0 largest score difference, 0.0 Hz largest hum peak difference, 0 hum verdict flips, 0 frequency-map windows that differ.

The round-1 table below used 7 clips and 210 windows (the demo set before the Tello seq 230 swap), so its milliseconds are not directly comparable with these. The in-run detector sweep above is the like-for-like measure of the tuning gain.

### 3. Event engine on real FRED events (`ev-*.json`)

`hertz.freq.frequency_map` over the full 1280x720 sensor and `hertz.freq.box_spectrum` on each of the 147 detector boxes, on windows of 20, 50, 100 and 500 ms ending at each frame time. One warm-up pass, then 2 timed passes. The 500 ms rows use every 5th window (36 windows) to bound the run time. Median events per window: 11,392 (20 ms), 28,513 (50 ms), 56,936 (100 ms), 303,730 (500 ms).

| Threads | Window | COOL map mean ms | pip map mean ms | COOL speed-up | x86 pip map mean ms | COOL box check mean ms | pip box check mean ms |
|---|---|---|---|---|---|---|---|
| 1 | 20 ms | 1.60 | 1.58 | 0.99x | 2.11 | 0.615 | 0.622 |
| 1 | 50 ms | 3.69 | 3.75 | 1.02x | 6.13 | 1.129 | 1.126 |
| 1 | 100 ms | 11.12 | 11.28 | 1.01x | 15.59 | 1.948 | 1.931 |
| 1 | 500 ms | 221.31 | 229.35 | 1.04x | 438.78 | 9.088 | 8.939 |
| 4 | 20 ms | 1.51 | 1.61 | 1.07x | 2.25 | 0.681 | 0.648 |
| 4 | 50 ms | 2.99 | 3.64 | 1.22x | 5.09 | 1.196 | 1.160 |
| 4 | 100 ms | 7.15 | 9.05 | 1.26x | 12.84 | 1.992 | 1.955 |
| 4 | 500 ms | 149.90 | 217.92 | 1.45x | 433.30 | 9.102 | 8.949 |

- The COOL gain grows with window length and needs threads. From 1 to 4 threads at 500 ms, COOL's map time falls from 221 to 150 ms and pip's from 229 to 218 ms. The likely cause is the map's row DFT and per-row arithmetic being parallelised in the COOL build (not profiled). The per-box hum check is small and single-threaded, so it is equal (within 5%).
- Outputs match (`ev-diff-cool-vs-pip-graviton4-c8g.xlarge.json`): 576 windows, 0 with different active or hum pixel counts, largest hum peak difference 0.0001 Hz (rounding), largest relative SNR difference 1.3e-6, 0 hum verdict flips.
- The x86 timings are noisy (p50 well under the mean, for example 5.06 vs 12.84 ms at 100 ms and 4 threads). c7i.xlarge has 4 vCPUs on 2 physical cores.

### 4. Throughput mode: no Graviton4 result

Several worker processes, each running the full E2E window over all 180 windows, with 4 / workers OpenCV threads each (`bench/tune.py tput`).
- x86 c7i.xlarge, pip, forked workers (`tput-pip-x86-c7i.xlarge.json`): 10.04, 11.88 and 12.86 windows/s at 1, 2 and 4 workers, so 0.00494, 0.00417 and 0.00386 USD per 1,000 windows.
- Graviton4, COOL: with forked workers the 2-worker step hung at 0% CPU for 43 minutes. With spawned workers the 2-worker step crashed (`double free or corruption`). No COOL multi-worker number was saved, and the pip Graviton4 step never ran, so there is no Graviton4 throughput comparison. The hang and the crash were not diagnosed.

## Round 2 sources

- Scripts: `bench/tune.py` (det, ev, tput, evcmp), `bench/e2e.py` (new `--engine` and `--target` options), the round-2 runner `bench/l17.py` and its on-host script `bench/l17_remote.sh`.
- Hosts, all tagged `Project=opencv26` and confirmed `terminated` with `describe-instances` on 2026-10-27: c8g.xlarge i-023086dd938ee50bf (COOL AMI, 04:09 to 05:17 UTC), c7i.xlarge i-09e52a1e0521efa56 (04:10 to 04:15 UTC; detector sweep and E2E, its event stage failed on a stale box file) and c7i.xlarge i-05060f09fb77316b8 (04:22 to 04:29 UTC; event and throughput stages).
- The event-engine stage reads its boxes from the same host's `e2e-pip-best-*-r3.json`.

Workload per window, on the real FRED demo clips (7 clips, 30 frames each, 210 windows):
- the drone detector (`hertz.detect.Detector`, OpenCV 5 dnn, `strobe_drone_960x544.onnx`, score >= 0.125) on the RGB frame;
- the hum check (`hertz.freq.box_spectrum`) on every box the detector proposes (169 boxes in total);
- the full-sensor frequency map (`hertz.freq.frequency_map`, 1280x720) over the same window.

Each window is the 100 ms of events ending at the frame time. JPEG decode is excluded. Each runtime ran 3 passes over the 210 windows (630 timed windows), after 10 warm-up windows. Both runtimes ran on the same c8g.xlarge (4 vCPU, Neoverse-V2), alternating COOL, pip, COOL, pip. OpenCV used all 4 threads.

| Runtime | OpenCV | p50 ms | p95 ms | windows/s | CPU, % of 4 vCPUs | USD per 1,000 windows | detector p50 ms | hum checks p50 ms | frequency map p50 ms |
|---|---|---|---|---|---|---|---|---|---|
| COOL, run 1 | 5.1.0-dev | 106.2 | 131.2 | 8.83 | 93.8 | 0.00502 | 103.3 | 0.83 | 1.85 |
| COOL, run 2 | 5.1.0-dev | 106.5 | 131.8 | 8.80 | 93.7 | 0.00504 | 103.7 | 0.82 | 1.86 |
| pip, run 1 | 5.0.0 (opencv-contrib-python-headless 5.0.0.93) | 98.9 | 129.2 | 9.32 | 91.8 | 0.00475 | 95.8 | 0.80 | 2.08 |
| pip, run 2 | 5.0.0 (opencv-contrib-python-headless 5.0.0.93) | 98.9 | 129.2 | 9.31 | 91.8 | 0.00476 | 95.9 | 0.78 | 2.02 |

Result: on this workload pip OpenCV 5.0.0 is about 7% faster than COOL end to end (p50 98.9 vs 106.2 ms). The detector forward pass decides the total, and it is slower under COOL (95.8 vs 103.3 ms). COOL is 12% faster on the frequency map (1.85 vs 2.08 ms, 1.12x). The hum checks are equal within noise. The two runs of each runtime agree within 0.3 ms at p50.

Cost is the c8g.xlarge on-demand price (0.15952 USD per hour, us-east-1, from the AWS Price List API) times the measured wall time per window. The COOL Marketplace software fee is not included.

## Output equality (pip run 1 vs COOL run 1)

| Check | Result |
|---|---|
| Windows with the same number of detector boxes | 210 of 210 |
| Boxes compared | 169 |
| Largest box corner difference | 0.0 px |
| Largest detector score difference | 0.0 |
| Largest hum peak difference | 0.0001 Hz (rounding of the stored value) |
| Boxes whose hum peak differs by more than 1 Hz | 0 |
| Largest relative difference in hum score | 4.9e-7 |
| Boxes whose hum verdict flips | 0 |
| Frequency-map windows whose active or hum pixel counts differ | 0 and 0 |

The two builds give the same boxes, scores, hum peaks and verdicts.

## Version confound

COOL ships OpenCV 5.1.0-dev, a development snapshot. The pip baseline is 5.0.0. The newest pip wheel is 5.0.0.93 (`pip index versions opencv-contrib-python-headless`, 2026-10-26), and PyPI has no 5.1 wheel. So this table compares COOL's 5.1.0-dev build (with KleidiCV 0.7.0 HAL and SVE baseline) against the stock 5.0.0 wheel (carotene HAL, NEON baseline). It does not separate the effect of the COOL build from the 5.0 to 5.1 change.

## Sources

- `bench/results/e2e-cool-graviton4-c8g.xlarge-r1.json`, `-r2.json`, `e2e-pip-graviton4-c8g.xlarge-r1.json`, `-r2.json` (meta, summary, per-window boxes, peaks and map counts)
- `bench/results/e2e-diff-cool-vs-pip-c8g.xlarge.json` (equality check)
- Script `bench/e2e.py`, run by `bench/e2e_remote.sh` through `python deploy/aws.py e2e`. The temporary instance i-0b91182be22a788d5 was launched 2026-10-26 21:14 UTC and terminated by the same command about 8 minutes later. `describe-instances` reports it as `terminated`.
- The detector model came from the project S3 bucket at deploy time and is not in git.

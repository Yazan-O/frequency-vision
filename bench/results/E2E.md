# End-to-end confirm step: COOL vs pip OpenCV on one Graviton4 host

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

Result: on this workload pip OpenCV 5.0.0 is about 7% faster than COOL end to end (p50 98.9 vs 106.2 ms). The detector forward pass decides the total, and it is slower under COOL (95.8 vs 103.3 ms). COOL is about 10% faster on the frequency map (1.85 vs 2.08 ms). The hum checks are equal within noise. The two runs of each runtime agree within 0.3 ms at p50.

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

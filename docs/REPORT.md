# [Project name]: technical report

## 1. Problem
## 2. Users
## 3. Architecture
Diagram: `architecture.svg` (OpenCV 5 stages, AWS services, COOL on Graviton, agent loop).
## 4. OpenCV 5 implementation
| Stage | OpenCV 5 API | Why this API | New in 5.x? |
|---|---|---|---|
## 5. AWS deployment
Instances, region, services, warm-endpoint strategy, cost controls, observability, security.
## 6. COOL on Graviton
COOL version, instance type, proof it runs the core workload, benchmark vs baseline (latency, throughput, utilization, cost per unit).
## 7. Agent loop
Workflow diagram, tools, a trace where vision output changed the next decision, human approval points, failure handling.
## 8. Evaluation
Datasets (with licences), metrics, baselines, results with denominators.
### 8.1 Failure cases
## 9. Limitations
## 10. Responsible use
Privacy, consent and data rights, safety, role of human review.
## 11. Reproduce

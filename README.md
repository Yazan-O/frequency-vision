# [Project name]

[One sentence.]

- Live endpoint: [URL]
- Video: [URL]
- Report: `docs/REPORT.md`

## Run locally
```bash
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --port 8080
```

## Deploy on AWS
See `deploy/README.md`.

## Reproduce the evaluation and benchmarks
See `docs/EVALUATION.md`.

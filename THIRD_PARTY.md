# Third-party code, models and data

Strobe's own code is Apache-2.0 (`LICENSE`). It uses the following.

## Runtime dependencies (`requirements.txt`, pinned)

| Package | Version | Licence |
|---|---|---|
| opencv-contrib-python-headless | 5.0.0.93 | Apache-2.0 |
| numpy | 2.5.4 | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) |
| fastapi | 0.162.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| boto3 | 1.43.118 | Apache-2.0 |
| h5py | 3.16.0 | BSD-3-Clause |

## Test and agent dependencies

| Package | Version | Where pinned | Licence |
|---|---|---|---|
| pytest | 9.1.1 | `requirements-dev.txt` | MIT |
| httpx | 0.28.1 | `requirements-dev.txt` | BSD-3-Clause |
| mcp | 1.26.0 | `strobe/agent/requirements.txt` | MIT |
| pydantic | 2.11.7 | `strobe/agent/requirements.txt` | MIT |

## Detector training only (`eval/train_detector/requirements.txt`, separate environment)

| Package | Version | Licence | Note |
|---|---|---|---|
| ultralytics | 8.3.236 | AGPL-3.0 | Used only to fine-tune the detector and export ONNX. Not imported by the Strobe runtime, which loads the ONNX file with OpenCV. |
| onnx | 1.20.1 | Apache-2.0 | Export |
| onnxslim | 0.1.98 | MIT | Export |
| opencv-python-headless | 4.12.0.88 | Apache-2.0 | Data preparation in the training environment |

Detector weights: fine-tuned from Ultralytics YOLOv8s pretrained weights (AGPL-3.0, Ultralytics). The trained ONNX file is not committed to this repository. Anyone redistributing it follows the Ultralytics licence terms.

## Vendored code

| Path | What | Licence |
|---|---|---|
| `strobe/ecf/ecf_codec.cpp`, `ecf_codec.h`, `ecf_codec_export.h` | Prophesee ECF event decoder, used to read FRED event files | Apache-2.0 (`strobe/ecf/LICENSE`) |

## Data

| Dataset | Licence | How it is used |
|---|---|---|
| FRED, huggingface.co/datasets/GabrieleMagrini/FRED | Apache-2.0, as stated on its Hugging Face card (its GitHub repository has no licence file) | Training, thresholds and every evaluation number. Two short demo clips (sequences 210 and 138) ship in `app/data` and `app/static/data` |
| EEPPR (github.com/JackPieCZ/EEPPR, arXiv:2408.06899) | GPL-3.0 | Known-frequency check only. Downloaded at run time by the user and never committed or redistributed |
| Prophesee sample recording `monitoring_40_50hz` (docs.prophesee.ai) | CC0, per the Prophesee datasets page | Mains-frequency check only. Downloaded at run time, not committed |
| OpenCV sample image `fruits.jpg` (github.com/opencv/opencv, samples/data) | OpenCV repository sample data | Benchmark input, fetched at run time by `bench/bench.py`, not redistributed |

## Services and tools

| Item | Licence or terms |
|---|---|
| Caddy (HTTPS reverse proxy on the endpoint) | Apache-2.0 |
| Amazon Bedrock, Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) | AWS Service Terms and the model provider's terms; called through the Bedrock API, nothing redistributed |
| COOL, Cloud Optimized OpenCV for AWS Graviton4 (AWS Marketplace) | Commercial Marketplace licence; used on our own subscribed instance, nothing redistributed |
| sslip.io | Free wildcard DNS service for the endpoint host name |

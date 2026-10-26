#!/bin/bash
set -euo pipefail
LABEL=$1
PRICE=$2
BUCKET=$3
PY=${4:-/srv/strobe/venv/bin/python}
ONNX_URL=${ONNX_URL:-https://huggingface.co/opencv/object_detection_yolox/resolve/main/object_detection_yolox_2022nov.onnx}
cd /srv/strobe
mkdir -p /var/tmp/bench
[ -s /var/tmp/bench/model.onnx ] || curl -fsSL "$ONNX_URL" -o /var/tmp/bench/model.onnx
$PY bench/bench.py --label "$LABEL" --onnx /var/tmp/bench/model.onnx --price-usd-hour "$PRICE" --out /var/tmp/bench/$LABEL
/srv/strobe/venv/bin/python -c "import boto3,sys;c=boto3.client('s3',region_name='us-east-1');[c.upload_file(f'/var/tmp/bench/{sys.argv[1]}.{e}',sys.argv[2],f'bench/{sys.argv[1]}.{e}') for e in ('json','npz')]" "$LABEL" "$BUCKET"

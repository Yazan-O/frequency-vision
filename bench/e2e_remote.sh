#!/bin/bash
set -euo pipefail
TYPE=$1
PRICE=$2
BUCKET=$3
cd /srv/strobe
O=/var/tmp/e2e
mkdir -p $O
M=/srv/models/strobe_drone_960x544.onnx
for r in 1 2; do
  /usr/local/bin/coolpy bench/e2e.py run --label e2e-cool-graviton4-$TYPE-r$r --onnx $M --price-usd-hour "$PRICE" --out $O/e2e-cool-graviton4-$TYPE-r$r.json
  venv/bin/python bench/e2e.py run --label e2e-pip-graviton4-$TYPE-r$r --onnx $M --price-usd-hour "$PRICE" --out $O/e2e-pip-graviton4-$TYPE-r$r.json
done
venv/bin/python bench/e2e.py compare $O/e2e-pip-graviton4-$TYPE-r1.json $O/e2e-cool-graviton4-$TYPE-r1.json --out $O/e2e-diff-cool-vs-pip-$TYPE.json
nproc; lscpu | grep -iE "model name|^cpu\(s\)" || true
venv/bin/python -c "import boto3,sys,glob,os;c=boto3.client('s3',region_name='us-east-1');[c.upload_file(f,sys.argv[1],'e2e/'+os.path.basename(f)) for f in glob.glob('$O/*.json')]" "$BUCKET"

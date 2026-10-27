#!/bin/bash
set -euo pipefail
HOST=$1
PRICE=$2
BUCKET=$3
RUNTIMES=${4:-"cool pip"}
cd /srv/strobe
O=/var/tmp/l17
mkdir -p $O
M=/srv/models/strobe_drone_960x544.onnx
BOXES=bench/results/e2e-pip-graviton4-c8g.xlarge-r1.json
py() { if [ "$1" = cool ]; then echo /usr/local/bin/coolpy; else echo venv/bin/python; fi; }
up() { venv/bin/python -c "import boto3,sys,glob,os;c=boto3.client('s3',region_name='us-east-1');[c.upload_file(f,sys.argv[1],'l17/'+os.path.basename(f)) for f in glob.glob('$O/*.json')]" "$BUCKET"; }
best() { venv/bin/python -c "import json,sys;b=json.load(open(sys.argv[1]))['best'];print(b['engine'],b['target'],b['threads'])" "$1"; }
for R in $RUNTIMES; do
  $(py $R) bench/tune.py det --label det-$R-$HOST --onnx $M --out $O/det-$R-$HOST.json
done
up
for r in 3 4; do
  for R in $RUNTIMES; do
    read E T N < <(best $O/det-$R-$HOST.json)
    $(py $R) bench/e2e.py run --label e2e-$R-best-$HOST-r$r --onnx $M --engine $E --target $T --threads $N --price-usd-hour "$PRICE" --out $O/e2e-$R-best-$HOST-r$r.json
  done
done
up
for R in $RUNTIMES; do
  $(py $R) bench/tune.py ev --label ev-$R-$HOST --boxes $BOXES --out $O/ev-$R-$HOST.json
done
up
for R in $RUNTIMES; do
  read E T N < <(best $O/det-$R-$HOST.json)
  $(py $R) bench/tune.py tput --label tput-$R-$HOST --onnx $M --engine $E --target $T --price-usd-hour "$PRICE" --out $O/tput-$R-$HOST.json
done
up
nproc; lscpu | grep -iE "model name|^cpu\(s\)" || true

#!/bin/bash
set -eu
WORK=$1; RUN=$2; DATA=$3; NAME=$4
cd "$WORK"
mkdir -p models
MC="python3 $HOME/tools/memcap.py --wait-admission 3600 --out $WORK/models"
until [ -f "$RUN/weights/DONE" ] && [ -f "$DATA/EVAL_DATA.done" ]; do sleep 60; done
V=yolo960/images/val
F="$V/108_000396.jpg $V/174_000868.jpg $V/24_003064.jpg"
[ -f "models/$NAME.onnx" ] || $MC --max-gb 6 -- env CUDA_VISIBLE_DEVICES= venv/bin/python repo/eval/train_detector/export_onnx.py --weights "$RUN/weights/best.pt" --out "$WORK/models/$NAME.onnx" --frames $F
$MC --max-gb 4 -- cv5/bin/python repo/eval/check_onnx.py --onnx "models/$NAME.onnx" --ref "models/$NAME.ref.npz" --images $F --reps 20 --threads 8 --out "models/check_$NAME.json"
md5sum repo/strobe/*.py repo/eval/*.py > "models/code_md5_$NAME.txt"
$MC --max-gb 60 -- cv5/bin/python repo/eval/run_eval.py --onnx "models/$NAME.onnx" --trainval_root "$DATA/seq_trainval" --test_root "$DATA/seq" --out "$WORK/eval_out/$NAME" --workers 10 --threads 2
touch "$WORK/FINAL_CHAIN.done"

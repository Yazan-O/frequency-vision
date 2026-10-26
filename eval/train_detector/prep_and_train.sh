#!/bin/bash
set -eu
UUID=$1; WORK=$2; ZIPS=$3; MODEL=$4; EPOCHS=$5; BATCH=$6; PREP_WORKERS=$7; TRAIN_WORKERS=$8
cd "$WORK"
[ -f yolo960/DONE ] || venv/bin/python repo/eval/train_detector/prep_yolo.py --zips "$ZIPS" --out "$WORK/yolo960" --step 4 --workers "$PREP_WORKERS"
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=$UUID
venv/bin/python repo/eval/train_detector/train_yolo.py --data "$WORK/yolo960/data.yaml" --project "$WORK/runs" --name "${MODEL%.pt}_960" --model "$MODEL" --epochs "$EPOCHS" --batch "$BATCH" --workers "$TRAIN_WORKERS"

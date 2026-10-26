#!/bin/bash
set -u
ROOT=${1:?data root}; TRAIN_ZIPS=${2:?train zip dir}; VAL_IDS=${3:?comma-separated held-out train ids}
PY=${PY:-python3}
mkdir -p "$ROOT/zips_test" "$ROOT/seq" "$ROOT/seq_trainval"
get(){ z=$1; cd "$ROOT/zips_test"; [ -f $z.done ] || { until curl -sS -L -C - --retry 5 -o $z.zip https://huggingface.co/datasets/GabrieleMagrini/FRED/resolve/main/test/$z.zip; do sleep 5; done; touch $z.done; }
  [ -d "$ROOT/seq/$z" ] || $PY -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); z.extractall(sys.argv[2], [n for n in z.namelist() if '/Frames/' not in n and '/._' not in n])" $z.zip "$ROOT/seq"; }
export -f get; export ROOT PY
echo 110 111 114 115 12 127 128 129 138 139 142 152 153 154 162 163 167 178 179 187 194 195 196 20 202 21 210 217 219 223 230 29 34 39 41 46 51 60 63 64 65 8 80 83 9 90 93 | tr ' ' '\n' | xargs -P 8 -I{} bash -c 'get {}'
for z in ${VAL_IDS//,/ }; do
  [ -d "$ROOT/seq_trainval/$z" ] || $PY -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); z.extractall(sys.argv[2], [n for n in z.namelist() if '/Frames/' not in n and '/._' not in n])" "$TRAIN_ZIPS/$z.zip" "$ROOT/seq_trainval"
done
touch "$ROOT/EVAL_DATA.done"

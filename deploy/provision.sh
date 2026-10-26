#!/bin/bash
set -euo pipefail
MODE=${1:-pip}
HOST=${2:-none}
SRC=$(cd "$(dirname "$0")/.." && pwd)
DST=/srv/strobe
COOL=/opt/cool/venvs/python_3.12
export DEBIAN_FRONTEND=noninteractive

need=()
command -v python3 >/dev/null || need+=(python3)
python3 -c "import ensurepip" 2>/dev/null || need+=(python3-venv)
[ "$HOST" = none ] || command -v caddy >/dev/null || need+=(caddy)
if [ ${#need[@]} -gt 0 ]; then apt-get update -q && apt-get install -yq "${need[@]}"; fi

mkdir -p $DST
rm -rf $DST/app $DST/hertz $DST/strobe $DST/pipeline $DST/agent $DST/bench $DST/deploy
cp -r "$SRC"/. $DST/
cd $DST

[ -x venv/bin/python ] || python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

PY=$DST/venv/bin/python
ENVX=""
if [ "$MODE" = cool ]; then
  [ -x $COOL/bin/python ] || { echo "COOL venv $COOL missing: not a COOL AMI"; exit 3; }
  grep -viE '^(opencv|numpy)' requirements.txt > /tmp/req-cool.txt
  $COOL/bin/pip install -q -r /tmp/req-cool.txt
  cat > /usr/local/bin/coolpy <<'W'
#!/bin/bash
export PYTHONPATH=/opt/cool/python_3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}
export LD_LIBRARY_PATH=/opt/cool/cpp_sdk/lib:/opt/ffmpeg/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
exec /opt/cool/venvs/python_3.12/bin/python "$@"
W
  chmod +x /usr/local/bin/coolpy
  PY=/usr/local/bin/coolpy
fi
$PY -c "import cv2,platform;print('cv2',cv2.__version__,cv2.__file__,platform.machine())"

[ "$HOST" = none ] && exit 0

cat > /etc/systemd/system/strobe.service <<EOF
[Unit]
Description=Frequency Vision API
After=network-online.target
[Service]
WorkingDirectory=$DST
$ENVX
ExecStart=$PY -m uvicorn app.main:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=2
StandardOutput=append:/var/log/strobe.log
StandardError=append:/var/log/strobe.log
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/strobe-health.service <<'EOF'
[Unit]
Description=Frequency Vision health probe
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'curl -fsS -m 5 http://127.0.0.1:8080/health >/dev/null || systemctl restart strobe'
EOF
cat > /etc/systemd/system/strobe-health.timer <<'EOF'
[Unit]
Description=Frequency Vision health probe every minute
[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
EOF

cat > /etc/caddy/Caddyfile <<EOF
$HOST {
	encode gzip
	reverse_proxy 127.0.0.1:8080
}
EOF

systemctl daemon-reload
systemctl enable --now strobe strobe-health.timer
systemctl restart strobe
systemctl enable caddy
systemctl reload-or-restart caddy

if [ ! -x /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl ]; then
  curl -fsSL "https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/$(dpkg --print-architecture)/latest/amazon-cloudwatch-agent.deb" -o /tmp/cwa.deb
  dpkg -i -E /tmp/cwa.deb
fi
cat > /opt/aws/amazon-cloudwatch-agent/etc/strobe.json <<'EOF'
{"agent": {"metrics_collection_interval": 60},
 "metrics": {"namespace": "opencv26/strobe", "append_dimensions": {"InstanceId": "${aws:InstanceId}"},
  "metrics_collected": {"mem": {"measurement": ["mem_used_percent"]}, "disk": {"resources": ["/"], "measurement": ["used_percent"]}}},
 "logs": {"logs_collected": {"files": {"collect_list": [{"file_path": "/var/log/strobe.log", "log_group_name": "/opencv26/strobe", "log_stream_name": "{instance_id}", "retention_in_days": 14}]}}}}
EOF
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/strobe.json

for k in $(seq 1 30); do curl -fsS -m 5 http://127.0.0.1:8080/health && break; sleep 2; done
echo
curl -fsS http://127.0.0.1:8080/version

# Deploying Frequency Vision on AWS Graviton

Live endpoint: `https://<public-ip-with-dashes>.sslip.io` (`/health`, `/version`). `/version` reports the CPU architecture, the OpenCV version, the path `cv2` was loaded from, and the HAL lines of `cv2.getBuildInformation()`.

## What gets created (all tagged `Project=opencv26`, region us-east-1)

| Resource | Name | Purpose |
|---|---|---|
| EC2 `c8g.medium` (Graviton4) from the COOL Graviton4 Marketplace AMI | `strobe-cool` | live endpoint, served by COOL (`python deploy/aws.py cool --type c8g.medium`) |
| EC2 `t4g.small` (Graviton2, Ubuntu 24.04 arm64), optional | `strobe` | pip OpenCV 5 endpoint without a COOL subscription (`python deploy/aws.py web`) |
| Security group | `opencv26-strobe-web` | inbound 80 and 443 only; no SSH (shell access is SSM Session Manager) |
| IAM role and instance profile | `opencv26-strobe-ec2` | SSM, CloudWatch agent, S3 bucket, Bedrock InvokeModel |
| S3 bucket | `opencv26-strobe-<random>` | release bundles and benchmark outputs |
| CloudWatch | log group `/opencv26/strobe`, namespace `opencv26/strobe`, alarm `strobe-auto-recover` | app log, memory and disk, EC2 auto-recover |
| Budgets | `opencv26-alert` (monthly, by `aws.py budget`), `opencv26-daily` (daily, created in the console) | email when actual monthly or daily spend passes the limit |

On the COOL instance the app runs on COOL's own Python build through `/usr/local/bin/coolpy` (OpenCV from `/opt/cool`, KleidiCV HAL). On the pip instance: a Python venv at `/srv/strobe/venv` with `requirements.txt` (pip `opencv-contrib-python-headless==5.0.0.93`), `uvicorn` on 127.0.0.1:8080 as systemd unit `strobe`, Caddy in front with an automatic Let's Encrypt certificate for the free `sslip.io` name of the public IP, and a one-minute timer `strobe-health` that restarts the app if `/health` stops answering. No Elastic IP, NAT gateway or load balancer. Resource, unit and path names keep the project's earlier working name `strobe`.

## Reproduce

Needs Python 3.10+, `pip install boto3==1.43.118`, and an AWS CLI profile (default name `opencv26`, override with `AWS_PROFILE`).

The deploy uploads the detector model from `build/models/strobe_drone_960x544.onnx` beside the repo folder (`MODEL` in `deploy/aws.py`). The model is not in the repo: train and export it as in [`THIRD_PARTY.md`](../THIRD_PARTY.md), then copy the exported file to that path.

```
python deploy/aws.py budget --amount 5 --email you@example.com
python deploy/aws.py web
curl https://<host>/version
```

`web` is idempotent: it reuses the bucket, role, security group and instance, uploads the current `app/ hertz/ bench/ deploy/ requirements.txt` as a bundle to S3, and runs `deploy/provision.sh` on the instance through SSM Run Command. Re-run it to redeploy. `python deploy/aws.py run --name strobe "<shell>"` runs any command on the instance.

## COOL (Cloud-Optimized OpenCV, Graviton4)

COOL ships as an AWS Marketplace AMI: "Cloud Optimized OpenCV For AWS Graviton4", https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs, product code `aajkmdd4qo3r7yhqg61a7aah9` (the launch error below links `pp?sku=aajkmdd4qo3r7yhqg61a7aah9`, which redirects to that listing). Subscribe on that page first. Then:

```
python deploy/aws.py cool-ami
python deploy/aws.py cool --name strobe-cool-bench --type c8g.xlarge
curl https://<cool-host>/version
python deploy/aws.py cool-bench --name strobe-cool-bench
```

`cool` launches the newest AMI with that product code on a Graviton4 instance, installs the app's non-OpenCV dependencies into `/opt/cool/venvs/python_3.12`, and serves the app from that interpreter. `/version` then shows `"cool": true`, a `cv2_file` under `/opt/cool`, and the KleidiCV Custom HAL line. `cool-bench` runs the benchmark with COOL and with pip OpenCV 5 on the same instance, writes the output diff, and terminates the instance.

Before subscribing, every launch of a COOL AMI fails with:

```
OptInRequired: In order to use this AWS Marketplace product you need to accept terms and subscribe. To do so please visit https://aws.amazon.com/marketplace/pp?sku=aajkmdd4qo3r7yhqg61a7aah9
```

## Benchmark

```
python deploy/aws.py bench --name strobe-bench-g4 --type c8g.xlarge --arch arm64 --label pip-graviton4-c8g.xlarge
python deploy/aws.py bench --name strobe-bench-x86 --type c7i.xlarge --arch x86_64 --label pip-x86-c7i.xlarge
python bench/table.py bench/results/cool-graviton4-*.json bench/results/pip-*.json
python bench/compare.py bench/results/pip-graviton4-c8g.xlarge.npz bench/results/pip-x86-c7i.xlarge.npz
```

`compare.py` reads the `.npz` outputs that the two `bench` commands above copy back. Each `bench` call launches a fresh instance, installs the pinned requirements, runs `bench/bench.py`, copies the JSON and outputs back through S3, and terminates the instance. Prices come from the AWS Pricing API at run time (`bench/price.py`).

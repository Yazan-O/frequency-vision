import argparse
import io
import json
import os
import secrets
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
REGION = "us-east-1"
TAG = {"Key": "Project", "Value": "opencv26"}
ROLE = "opencv26-strobe-ec2"
SG = "opencv26-strobe-web"
REPO = Path(__file__).resolve().parent.parent
MODEL = REPO.parent / "build" / "models" / "strobe_drone_960x544.onnx"
MODEL_KEY = f"models/{MODEL.name}"
COOL_G4_PRODUCT_CODE = "aajkmdd4qo3r7yhqg61a7aah9"
UBUNTU = {
    "arm64": "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id",
    "x86_64": "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id",
}

S = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "opencv26"), region_name=REGION)
ec2 = S.client("ec2")
iam = S.client("iam")
s3 = S.client("s3")
ssm = S.client("ssm")
ACCOUNT = S.client("sts").get_caller_identity()["Account"]


def tags(name, kind="instance"):
    return [{"ResourceType": kind, "Tags": [TAG, {"Key": "Name", "Value": name}]}]


def bucket():
    for b in s3.list_buckets()["Buckets"]:
        if b["Name"].startswith("opencv26-strobe-"):
            return b["Name"]
    name = f"opencv26-strobe-{secrets.token_hex(4)}"
    s3.create_bucket(Bucket=name)
    s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={k: True for k in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")})
    s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": [TAG]})
    s3.put_bucket_lifecycle_configuration(Bucket=name, LifecycleConfiguration={"Rules": [{"ID": "expire-scratch", "Status": "Enabled", "Filter": {"Prefix": "scratch/"}, "Expiration": {"Days": 7}}]})
    return name


def role(bkt):
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try:
        iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust), Tags=[TAG])
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    for arn in ("arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore", "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"):
        iam.attach_role_policy(RoleName=ROLE, PolicyArn=arn)
    inline = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"], "Resource": [f"arn:aws:s3:::{bkt}", f"arn:aws:s3:::{bkt}/*"]},
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"], "Resource": "*"},
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "cloudwatch:PutMetricData"], "Resource": "*"},
    ]}
    iam.put_role_policy(RoleName=ROLE, PolicyName="strobe", PolicyDocument=json.dumps(inline))
    try:
        iam.create_instance_profile(InstanceProfileName=ROLE, Tags=[TAG])
        iam.add_role_to_instance_profile(InstanceProfileName=ROLE, RoleName=ROLE)
        time.sleep(15)
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    return ROLE


def security_group():
    vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    got = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [SG]}, {"Name": "vpc-id", "Values": [vpc]}])["SecurityGroups"]
    if got:
        return got[0]["GroupId"]
    gid = ec2.create_security_group(GroupName=SG, Description="Hertz HTTP/HTTPS only, no SSH (SSM)", VpcId=vpc, TagSpecifications=tags(SG, "security-group"))["GroupId"]
    ec2.authorize_security_group_ingress(GroupId=gid, IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]} for p in (80, 443)])
    return gid


def find(name):
    r = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [name]}, {"Name": "tag:Project", "Values": ["opencv26"]},
                                        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    inst = [i for res in r["Reservations"] for i in res["Instances"]]
    return inst[0] if inst else None


def cool_ami():
    imgs = ec2.describe_images(Owners=["aws-marketplace"], Filters=[{"Name": "product-code", "Values": [COOL_G4_PRODUCT_CODE]}])["Images"]
    return sorted(imgs, key=lambda i: i["CreationDate"])[-1]


def up(name, itype, arch, ami=None, burst_standard=False):
    i = find(name)
    if i:
        if i["State"]["Name"] in ("stopped", "stopping"):
            ec2.get_waiter("instance_stopped").wait(InstanceIds=[i["InstanceId"]])
            ec2.start_instances(InstanceIds=[i["InstanceId"]])
        ec2.get_waiter("instance_running").wait(InstanceIds=[i["InstanceId"]])
        return find(name)
    ami = ami or ssm.get_parameter(Name=UBUNTU[arch])["Parameter"]["Value"]
    img = ec2.describe_images(ImageIds=[ami])["Images"][0]
    root = next(m for m in img["BlockDeviceMappings"] if m["DeviceName"] == img["RootDeviceName"])
    kw = dict(ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1,
              IamInstanceProfile={"Name": role(bucket())}, SecurityGroupIds=[security_group()],
              BlockDeviceMappings=[{"DeviceName": img["RootDeviceName"], "Ebs": {"VolumeSize": max(30, root["Ebs"]["VolumeSize"]), "VolumeType": "gp3", "DeleteOnTermination": True}}],
              MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
              TagSpecifications=tags(name) + tags(name, "volume"))
    if burst_standard:
        kw["CreditSpecification"] = {"CpuCredits": "standard"}
    iid = ec2.run_instances(**kw)["Instances"][0]["InstanceId"]
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    return find(name)


def host_of(i):
    return i["PublicIpAddress"].replace(".", "-") + ".sslip.io"


def wait_ssm(iid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        info = ssm.describe_instance_information(Filters=[{"Key": "InstanceIds", "Values": [iid]}])["InstanceInformationList"]
        if info and info[0]["PingStatus"] == "Online":
            return
        time.sleep(10)
    sys.exit(f"SSM agent on {iid} not online after {timeout}s")


def run(iid, script, timeout=3600):
    wait_ssm(iid)
    cid = ssm.send_command(InstanceIds=[iid], DocumentName="AWS-RunShellScript", TimeoutSeconds=timeout,
                           Parameters={"commands": [script], "executionTimeout": [str(timeout)]})["Command"]["CommandId"]
    while True:
        time.sleep(5)
        try:
            r = ssm.get_command_invocation(CommandId=cid, InstanceId=iid)
        except ClientError:
            continue
        if r["Status"] not in ("Pending", "InProgress", "Delayed"):
            sys.stdout.write(r["StandardOutputContent"])
            sys.stderr.write(r["StandardErrorContent"])
            if r["Status"] != "Success":
                sys.exit(f"command {r['Status']} on {iid}")
            return r["StandardOutputContent"]


def bundle(bkt):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in ("app", "hertz", "pipeline", "agent", "bench", "deploy", "requirements.txt"):
            if (REPO / p).exists():
                t.add(REPO / p, arcname=p, filter=lambda x: None if "__pycache__" in x.name or x.name.endswith(".pyc") else x)
    key = f"releases/strobe-{int(time.time())}.tgz"
    s3.put_object(Bucket=bkt, Key=key, Body=buf.getvalue(), Tagging="Project=opencv26")
    return s3.generate_presigned_url("get_object", Params={"Bucket": bkt, "Key": key}, ExpiresIn=3600)


def model_url(bkt):
    try:
        same = s3.head_object(Bucket=bkt, Key=MODEL_KEY)["ContentLength"] == MODEL.stat().st_size
    except ClientError:
        same = False
    if not same:
        s3.upload_file(str(MODEL), bkt, MODEL_KEY, ExtraArgs={"Tagging": "Project=opencv26"})
    return s3.generate_presigned_url("get_object", Params={"Bucket": bkt, "Key": MODEL_KEY}, ExpiresIn=3600)


def push(name, mode, web):
    i = find(name) or sys.exit(f"no instance {name}")
    bkt = bucket()
    url = bundle(bkt)
    host = host_of(i) if web else "none"
    dst = f"/srv/models/{MODEL.name}"
    model = (f"mkdir -p /srv/models /etc/systemd/system/strobe.service.d && curl -fsSL '{model_url(bkt)}' -o {dst} && "
             f"printf '[Service]\nEnvironment=HERTZ_DETECTOR_ONNX={dst}\n' > /etc/systemd/system/strobe.service.d/model.conf && ")
    run(i["InstanceId"], model + f"curl -fsSL '{url}' -o /tmp/strobe.tgz && rm -rf /tmp/strobe-src && mkdir -p /tmp/strobe-src && tar xzf /tmp/strobe.tgz -C /tmp/strobe-src && bash /tmp/strobe-src/deploy/provision.sh {mode} {host}", 1800)
    return host


def alarm(iid, name):
    S.client("cloudwatch").put_metric_alarm(
        AlarmName=f"{name}-auto-recover", Namespace="AWS/EC2", MetricName="StatusCheckFailed_System", Statistic="Maximum",
        Dimensions=[{"Name": "InstanceId", "Value": iid}], Period=60, EvaluationPeriods=2, Threshold=1, ComparisonOperator="GreaterThanOrEqualToThreshold",
        AlarmActions=[f"arn:aws:automate:{REGION}:ec2:recover"], Tags=[TAG])


def budget(amount, email):
    b = S.client("budgets")
    spec = {"BudgetName": "opencv26-alert", "BudgetLimit": {"Amount": str(amount), "Unit": "USD"}, "TimeUnit": "MONTHLY", "BudgetType": "COST"}
    note = {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 100.0, "ThresholdType": "PERCENTAGE"}
    try:
        b.create_budget(AccountId=ACCOUNT, Budget=spec, NotificationsWithSubscribers=[{"Notification": note, "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}]}])
    except b.exceptions.DuplicateRecordException:
        b.update_budget(AccountId=ACCOUNT, NewBudget=spec)
    return b.describe_budget(AccountId=ACCOUNT, BudgetName="opencv26-alert")["Budget"]["BudgetLimit"]


def price(itype):
    sys.path.insert(0, str(REPO / "bench"))
    from price import od_price
    return od_price(S.client("pricing"), itype)[0]


def bench(name, label, out, py=None, terminate=True):
    i = find(name) or sys.exit(f"no instance {name}")
    bkt = bucket()
    try:
        run(i["InstanceId"], f"bash /srv/strobe/bench/remote.sh {label} {price(i['InstanceType'])} {bkt} {py or ''}", 3600)
        os.makedirs(out, exist_ok=True)
        for e in ("json", "npz"):
            s3.download_file(bkt, f"bench/{label}.{e}", os.path.join(out, f"{label}.{e}"))
    finally:
        if terminate:
            ec2.terminate_instances(InstanceIds=[i["InstanceId"]])
            print("terminated", i["InstanceId"])


def e2e(name, itype, out):
    i = up(name, itype, "arm64", ami=cool_ami()["ImageId"])
    bkt = bucket()
    t0 = time.time()
    try:
        push(name, "cool", False)
        run(i["InstanceId"], f"bash /srv/strobe/bench/e2e_remote.sh {itype} {price(itype)} {bkt}", 3600)
        os.makedirs(out, exist_ok=True)
        for o in s3.list_objects_v2(Bucket=bkt, Prefix="e2e/").get("Contents", []):
            s3.download_file(bkt, o["Key"], os.path.join(out, os.path.basename(o["Key"])))
    finally:
        ec2.terminate_instances(InstanceIds=[i["InstanceId"]])
        ec2.get_waiter("instance_terminated").wait(InstanceIds=[i["InstanceId"]])
        st = ec2.describe_instances(InstanceIds=[i["InstanceId"]])["Reservations"][0]["Instances"][0]["State"]["Name"]
        print(json.dumps({"instance": i["InstanceId"], "state": st, "launched": str(i["LaunchTime"]), "minutes_after_up": round((time.time() - t0) / 60, 1)}))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    w = sp.add_parser("web")
    w.add_argument("--name", default="strobe")
    w.add_argument("--type", default="t4g.small")
    c = sp.add_parser("cool")
    c.add_argument("--name", default="strobe-cool")
    c.add_argument("--type", default="c8g.xlarge")
    c.add_argument("--ami")
    bn = sp.add_parser("bench-host")
    bn.add_argument("--name", required=True)
    bn.add_argument("--type", required=True)
    bn.add_argument("--arch", choices=list(UBUNTU), required=True)
    r = sp.add_parser("run")
    r.add_argument("--name", required=True)
    r.add_argument("script")
    for n in ("stop", "terminate"):
        sp.add_parser(n).add_argument("--name", required=True)
    sp.add_parser("cool-ami")
    cb = sp.add_parser("cool-bench")
    cb.add_argument("--name", default="strobe-cool")
    cb.add_argument("--out", default=str(REPO / "bench" / "results"))
    cb.add_argument("--keep", action="store_true")
    be = sp.add_parser("bench")
    be.add_argument("--name", required=True)
    be.add_argument("--type", required=True)
    be.add_argument("--arch", choices=list(UBUNTU), default="arm64")
    be.add_argument("--label", required=True)
    be.add_argument("--out", default=str(REPO / "bench" / "results"))
    be.add_argument("--keep", action="store_true")
    ee = sp.add_parser("e2e")
    ee.add_argument("--name", default="strobe-e2e")
    ee.add_argument("--type", default="c8g.xlarge")
    ee.add_argument("--out", default=str(REPO / "bench" / "results"))
    bg = sp.add_parser("budget")
    bg.add_argument("--amount", type=float, default=5)
    bg.add_argument("--email", required=True)
    a = ap.parse_args()
    if a.cmd == "web":
        i = up(a.name, a.type, "arm64", burst_standard=a.type.startswith("t"))
        alarm(i["InstanceId"], a.name)
        print(json.dumps({"instance": i["InstanceId"], "url": "https://" + push(a.name, "pip", True)}))
    elif a.cmd == "cool":
        ami = a.ami or cool_ami()["ImageId"]
        i = up(a.name, a.type, "arm64", ami=ami)
        print(json.dumps({"instance": i["InstanceId"], "ami": ami, "url": "https://" + push(a.name, "cool", True)}))
    elif a.cmd == "bench-host":
        i = up(a.name, a.type, a.arch)
        push(a.name, "pip", False)
        print(json.dumps({"instance": i["InstanceId"]}))
    elif a.cmd == "bench":
        up(a.name, a.type, a.arch)
        push(a.name, "pip", False)
        bench(a.name, a.label, a.out, terminate=not a.keep)
    elif a.cmd == "cool-bench":
        i = find(a.name) or sys.exit(f"no instance {a.name}: run `cool` first")
        t = i["InstanceType"]
        bench(a.name, f"cool-graviton4-{t}", a.out, py="/usr/local/bin/coolpy", terminate=False)
        bench(a.name, f"pip-graviton4-{t}-samehost", a.out, terminate=not a.keep)
        subprocess.run([sys.executable, str(REPO / "bench" / "compare.py"), os.path.join(a.out, f"pip-graviton4-{t}-samehost.npz"),
                        os.path.join(a.out, f"cool-graviton4-{t}.npz"), "--out", os.path.join(a.out, f"diff-cool-vs-pip-{t}.json")], check=True)
    elif a.cmd == "run":
        i = find(a.name) or sys.exit(f"no instance {a.name}")
        run(i["InstanceId"], a.script)
    elif a.cmd in ("stop", "terminate"):
        i = find(a.name) or sys.exit(f"no instance {a.name}")
        getattr(ec2, f"{a.cmd}_instances")(InstanceIds=[i["InstanceId"]])
        print(a.cmd, i["InstanceId"])
    elif a.cmd == "cool-ami":
        i = cool_ami()
        print(json.dumps({k: i.get(k) for k in ("ImageId", "Name", "CreationDate", "Architecture", "ProductCodes", "Description")}, indent=1))
    elif a.cmd == "e2e":
        e2e(a.name, a.type, a.out)
    elif a.cmd == "budget":
        print(budget(a.amount, a.email))


if __name__ == "__main__":
    main()

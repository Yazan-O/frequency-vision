import json
import os
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "deploy"))
import aws

OUT = REPO / "bench" / "results"
HOSTS = [("strobe-l17-g4", "c8g.xlarge", "arm64", "cool", "cool pip", "graviton4-c8g.xlarge"),
         ("strobe-l17-x86", "c7i.xlarge", "x86_64", "pip", "pip", "x86-c7i.xlarge")]
LIVE = "i-0d59ee3505c397229"


def one(name, itype, arch, mode, runtimes, tag, log):
    ami = aws.cool_ami()["ImageId"] if mode == "cool" else None
    i = aws.up(name, itype, arch, ami=ami)
    assert i["InstanceId"] != LIVE
    log[name] = {"instance": i["InstanceId"], "launched": str(i["LaunchTime"])}
    try:
        aws.push(name, mode, False)
        aws.run(i["InstanceId"], f"bash /srv/strobe/bench/l17_remote.sh {tag} {aws.price(itype)} {aws.bucket()} '{runtimes}'", 5400)
        log[name]["ok"] = True
    except BaseException as e:
        log[name]["error"] = repr(e)
    finally:
        bkt = aws.bucket()
        for o in aws.s3.list_objects_v2(Bucket=bkt, Prefix="l17/").get("Contents", []):
            if tag in o["Key"]:
                aws.s3.download_file(bkt, o["Key"], str(OUT / os.path.basename(o["Key"])))
        aws.ec2.terminate_instances(InstanceIds=[i["InstanceId"]])
        aws.ec2.get_waiter("instance_terminated").wait(InstanceIds=[i["InstanceId"]])
        log[name]["state"] = aws.ec2.describe_instances(InstanceIds=[i["InstanceId"]])["Reservations"][0]["Instances"][0]["State"]["Name"]
        log[name]["terminated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main():
    log = {}
    ts = [threading.Thread(target=one, args=(*h, log)) for h in HOSTS]
    for t in ts:
        t.start()
        time.sleep(20)
    for t in ts:
        t.join()
    print(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()

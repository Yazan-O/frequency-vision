import argparse
import json
import os

import boto3


def od_price(pricing, itype):
    f = {"instanceType": itype, "location": "US East (N. Virginia)", "operatingSystem": "Linux", "tenancy": "Shared", "preInstalledSw": "NA", "capacitystatus": "Used"}
    r = pricing.get_products(ServiceCode="AmazonEC2", Filters=[{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in f.items()])
    p = json.loads(r["PriceList"][0])
    dim = next(iter(next(iter(p["terms"]["OnDemand"].values()))["priceDimensions"].values()))
    return float(dim["pricePerUnit"]["USD"]), p["publicationDate"] if "publicationDate" in p else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("types", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pricing = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "opencv26"), region_name="us-east-1").client("pricing")
    out = {t: dict(zip(("usd_per_hour", "published"), od_price(pricing, t))) for t in a.types}
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()

import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+")
    a = ap.parse_args()
    runs = [json.load(open(p)) for p in a.results]
    print("| run | instance | arch | cv2 | op | threads | p50 ms | p95 ms | per s | CPU % | USD per 1M |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        m = r["meta"]
        src = "COOL" if m["cv2_file"].startswith("/opt/cool") else "pip"
        for x in r["rows"]:
            usd = f"{x['usd_per_million']:.3f}" if "usd_per_million" in x else ""
            print(f"| {m['label']} | {m['instance_type']} | {m['machine']} | {m['opencv']} {src} | {x['op']} | {x['threads']} | {x['p50_ms']:.3f} | {x['p95_ms']:.3f} | {x['throughput_per_s']:.1f} | {x['cpu_pct']:.0f} | {usd} |")


if __name__ == "__main__":
    main()

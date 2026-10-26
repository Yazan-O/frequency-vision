import json
import math
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from hertz import freq

HUM, INK, GREY, SOFT, BLUE = "#FF5A1F", "#1E1E1E", "#8A847C", "#DDD8D2", "#2E5AA8"
PALE, DEEP, PAPER = "#FFB596", "#B8400F", "#F3F1EE"
DEMO, DEMO_T, DEMO_FRAME = "clear_mini2_seq202", 1.767, 14
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": INK, "axes.labelcolor": INK,
    "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titleweight": "bold", "axes.titlesize": 11, "axes.titlelocation": "left", "figure.facecolor": "white",
    "savefig.facecolor": "white", "legend.frameon": False, "axes.grid": False, "figure.titleweight": "bold",
})


def load(p):
    return json.loads((ROOT / p).read_text())


def save(fig, name):
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def clip(cid):
    return next(c for c in load("app/static/data/clips.json")["clips"] if c["id"] == cid)


def events(cid):
    z = np.load(ROOT / "app/data" / f"{cid}.npz")
    return {"x": z["x"].astype(np.int32), "y": z["y"].astype(np.int32), "t": z["t"].astype(np.int64),
            "p": z["p"].astype(np.int8)}, float(z["origin_s"])


def demo_window():
    c = clip(DEMO)
    ev, origin = events(DEMO)
    fr = c["frames"][DEMO_FRAME]
    box = [int(v) for v in fr["boxes"][0]["box"]]
    other = [int(v) for v in fr["boxes"][1]["box"]]
    t1 = int(round((DEMO_T - origin) * 1e6))
    return c, ev, origin, fr, box, other, t1 - 100_000, t1


def fig_alias():
    c, ev, origin, _, box, _, t0, t1 = demo_window()
    f, fps = c["hum"]["median_hz"], 30.0
    k = round(f / fps)
    fa = f - k * fps
    fig, ax = plt.subplots(3, 1, figsize=(10, 7.4), gridspec_kw={"height_ratios": [1.2, 1.2, 0.55], "hspace": 0.62})
    t = np.linspace(0, 0.3, 30000)
    ax[0].plot(t * 1e3, np.sin(2 * np.pi * f * t), color=SOFT, lw=0.6, label=f"blade-pass signal, {f:.0f} Hz")
    tn = np.arange(0, 0.3, 1 / fps)
    ax[0].plot(t * 1e3, np.sin(2 * np.pi * fa * t), "--", color=INK, lw=1.4, label=f"what 30 fps reconstructs: {abs(fa):.0f} Hz")
    ax[0].plot(tn * 1e3, np.sin(2 * np.pi * f * tn), "o", color=HUM, ms=7, label="30 fps samples")
    ax[0].set(xlabel="time (ms)", yticks=[], xlim=(0, 300))
    ax[0].set_title(f"(a) {f:.0f} Hz sampled at 30 fps looks like {abs(fa):.0f} Hz", pad=22)
    ax[0].legend(loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=3, fontsize=9)
    w, _ = freq._in_box(freq._window(ev, t0, t1), box)
    fs = 4000
    on = w["p"] > 0
    sig = freq.bin_counts(w["t"][on], t0, t1, fs) - freq.bin_counts(w["t"][~on], t0, t1, fs)
    tt = np.arange(len(sig)) / fs * 1e3
    ax[1].plot(tt, sig, color=HUM, lw=1.0)
    frames = [fr["t"] for fr in c["frames"] if (t0 / 1e6 + origin) <= fr["t"] < (t1 / 1e6 + origin)]
    for i, ft in enumerate(frames):
        ax[1].axvline((ft - origin) * 1e6 / 1e3 - t0 / 1e3, color=INK, lw=1.4, ls=":", label="RGB frame instants (30 fps)" if i == 0 else None)
    ax[1].set(xlabel="time in window (ms)", ylabel="ON − OFF events / 0.25 ms", xlim=(0, 100))
    ax[1].set_title(f"Real FRED events in the DJI Mini 2 box, 100 ms ({len(w['t']):,} events, seq {c['seq']}): about {f * 0.1:.0f} cycles between {len(frames)} RGB frames", pad=8)
    ax[1].legend(loc="upper right", fontsize=9)
    a = ax[2]
    a.set_xscale("symlog", linthresh=10)
    a.axvspan(0, fps / 2, color=SOFT, alpha=0.7)
    a.axvspan(150, 1000, color=HUM, alpha=0.15)
    a.text(1.2, 0.5, "what 30 fps can show\n(0 to 15 Hz)", va="center", fontsize=8.5)
    a.text(200, 0.5, "drone blade-pass band\n150 to 1,000 Hz", va="center", fontsize=8.5, color=HUM)
    a.annotate("", xy=(abs(fa), 0.12), xytext=(f, 0.12), arrowprops=dict(arrowstyle="->", color=INK, lw=1.4, connectionstyle="arc3,rad=0.25"))
    a.plot([f], [0.12], "o", color=HUM)
    a.plot([abs(fa)], [0.12], "o", color=INK)
    a.text(f * 1.05, 0.12, f" {f:.0f} Hz", va="center", fontsize=8.5)
    a.text(abs(fa) * 0.94, 0.12, f"{abs(fa):.0f} Hz ", va="center", ha="right", fontsize=8.5)
    a.set(xlim=(0, 3000), ylim=(0, 1), yticks=[], xlabel="frequency (Hz, log above 10)")
    a.spines["left"].set_visible(False)
    save(fig, "fig_a_alias.png")


def busiest_patch(ev, box, t0, t1, W=1280, H=720):
    w = freq._window(ev, t0, t1)
    bw, bh = box[2] - box[0], box[3] - box[1]
    img = np.zeros((H, W), np.float64)
    np.add.at(img, (w["y"], w["x"]), 1)
    ii = np.pad(img, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    best, arg = -1, None
    for y in range(0, H - bh, 4):
        for x in range(0, W - bw, 4):
            if x < box[2] and x + bw > box[0] and y < box[3] and y + bh > box[1]:
                continue
            s = ii[y + bh, x + bw] - ii[y, x + bw] - ii[y + bh, x] + ii[y, x]
            if s > best:
                best, arg = s, [x, y, x + bw, y + bh]
    return arg


def cloud(ax, w, box, color, title):
    t = (w["t"] - w["t"].min()) / 1e3
    on = w["p"] > 0
    ax.scatter(t[on], w["x"][on], w["y"][on], s=1.5, c=color, alpha=0.6, linewidths=0)
    ax.scatter(t[~on], w["x"][~on], w["y"][~on], s=1.5, c=INK, alpha=0.4, linewidths=0)
    ax.set(xlabel="time (ms)", ylabel="x (px)", zlabel="y (px)", ylim=(box[0], box[2]), zlim=(box[3], box[1]))
    ax.set_box_aspect((2.2, 1, 0.75), zoom=1.3)
    ax.set_title(title, fontsize=9.5, loc="center", fontweight="bold", y=0.93)
    for a in (ax.xaxis, ax.yaxis, ax.zaxis):
        a.pane.set_facecolor(PAPER)
        a.pane.set_edgecolor(SOFT)
        a._axinfo["grid"]["linewidth"] = 0
    ax.view_init(elev=18, azim=-72)
    ax.tick_params(labelsize=7)


def fig_events():
    c, ev, origin, _, box, _, t0, t1 = demo_window()
    te = t1
    tc0 = te - c["cloud"]["ms"] * 1000
    bg = busiest_patch(ev, box, t0, t1)
    fig = plt.figure(figsize=(14, 6.6))
    gs = fig.add_gridspec(1, 2, wspace=-0.08, left=-0.04, right=1.0, top=1.04, bottom=0.42)
    ax1 = fig.add_subplot(gs[0, 0], projection="3d")
    ax2 = fig.add_subplot(gs[0, 1], projection="3d")
    ax3 = fig.add_axes([0.06, 0.08, 0.9, 0.34])
    wd, _ = freq._in_box(freq._window(ev, tc0, te), box)
    wb, _ = freq._in_box(freq._window(ev, tc0, te), bg)
    cloud(ax1, wd, box, HUM, f"drone box {box}\n{len(wd['t']):,} events in {c['cloud']['ms']} ms")
    cloud(ax2, wb, bg, GREY, f"busiest same-size non-drone patch {bg}\n{len(wb['t']):,} events in {c['cloud']['ms']} ms")
    rd = freq.box_spectrum(ev, box, t0, t1)
    rb = freq.box_spectrum(ev, bg, t0, t1)
    for r, col, lab in ((rd, HUM, "drone box"), (rb, GREY, "non-drone patch")):
        m = (r["freqs"] >= 50) & (r["freqs"] <= 1200)
        p = r["power"][m]
        ax3.plot(r["freqs"][m], p, color=col, lw=1.3, label=f"{lab}: peak {r['peak_hz']:.1f} Hz, score {r['snr']:,.0f}")
    ax3.axvspan(*freq.BAND, color=HUM, alpha=0.06)
    ax3.axvline(rd["peak_hz"], color=HUM, ls=":", lw=1)
    ax3.set(xlabel="frequency (Hz)", ylabel="power (log)", xlim=(50, 1200), yscale="log")
    ax3.set_title("Spectrum, 100 ms window (cv.calcHist + cv.dft)", fontsize=10)
    ax3.legend(loc="upper right", fontsize=9.5)
    fig.suptitle(f"(b) Real FRED events (seq {c['seq']}, DJI Mini 2) as an x-y-t cloud: the propeller is a periodic stripe", x=0.06, y=1.07, ha="left", fontweight="bold")
    save(fig, "fig_b_events.png")
    return {"drone": [rd["peak_hz"], rd["snr"]], "bg": [rb["peak_hz"], rb["snr"]], "bg_box": bg}


def fig_models():
    pm = load("results/engine/per_model_youden.json")
    pp = {}
    for v in load("results/engine/summary.json")["per_model"].values():
        for m, r in v.items():
            if r.get("proppulse_median_hz") is not None:
                pp[m] = r["proppulse_median_hz"]
    rows = sorted(pm.items(), key=lambda kv: kv[1]["median_hz"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for i, (m, r) in enumerate(rows):
        ax.plot(r["iqr"], [i, i], color=HUM, lw=5, alpha=0.3, solid_capstyle="round")
        ax.plot(r["median_hz"], i, "o", color=HUM, ms=9, zorder=3)
        ax.text(r["iqr"][1] + 12, i, f"{r['median_hz']:.0f} Hz   n = {r['n_boxes']:,} boxes, {r['share_above_7.86'] * 100:.1f}% scored", va="center", fontsize=8.5)
        if m in pp:
            ax.plot(pp[m], i, "D", mfc="white", mec=INK, mew=1.6, ms=8, zorder=4)
    ax.set_yticks(range(len(rows)), [m for m, _ in rows])
    ax.plot([], [], "o", color=HUM, label="Frequency Vision median (bar: IQR), FRED test")
    ax.plot([], [], "D", mfc="white", mec=INK, label="PropPulse / DENSE-CUAS published median")
    ax.set(xlabel="blade-pass frequency (Hz)", xlim=(150, 1150))
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title("(c) Measured hum per drone model vs an independent published estimate")
    save(fig, "fig_c_models.png")


DET_LABEL = {"a_rgb_only": "RGB only", "b_hum_train_chosen": "RGB + hum (score ≥ 3)", "b_hum_ambiguous_7.9": "RGB + hum (≥ 7.9)",
             "b_hum_clear_98": "RGB + hum (≥ 98)", "b_motion_train_chosen": "RGB + motion", "b_hum_train_chosen_and_motion": "RGB + hum + motion", "b_hum_ambiguous_7.9_and_motion": "RGB + hum (≥ 7.9) + motion"}


def fig_detector():
    r = load("results/detector/results_test.json")
    rules = {k: v for k, v in r.items() if isinstance(v, dict) and "recall" in v and "false_alarms_per_min" in v}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1.25, 1]})
    chain = [k for k in ("a_rgb_only", "b_hum_train_chosen", "b_hum_ambiguous_7.9", "b_hum_clear_98") if k in rules]
    ax.plot([rules[k]["recall"] for k in chain], [rules[k]["false_alarms_per_min"] for k in chain], color=HUM, lw=1.2, alpha=0.6, zorder=1)
    for k, v in rules.items():
        hum = "hum" in k and "motion" not in k
        col = INK if k == "a_rgb_only" else HUM if hum else GREY
        ax.scatter(v["recall"], v["false_alarms_per_min"], s=70, color=col, zorder=3, edgecolor="white")
        ax.annotate(f"{DET_LABEL.get(k, k)}\nP {v['precision']:.3f} · mAP {v['ap50']:.3f}", (v["recall"], v["false_alarms_per_min"]),
                    xytext=(8, -4) if k != "b_hum_train_chosen" else (-150, -30), textcoords="offset points", fontsize=8)
    ax.set(xlabel="recall (IoU 0.5)", ylabel="false alarms per minute", xlim=(0.1, 0.62), ylim=(0, 460))
    ax.set_title(f"(d) Every filter rule, full FRED test split\n{r['n_seq']} sequences, {r['minutes']:.1f} min, {r['n_frames']:,} frames; lower right is better")
    a, b = rules["a_rgb_only"], rules["b_hum_train_chosen"]
    cut = 1 - b["false_alarms_per_min"] / a["false_alarms_per_min"]
    bars = bx.bar(["RGB detector\nalone", "RGB + hum\n(train-chosen)"], [a["false_alarms_per_min"], b["false_alarms_per_min"]], color=[INK, HUM], width=0.55)
    for bar, v in zip(bars, (a, b)):
        bx.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 6, f"{v['false_alarms_per_min']:.1f}/min\nrecall {v['recall']:.3f}", ha="center", fontsize=9)
    bx.annotate(f"−{cut * 100:.0f}%", xy=(1, b["false_alarms_per_min"]), xytext=(0.5, a["false_alarms_per_min"] * 0.9), fontsize=20, fontweight="bold", color=HUM, ha="center")
    bx.set(ylabel="false alarms per minute", ylim=(0, a["false_alarms_per_min"] * 1.25))
    bx.set_title(f"{b['removed_fp']:,} of {a['fp']:,} false detections removed\n{b['removed_tp']} of {a['tp']:,} true detections lost")
    save(fig, "fig_d_detector.png")


def rows(p):
    return {(x["op"], x["threads"]): x["p50_ms"] for x in load(p)["rows"]}


def fig_bench():
    cool, pip_ = rows("bench/results/cool-graviton4-c8g.xlarge.json"), rows("bench/results/pip-graviton4-c8g.xlarge-samehost.json")
    g4, x86 = rows("bench/results/pip-graviton4-c8g.xlarge.json"), rows("bench/results/pip-x86-c7i.xlarge.json")
    ops = ["GaussianBlur", "dft", "connectedComponentsWithStats", "cvtColor", "resize", "dnn_forward"]
    short = {"connectedComponentsWithStats": "connected\nComponents", "dnn_forward": "DNN forward\n(YOLOX-S)", "GaussianBlur": "Gaussian\nBlur"}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14, 4.8))
    x = np.arange(len(ops))
    for j, (th, col) in enumerate(((1, SOFT), (4, HUM))):
        s = [pip_[(o, th)] / cool[(o, th)] for o in ops]
        bs = ax.bar(x + (j - 0.5) * 0.38, s, 0.38, color=col, label=f"{th} thread{'s' if th > 1 else ''}", edgecolor=INK if th == 1 else HUM, lw=0.6)
        for b_, v in zip(bs, s):
            ax.text(b_.get_x() + b_.get_width() / 2, v + 0.03, f"{v:.2f}x", ha="center", fontsize=8)
    ax.axhline(1, color=INK, lw=1, ls="--")
    ax.set_xticks(x, [short.get(o, o) for o in ops], fontsize=8.5)
    ax.set(ylabel="speed-up (pip p50 / COOL p50)", ylim=(0, 2.6))
    ax.legend(loc="upper right")
    ax.set_title("(e) COOL vs pip OpenCV 5, same Graviton4 c8g.xlarge host")
    w = 0.38
    gv, xv = [g4[(o, 4)] for o in ops], [x86[(o, 4)] for o in ops]
    bx.bar(x - w / 2, gv, w, color=HUM, label="Graviton4 c8g.xlarge (Arm)")
    bx.bar(x + w / 2, xv, w, color=INK, label="x86 c7i.xlarge")
    for i in range(len(ops)):
        bx.text(x[i], max(gv[i], xv[i]) * 1.25, f"{xv[i] / gv[i]:.2f}x", ha="center", fontsize=8.5, fontweight="bold", color=HUM if xv[i] > gv[i] else INK)
    bx.set_yscale("log")
    bx.set_xticks(x, [short.get(o, o) for o in ops], fontsize=8.5)
    bx.set(ylabel="p50 latency, ms (log), 4 threads", ylim=(0.05, 1500))
    bx.legend(loc="upper left", fontsize=8.5)
    bx.set_title("pip OpenCV 5.0.0: Graviton4 vs x86 (label: Graviton4 speed-up)")
    save(fig, "fig_e_bench.png")


TOOL_COL = {"detect_frame": GREY, "frequency_map": INK, "box_spectrum": HUM, "request_window": HUM, "track": PALE,
            "ask_human": "#5A544E", "raise_alert": DEEP, "finish": "#6E2608"}


def step_note(s):
    r, tool = s["result"] or {}, s["tool"]
    if tool == "detect_frame":
        return f"t={s['args'].get('t')} s: {len(r.get('detections', []))} boxes"
    if tool == "frequency_map":
        return f"{r.get('hum_pixels')} hum px, spot at {r.get('dominant_hz'):.0f} Hz"
    if tool in ("box_spectrum", "request_window"):
        return f"{r.get('verdict')} {r.get('peak_hz'):.1f} Hz, score {r.get('snr'):.0f}"
    if tool == "track":
        return f"{'lost' if r.get('lost') else 'held'}, moved {r.get('displacement_px'):.0f} px"
    if tool == "ask_human":
        return "approved (SIMULATED stand-in)" if r.get("approved") else "rejected"
    if tool == "raise_alert":
        return f"{s['args'].get('severity')} alert"
    if tool == "finish":
        return s["args"].get("verdict", "")
    return ""


def utc(s):
    return datetime.fromisoformat(s)


def fig_agent():
    res = load("results/agent/eval_v3/results.json")
    sm, bk = res["summary"], res["by_kind"]
    planners = [p for p in ("bedrock", "rule", "fixed") if p in sm]
    pname = {"bedrock": "Bedrock planner\n(Claude Sonnet 4.6)", "rule": "rule planner", "fixed": "fixed schedule"}
    fig = plt.figure(figsize=(14, 9.4))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.45], hspace=0.42, wspace=0.35)
    a1, a2, a3 = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[0, 2])
    cols = [HUM, INK, GREY]
    y = np.arange(len(planners))
    a1.barh(y, [sm[p]["success"] for p in planners], color=cols)
    for i, p in enumerate(planners):
        a1.text(sm[p]["success"] + 0.1, i, f"{sm[p]['success']} / {sm[p]['episodes']}, {sm[p]['false_alerts']} false alerts", va="center", fontsize=8.5)
    a1.set_yticks(y, [pname[p] for p in planners], fontsize=8.5)
    a1.invert_yaxis()
    a1.set(xlim=(0, 8), xlabel="scenarios solved (of 8)")
    a1.set_title("(f) Agent, 8 pre-registered FRED scenarios")
    a2.barh(y, [sm[p]["mean_steps"] for p in planners], color=cols)
    for i, p in enumerate(planners):
        a2.text(sm[p]["mean_steps"] + 0.2, i, f"{sm[p]['mean_steps']:g} steps", va="center", fontsize=8.5)
    a2.set_yticks(y, [])
    a2.invert_yaxis()
    a2.set(xlim=(0, 22), xlabel="mean tool calls per episode")
    a2.set_title("tool calls")
    kinds = ["background", "clear", "late", "distant"]
    M = np.array([[bk[p][k]["success"] / bk[p][k]["episodes"] for k in kinds] for p in planners])
    a3.imshow(M, cmap=matplotlib.colors.LinearSegmentedColormap.from_list("h", ["#FFFFFF", HUM]), vmin=0, vmax=1, aspect="auto")
    for i, p in enumerate(planners):
        for j, k in enumerate(kinds):
            a3.text(j, i, f"{bk[p][k]['success']}/{bk[p][k]['episodes']}", ha="center", va="center", fontsize=10, fontweight="bold")
    a3.set_xticks(range(len(kinds)), kinds, fontsize=8.5)
    a3.set_yticks(range(len(planners)), [p for p in planners], fontsize=8.5)
    a3.set_title("solved by scenario kind")
    for s in ("top", "right", "left", "bottom"):
        a3.spines[s].set_visible(False)
    rows_ = [json.loads(l) for l in (ROOT / "results/agent/eval_v3/traces/bedrock_late_142.jsonl").read_text().splitlines() if l.strip()]
    start = utc(next(r for r in rows_ if r["kind"] == "start")["utc"])
    end = next(r for r in rows_ if r["kind"] == "end")
    steps = [r for r in rows_ if r["kind"] == "step"]
    tl = fig.add_subplot(gs[1, :])
    for s in steps:
        e = (utc(s["utc"]) - start).total_seconds()
        pm, tm = s["planner_ms"] / 1e3, s["tool_ms"] / 1e3
        y_ = s["step"]
        tl.barh(y_, pm, left=e - pm - tm, color=SOFT, height=0.62)
        tl.barh(y_, max(tm, 0.06), left=e - tm, color=TOOL_COL.get(s["tool"], GREY), height=0.62)
        tl.text(e + 0.15, y_, f"{s['tool']}  ·  {step_note(s)}  ·  stream t {s['now_after']:.1f} s", va="center", fontsize=8.5,
                fontweight="bold" if s["tool"] in ("frequency_map", "ask_human", "raise_alert") else None)
    from matplotlib.patches import Patch
    hs = [Patch(color=SOFT, label="planner (Bedrock) choosing the next call")] + [Patch(color=c, label=t) for t, c in TOOL_COL.items() if t != "request_window"]
    tl.invert_yaxis()
    tl.set_yticks([s["step"] for s in steps], [f"step {s['step']}" for s in steps], fontsize=8)
    tl.set(xlabel="wall-clock seconds since episode start", xlim=(0, end["wall_s"] + 9))
    tl.legend(handles=hs, loc="upper right", fontsize=8.5, title="tool (OpenCV 5) running", title_fontsize=8.5)
    tl.set_title(f"Trace late_142 (FRED test seq 142, DJI Tello EDU enters at {next(r for r in rows_ if r['kind'] == 'start')['scenario']['entry']} s): "
                 f"the DNN sees nothing, the frequency map finds it. {end['steps']} steps, {end['wall_s']:.1f} s, verdict {end['verdict']}")
    save(fig, "fig_f_agent.png")


def fig_known():
    kf = [r for r in load("results/engine/known_freq.json") if isinstance(r["gt_hz"], (int, float))]
    fig, ax = plt.subplots(figsize=(8, 6))
    lim = (1.5, 4000)
    xs = np.array(lim)
    ax.plot(xs, xs, color=INK, lw=1, label="measured = true")
    ax.plot(xs, 2 * xs, color=GREY, lw=1, ls="--", label="measured = 2 × true (two edges per cycle)")
    for r in kf:
        g, m = r["gt_hz"], r["signed_hz"]
        err = abs(m - g) / g
        col, mk = (HUM, "o") if err < 0.03 else (BLUE, "s") if abs(m / g - 2) < 0.03 else (INK, "X")
        ax.plot(g, r["count_hz"], "o", mfc="none", mec=GREY, ms=11)
        ax.plot(g, m, mk, color=col, ms=9, mec="white")
        ax.annotate(r["name"], (g, m), xytext={"velcro_front": (-70, 6), "highcontrastdot": (-92, -4), "motor": (8, 6), "velcro_side": (-72, -3)}.get(r["name"], (6, 4)), textcoords="offset points", fontsize=8)
    ax.plot([], [], "o", color=HUM, label="ON-minus-OFF (pipeline): within 3% of true")
    ax.plot([], [], "s", color=BLUE, label="ON-minus-OFF: 2 × true")
    ax.plot([], [], "X", color=INK, label="ON-minus-OFF: other")
    ax.plot([], [], "o", mfc="none", mec=GREY, label="event-count signal, for comparison")
    ax.set(xscale="log", yscale="log", xlim=lim, ylim=lim, xlabel="stated true frequency (Hz)", ylabel="measured peak (Hz)")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title(f"(g) Known-frequency check: {len(kf)} EEPPR event clips, 1 s window")
    save(fig, "fig_g_known_freq.png")


def fig_roc():
    s = load("results/engine/summary.json")
    key = "100|signed_mask_notch"
    row = next(r for r in s["table"] if r["win_ms"] == 100 and r["variant"] == "signed_mask_notch")
    fig, ax = plt.subplots(figsize=(6.2, 5.6))
    for neg, col, auc in (("drone_vs_random", HUM, row["test_auc_drone_vs_random"]), ("drone_vs_busiest", INK, row["test_auc_drone_vs_busiest"])):
        pts = np.array(s["roc"][key][neg])
        ax.plot(pts[:, 1], pts[:, 2], color=col, lw=2, label=f"{neg.replace('_', ' ')}: AUC {auc:.3f}")
    ax.plot([0, 1], [0, 1], color=SOFT, ls="--")
    ax.set(xlabel="false-positive rate", ylabel="true-positive rate", xlim=(0, 1), ylim=(0, 1))
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title(f"(h) Hum score ROC, 100 ms, FRED test\n({row['n_test_drone']:,} drone boxes)")
    save(fig, "fig_h_roc.png")


def bars(cx, cy, r0, n, lens, flare, ink, dur):
    out = []
    for i in range(n):
        a = -math.pi / 2 + i / n * 2 * math.pi
        c, s = math.cos(a), math.sin(a)
        L = lens[i]
        col, wdt = (HUM, 5.4) if i == flare else (ink, 3.3)
        x1, y1 = cx + c * r0, cy + s * r0
        ends = [(cx + c * (r0 + l), cy + s * (r0 + l)) for l in L]
        vx = ";".join(f"{e[0]:.1f}" for e in ends + ends[:1])
        vy = ";".join(f"{e[1]:.1f}" for e in ends + ends[:1])
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{ends[0][0]:.1f}" y2="{ends[0][1]:.1f}" stroke="{col}" stroke-width="{wdt}" stroke-linecap="round">'
                   f'<animate attributeName="x2" values="{vx}" dur="{dur}s" repeatCount="indefinite"/>'
                   f'<animate attributeName="y2" values="{vy}" dur="{dur}s" repeatCount="indefinite"/></line>')
    return "".join(out)


def logo(ink, name):
    hz = clip(DEMO)["hum"]["median_hz"]
    n = 28
    flare = round((min(max(hz, 150), 1000) - 150) / 850 * (n - 1))
    rng = np.random.default_rng(7)
    lens = [[24, 29, 24] if i == flare else list(5 + 10 * rng.random(3)) for i in range(n)]
    cx, cy = 72, 60
    eye = f'M8,{cy} Q{cx},-6 136,{cy} Q{cx},126 8,{cy} Z'
    wave_len = 44
    pts = " ".join(f"{x},{60 + 17 * math.sin(2 * math.pi * x / wave_len):.2f}" for x in range(0, 4 * wave_len + 1, 2))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 120" width="560" height="120" role="img" aria-label="Frequency Vision">
<title>Frequency Vision</title>
<defs><clipPath id="eye"><path d="{eye}"/></clipPath><clipPath id="sw"><rect x="160" y="30" width="88" height="60"/></clipPath></defs>
<g clip-path="url(#eye)">{bars(cx, cy, 15, n, lens, flare, ink, 1.1)}<circle cx="{cx}" cy="{cy}" r="11" fill="{ink}"/><circle cx="{cx - 3.6}" cy="{cy - 3.6}" r="2.7" fill="#FFFFFF"/></g>
<path d="{eye}" fill="none" stroke="{ink}" stroke-width="4.5" stroke-linejoin="round"/>
<g clip-path="url(#sw)"><polyline points="{pts}" fill="none" stroke="{HUM}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" transform="translate(160 0)">
<animateTransform attributeName="transform" type="translate" from="160 0" to="{160 - wave_len} 0" dur="0.5s" repeatCount="indefinite"/></polyline></g>
<text x="262" y="76" font-family="Archivo, 'Helvetica Neue', Helvetica, Arial, sans-serif" font-size="44" font-weight="700" letter-spacing="-1" fill="{ink}">Vision</text>
<rect x="420" y="42" width="128" height="38" fill="none" stroke="{HUM}" stroke-width="2"/>
<text x="484" y="69" text-anchor="middle" font-family="'JetBrains Mono', Consolas, 'DejaVu Sans Mono', monospace" font-size="22" font-weight="500" fill="{HUM}">{hz:.0f} Hz</text>
</svg>
'''
    (OUT / name).write_text(svg, encoding="utf-8")
    print("wrote", name)


def fig_hero():
    import cv2 as cv
    from matplotlib.patches import Rectangle
    c, ev, origin, fr, box, other, t0, t1 = demo_window()
    img = cv.cvtColor(cv.imread(str(ROOT / "app/static" / fr["src"])), cv.COLOR_BGR2RGB)
    s = img.shape[1] / c["width"]
    rd, ro = freq.box_spectrum(ev, box, t0, t1), freq.box_spectrum(ev, other, t0, t1)
    hz = c["hum"]["median_hz"]
    LIGHT = "#F3F1EE"
    fig = plt.figure(figsize=(10, 4.375), dpi=160)
    fig.patch.set_facecolor(INK)
    ax = fig.add_axes([0.03, 0.2, 0.48, 0.48 * 10 / 4.375 * img.shape[0] / img.shape[1]])
    ax.imshow(img)
    x0, y0, x1, y1 = [v * s for v in box]
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec=HUM, lw=2))
    ax.text(x0, y1 + 9, "drone", color=HUM, fontsize=9, fontweight="bold", va="top")
    ax.set_axis_off()
    m = 14
    cy0, cy1, cx0, cx1 = int(y0 - m), int(y1 + m), int(x0 - m), int(x1 + m)
    crop = cv.resize(img[cy0:cy1, cx0:cx1], None, fx=4, fy=4, interpolation=cv.INTER_CUBIC)
    ins = ax.inset_axes([0.02, 0.6, 0.38, 0.38 * (cy1 - cy0) / (cx1 - cx0) * img.shape[1] / img.shape[0]])
    ins.imshow(crop)
    ins.add_patch(Rectangle((m * 4, m * 4), (x1 - x0) * 4, (y1 - y0) * 4, fill=False, ec=HUM, lw=1.5))
    ins.set_xticks([])
    ins.set_yticks([])
    for sp in ins.spines.values():
        sp.set_color(HUM)
        sp.set_linewidth(1.5)
    fig.text(0.03, 0.9, "What a 30 fps camera sees", color=LIGHT, fontsize=15, fontweight="bold")
    fig.text(0.03, 0.835, "A drone or a bird? The rotors are a blur.", color=GREY, fontsize=10.5)
    bx = fig.add_axes([0.6, 0.24, 0.37, 0.52])
    bx.set_facecolor(INK)
    for r, col, lw in ((ro, GREY, 1.4), (rd, HUM, 2.2)):
        k = (r["freqs"] >= 50) & (r["freqs"] <= 1000)
        band = (r["freqs"] >= freq.BAND[0]) & (r["freqs"] <= freq.BAND[1])
        y = r["power"][k] / np.median(r["power"][band])
        bx.plot(r["freqs"][k], y, color=col, lw=lw)
        if col == HUM:
            bx.fill_between(r["freqs"][k], y, color=HUM, alpha=0.25, lw=0)
            top = y.max()
    bx.annotate(f"{hz:.0f} Hz", (rd["peak_hz"], top), xytext=(rd["peak_hz"] + 70, top * 0.82), color=HUM, fontsize=30,
                fontweight="bold", va="center", arrowprops=dict(arrowstyle="-", color=HUM, lw=1))
    bx.text(1000, top * 0.07, "no drone: flat", color=GREY, fontsize=9.5, ha="right", va="bottom")
    bx.set(xlim=(50, 1000), ylim=(0, top * 1.08), yticks=[])
    bx.set_xlabel("frequency (Hz)", color=LIGHT, fontsize=9.5, labelpad=2)
    bx.tick_params(colors=LIGHT, labelsize=9)
    for k_, sp in bx.spines.items():
        sp.set_color(GREY)
        sp.set_visible(k_ == "bottom")
    fig.text(0.6, 0.9, "What the event camera hears", color=LIGHT, fontsize=15, fontweight="bold")
    fig.text(0.6, 0.835, "Events in the same box: the propeller hum.", color=GREY, fontsize=10.5)
    fig.text(0.03, 0.03, f"Real FRED test sequence {c['seq']}, DJI Mini 2. Spectrum of 100 ms of events in the drone box (cv.calcHist + cv.dft): "
             f"peak {rd['peak_hz']:.1f} Hz, score {rd['snr']:,.0f}.\nGrey: busiest patch with no drone, score {ro['snr']:,.0f}. "
             f"Clip median {hz:.0f} Hz over {c['hum']['n_windows']} windows of 100 ms.", color=GREY, fontsize=7.6, linespacing=1.5)
    fig.savefig(OUT / "hero.png", dpi=160, facecolor=INK)
    plt.close(fig)
    print("wrote hero.png", round(rd["peak_hz"], 1), round(rd["snr"]), round(ro["peak_hz"], 1), round(ro["snr"], 1))


FIGS = {"logo": lambda: (logo(INK, "logo.svg"), logo("#EDEDED", "logo-dark.svg")), "hero": fig_hero, "a": fig_alias,
        "b": lambda: print(json.dumps(fig_events())), "c": fig_models, "d": fig_detector, "e": fig_bench, "f": fig_agent,
        "g": fig_known, "h": fig_roc}

if __name__ == "__main__":
    for k in sys.argv[1:] or FIGS:
        FIGS[k]()

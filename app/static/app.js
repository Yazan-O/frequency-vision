import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = getComputedStyle(document.documentElement);
const INK = css.getPropertyValue("--ink").trim() || "#1E1E1E";
const OFF = css.getPropertyValue("--off").trim() || "#9A9A9A";
const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d));
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

const [clipsDoc, tracesDoc] = await Promise.all([fetch("/data/clips.json").then((r) => r.json()), fetch("/data/traces.json").then((r) => r.json())]);
const clips = clipsDoc.clips;
const hero = clips.find((c) => c.hum && c.hum.median_hz) || clips[0];

function loadFrames(clip) {
  if (!clip._imgs) clip._imgs = clip.frames.map((f) => { const i = new Image(); i.src = "/" + f.src; return i; });
  return clip._imgs;
}

function drawBoxes(ctx, clip, frame, sel, labelHz) {
  const sx = ctx.canvas.width / clip.width, sy = ctx.canvas.height / clip.height;
  frame.boxes.forEach((b, i) => {
    const [x0, y0, x1, y1] = b.box;
    const drone = b.kind === "drone";
    const pad = drone ? 0 : 6;
    ctx.lineWidth = i === sel ? 6 : drone ? 4 : 2;
    ctx.strokeStyle = drone ? "#FFFFFF" : "rgba(255,255,255,.75)";
    ctx.setLineDash(drone ? [] : [8, 6]);
    ctx.strokeRect(x0 * sx - pad, y0 * sy - pad, (x1 - x0) * sx + 2 * pad, (y1 - y0) * sy + 2 * pad);
    ctx.setLineDash([]);
    if (drone || i === sel) {
      const t = drone && labelHz ? `drone · ${labelHz} Hz` : b.label;
      ctx.font = "500 26px 'JetBrains Mono', monospace";
      const w = ctx.measureText(t).width + 16;
      const ty = Math.max(0, y0 * sy - pad - 38);
      ctx.fillStyle = "#FFFFFF"; ctx.fillRect(x0 * sx - pad, ty, w, 34);
      ctx.fillStyle = INK; ctx.fillText(t, x0 * sx - pad + 8, ty + 25);
    }
  });
}

function heroSection() {
  const h = hero.hum;
  const hz = h && h.median_hz ? Math.round(h.median_hz) : null;
  if (hz) {
    $("headline").textContent = `A bird and a drone look alike at 30 fps. Only one hums at ${hz} Hz.`;
    $("hz").textContent = `${hz} Hz`;
    $("hzcap").textContent = `Measured blade-pass frequency inside the drone box. FRED sequence ${hero.seq}, ${hero.classes.join(", ")}: median of ${h.n_windows} event windows of ${h.window_ms} ms, ${h.n_clear} of them above the hum threshold; middle half ${fmt(h.p25_hz, 0)} to ${fmt(h.p75_hz, 0)} Hz.`;
  }
  $("rgbcap").textContent = `${hero.provenance}. Box: FRED annotation.`;
  const cv = $("rgb"), ctx = cv.getContext("2d"), imgs = loadFrames(hero);
  let playing = !reduce, i = Math.floor(hero.frames.length / 2), last = 0;
  const draw = () => {
    const img = imgs[i];
    if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, cv.width, cv.height);
    const fr = hero.frames[i], db = fr.boxes.find((b) => b.kind === "drone");
    drawBoxes(ctx, hero, { boxes: fr.boxes.filter((b) => b.kind === "drone") }, -1, hz);
    if (db && img.complete && img.naturalWidth) {
      const k = img.naturalWidth / hero.width, [x0, y0, x1, y1] = db.box, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      const sw = 120, sh = 68, iw = cv.width * 0.34, ih = iw * sh / sw, ix = cv.width - iw - 16, iy = 16;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(img, (cx - sw / 2) * k, (cy - sh / 2) * k, sw * k, sh * k, ix, iy, iw, ih);
      ctx.imageSmoothingEnabled = true;
      ctx.lineWidth = 3; ctx.strokeStyle = "#FFFFFF"; ctx.strokeRect(ix, iy, iw, ih);
      ctx.font = "500 22px 'JetBrains Mono', monospace"; ctx.fillStyle = "#FFFFFF"; ctx.fillRect(ix, iy + ih, iw, 32);
      ctx.fillStyle = INK; ctx.fillText("drone, zoomed: no rotor visible", ix + 10, iy + ih + 23);
    }
    ctx.font = "500 22px 'JetBrains Mono', monospace"; ctx.fillStyle = "#FFFFFF";
    ctx.fillText(`t = ${hero.frames[i].t.toFixed(3)} s   frame ${i + 1}/${hero.frames.length}`, 20, cv.height - 20);
  };
  const tick = (now) => {
    if (playing && now - last >= 1000 / 30) { i = (i + 1) % imgs.length; last = now; draw(); }
    requestAnimationFrame(tick);
  };
  imgs.forEach((im) => im.addEventListener("load", () => { if (!playing) draw(); }));
  imgs[i].addEventListener("load", draw);
  requestAnimationFrame(tick);
  const btn = $("play");
  const sync = () => { btn.textContent = playing ? "Pause video" : "Play video"; btn.setAttribute("aria-pressed", String(playing)); };
  btn.addEventListener("click", () => { playing = !playing; sync(); draw(); });
  sync();
}

async function cloudSection() {
  const host = $("cloud");
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(new THREE.Color("#FEFEFE"));
  host.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 16 / 9, 0.01, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = !reduce;
  controls.autoRotateSpeed = 0.8;
  controls.addEventListener("start", () => { controls.autoRotate = false; });
  const group = new THREE.Group();
  scene.add(group);
  const cache = {};
  const c = hero.cloud;

  async function show(view) {
    const spec = view === "crop" && c.crop ? c.crop : c.scene;
    const buf = cache[spec.src] || (cache[spec.src] = new Uint16Array(await fetch("/" + spec.src).then((r) => r.arrayBuffer())));
    const n = buf.length / 4;
    const q = (o, a) => { const v = []; for (let k = 0; k < n; k++) v.push(buf[4 * k + o]); v.sort((x, y) => x - y); return v[Math.floor(a * (n - 1))]; };
    const [bx0, by0, bx1, by1] = view === "crop" && c.crop ? [q(0, 0.02), q(1, 0.02), q(0, 0.98) + 1, q(1, 0.98) + 1] : [0, 0, hero.width, hero.height];
    const w = bx1 - bx0, h = by1 - by0, span = c.ms * 1000;
    const s = view === "crop" ? Math.min(0.9 / h, 1.4 / w) : 1 / Math.max(w, h), depth = 1.6;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const on = new THREE.Color(INK), off = new THREE.Color("#D2D2D2");
    const order = [...Array(n).keys()].sort((a, b) => buf[4 * a + 3] - buf[4 * b + 3]);
    for (let j = 0; j < n; j++) {
      const k = order[j];
      pos[3 * j] = (buf[4 * k + 2] / span - 0.5) * depth;
      pos[3 * j + 1] = -(buf[4 * k + 1] - by0 - h / 2) * s;
      pos[3 * j + 2] = (buf[4 * k] - bx0 - w / 2) * s;
      const cc = buf[4 * k + 3] ? on : off;
      col[3 * j] = cc.r; col[3 * j + 1] = cc.g; col[3 * j + 2] = cc.b;
    }
    group.clear();
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    group.add(new THREE.Points(g, new THREE.PointsMaterial({ size: view === "crop" ? 3 : 1.2, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: view === "crop" ? 0.9 : 0.6 })));
    const bx = new THREE.Box3(new THREE.Vector3(-depth / 2, -h * s / 2, -w * s / 2), new THREE.Vector3(depth / 2, h * s / 2, w * s / 2));
    group.add(new THREE.Box3Helper(bx, new THREE.Color("#C8C8C8")));
    const ax = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-depth / 2, -h * s / 2, w * s / 2 + 0.03), new THREE.Vector3(depth / 2, -h * s / 2, w * s / 2 + 0.03)]);
    group.add(new THREE.Line(ax, new THREE.LineBasicMaterial({ color: INK })));
    camera.position.set(0.35, 0.3, 2.3);
    controls.target.set(0, 0, 0);
    controls.update();
    const total = spec.n_total && spec.n_total > n ? ` of ${spec.n_total.toLocaleString()}` : "";
    $("cloudcap").textContent = view === "crop"
      ? `${n.toLocaleString()} events in ${c.ms} ms on the drone. Black: pixel got brighter, grey: darker. The two alternate in bands as the blades pass. Drag to orbit.`
      : `${n.toLocaleString()}${total} events in ${c.ms} ms, whole frame. Drag to orbit.`;
    $("axis").textContent = `time axis: ${c.ms} ms, left to right · ${w}×${h} px`;
    bars(buf, n, span);
  }

  function bars(buf, n, span) {
    const cv = $("bars"), ctx = cv.getContext("2d"), nb = 80, d = new Float32Array(nb);
    for (let k = 0; k < n; k++) d[Math.min(nb - 1, Math.floor(buf[4 * k + 2] / span * nb))] += buf[4 * k + 3] ? 1 : -1;
    const m = Math.max(...d.map(Math.abs)) || 1, W = cv.width, H = cv.height, bw = W / nb;
    ctx.fillStyle = "#FEFEFE"; ctx.fillRect(0, 0, W, H);
    for (let k = 0; k < nb; k++) { const v = d[k] / m * (H / 2 - 4); ctx.fillStyle = v >= 0 ? INK : OFF; ctx.fillRect(k * bw, v >= 0 ? H / 2 - v : H / 2, bw - 1, Math.abs(v)); }
    const hz = hero.hum && hero.hum.median_hz;
    if (hz) { ctx.fillStyle = INK; for (let t = 0; t < span; t += 1e6 / hz) ctx.fillRect(t / span * W, H - 6, 2, 6); }
    $("barscap").textContent = hz ? `Brighter minus darker events per ${(span / nb / 1000).toFixed(2)} ms. Ticks every 1/${Math.round(hz)} s = ${(1000 / hz).toFixed(1)} ms.` : "";
  }

  const resize = () => {
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, true);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(host);
  resize();
  const loop = () => { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); };
  loop();
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-view]").forEach((o) => { const sel = o === b; o.classList.toggle("on", sel); o.setAttribute("aria-pressed", String(sel)); });
    show(b.dataset.view);
  }));
  await show(c.crop ? "crop" : "scene");
}

function spectrumSection() {
  const st = { clip: hero, frame: Math.floor(hero.frames.length / 2), box: 0, win: 100, req: 0 };
  const cv = $("pick"), ctx = cv.getContext("2d");
  const clipBtns = $("clipbtns"), winBtns = $("winbtns");
  clips.forEach((c) => {
    const b = el("button", "btn", c.drone ? `Seq ${c.seq}: drone` : `Seq ${c.seq}: no drone`);
    b.title = c.title;
    b.addEventListener("click", () => { st.clip = c; st.frame = Math.min(st.frame, c.frames.length - 1); st.box = 0; setSeg(clipBtns, b); render(); run(); });
    clipBtns.append(b);
  });
  [20, 50, 100, 300].forEach((w) => {
    const b = el("button", "btn", `${w} ms`);
    b.addEventListener("click", () => { st.win = w; setSeg(winBtns, b); run(); });
    winBtns.append(b);
    if (w === st.win) setSeg(winBtns, b);
  });
  setSeg(clipBtns, clipBtns.children[clips.indexOf(hero)]);
  function setSeg(group, on) { [...group.children].forEach((o) => { o.classList.toggle("on", o === on); o.setAttribute("aria-pressed", String(o === on)); }); }

  function render() {
    const c = st.clip, f = c.frames[st.frame], imgs = loadFrames(c), img = imgs[st.frame];
    const paint = () => { if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, cv.width, cv.height); drawBoxes(ctx, c, f, st.box, null); };
    if (img.complete) paint(); else img.onload = paint;
    $("scrub").max = c.frames.length - 1; $("scrub").value = st.frame;
    $("scrubv").textContent = `${st.frame + 1}/${c.frames.length} · t = ${f.t.toFixed(3)} s`;
    const list = $("boxbtns"); list.textContent = "";
    f.boxes.forEach((b, i) => {
      const btn = el("button", "btn", `${b.kind === "drone" ? "Drone" : "Other"} · ${Math.round(b.box[2] - b.box[0])}×${Math.round(b.box[3] - b.box[1])} px`);
      btn.setAttribute("aria-pressed", String(i === st.box));
      btn.classList.toggle("on", i === st.box);
      btn.addEventListener("click", () => { st.box = i; render(); run(); });
      list.append(btn);
    });
    if (!f.boxes.length) list.append(el("span", "cap", "No boxes in this frame. Move the slider."));
    $("pickprov").textContent = `${c.provenance}. ${c.title}. Solid box: FRED annotation. Dashed: moving things found by event blobs (OpenCV connectedComponentsWithStats).`;
  }

  cv.addEventListener("click", (e) => {
    const r = cv.getBoundingClientRect(), f = st.clip.frames[st.frame];
    const x = (e.clientX - r.left) / r.width * st.clip.width, y = (e.clientY - r.top) / r.height * st.clip.height;
    const tol = 14 / r.width * st.clip.width;
    let best = -1, area = Infinity;
    f.boxes.forEach((b, i) => {
      const [x0, y0, x1, y1] = b.box;
      if (x >= x0 - tol && x <= x1 + tol && y >= y0 - tol && y <= y1 + tol && (x1 - x0) * (y1 - y0) < area) { best = i; area = (x1 - x0) * (y1 - y0); }
    });
    if (best >= 0) { st.box = best; render(); run(); }
  });
  $("scrub").addEventListener("input", (e) => { st.frame = +e.target.value; st.box = 0; render(); clearTimeout(st.deb); st.deb = setTimeout(run, 120); });

  async function run() {
    const c = st.clip, f = c.frames[st.frame], b = f.boxes[st.box];
    if (!b) { plot(null); return; }
    const id = ++st.req, t0 = performance.now();
    $("s_src").textContent = "Computing…";
    try {
      const r = await fetch("/api/spectrum", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clip: c.id, box: b.box, t: f.t, window_ms: st.win, frame: st.frame, box_index: st.box }) });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const d = await r.json();
      if (id !== st.req) return;
      plot(d);
      $("s_peak").textContent = `${fmt(d.peak_hz, 0)} Hz`;
      $("s_snr").textContent = `${fmt(d.snr, 1)}×`;
      $("s_n").textContent = d.n_events.toLocaleString();
      $("s_v").textContent = d.clear ? "Hums" : "No hum";
      const rt = Math.round(performance.now() - t0);
      $("s_src").textContent = d.mode === "live"
        ? `Computed live for this click on AWS Graviton by ${d.source}: ${fmt(d.compute_ms, 1)} ms on the server, ${rt} ms round trip. Window: ${d.window_ms} ms of events ending at this frame. Hum: peak in ${d.band[0]}–${d.band[1]} Hz at least ${d.clear_snr}× the band median, with at least 200 events.`
        : `Server could not compute live; showing the spectrum ${d.source} (100 ms window).`;
    } catch (err) {
      if (id === st.req) $("s_src").textContent = `Spectrum request failed: ${err.message}. Try another box.`;
    }
  }

  function plot(d) {
    const svg = $("plot"), W = 600, H = 320, L = 44, R = 10, T = 14, B = 34, fmax = 1200;
    const X = (f) => L + (f / fmax) * (W - L - R);
    const Y = (v) => { const lv = Math.log10(Math.max(v, 0.1)); return T + (1 - (lv + 1) / 5) * (H - T - B); };
    let s = `<rect x="${X(150)}" y="${T}" width="${X(1000) - X(150)}" height="${H - T - B}" fill="var(--code-bg)"/>`;
    s += `<text x="${X(575)}" y="${T + 14}" text-anchor="middle">propeller band 150–1000 Hz</text>`;
    [0.1, 1, 10, 100, 1000, 10000].forEach((v) => { s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${v >= 1000 ? v / 1000 + "k" : v}</text>`; });
    [0, 200, 400, 600, 800, 1000, 1200].forEach((f) => { s += `<text x="${X(f)}" y="${H - B + 18}" text-anchor="middle">${f}</text>`; });
    s += `<text x="${W - R}" y="${H - 4}" text-anchor="end">Hz</text><text x="4" y="${T + 4}" transform="rotate(-90 4 ${T + 4})" text-anchor="end" dy="8">power / band median</text>`;
    if (d) {
      const thr = d.clear_snr || 15;
      s += `<line x1="${X(150)}" x2="${X(1000)}" y1="${Y(thr)}" y2="${Y(thr)}" stroke="var(--ink)" stroke-dasharray="4 4"/><text x="${X(1000) - 4}" y="${Y(thr) - 6}" text-anchor="end">hum threshold ${thr}×</text>`;
      const pts = d.power.map((p, k) => `${X(k * d.df).toFixed(1)},${Y(p).toFixed(1)}`).join(" ");
      s += `<polyline points="${pts}" fill="none" stroke="var(--ink)" stroke-width="1.4"/>`;
      if (d.peak_hz > 0) {
        const k = Math.round(d.peak_hz / d.df), pv = d.power[k] || 1;
        s += `<circle cx="${X(d.peak_hz)}" cy="${Y(pv)}" r="4" fill="var(--ink)"/><text x="${X(d.peak_hz) + 8}" y="${Math.max(Y(pv) - 6, T + 28)}" style="fill:var(--ink)">${Math.round(d.peak_hz)} Hz</text>`;
      }
    }
    svg.innerHTML = s;
  }
  render();
  plot(null);
  run();
}

function summarize(tool, r) {
  if (!r) return "";
  if (r.error) return `error: ${r.error}`;
  if (tool === "detect_frame") return `${r.detections.length} candidate${r.detections.length === 1 ? "" : "s"}${r.detections.length ? ": " + r.detections.map((d) => `[${d.box.join(", ")}]`).join(" ") : ""}`;
  if ("peak_hz" in r) return `peak ${fmt(r.peak_hz, 1)} Hz, ${fmt(r.snr, 1)}× median, ${r.n_events} events, ${r.window_ms} ms window → ${r.verdict}`;
  if (tool === "raise_alert") return `alert #${r.alert_id}, ${r.severity}: ${r.reason}`;
  if (tool === "finish") return `verdict: ${r.verdict}`;
  const skip = new Set(["now", "source", "thresholds"]);
  return Object.entries(r).filter(([k]) => !skip.has(k)).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ").slice(0, 240);
}

function agentSection() {
  const eps = tracesDoc.episodes || [];
  const bar = $("epbtns"), list = $("trace");
  if (!eps.length) { $("epcap").textContent = "Agent traces pending: no trace file has been exported yet."; return; }
  const pick = (ep, btn) => {
    [...bar.children].forEach((o) => { o.classList.toggle("on", o === btn); o.setAttribute("aria-pressed", String(o === btn)); });
    const sc = ep.score;
    const clip = clips.find((c) => c.id === ep.episode);
    $("epcap").textContent = `Episode ${ep.episode}, ${ep.planner} planner${ep.model ? " (" + ep.model + ")" : ""}, on ${clip ? clip.provenance : "FRED test data"}. ` +
      (sc ? `Scored against FRED boxes: ${sc.success ? "success" : "fail"}, ${sc.true_alerts} true alert${sc.true_alerts === 1 ? "" : "s"}, ${sc.false_alerts} false alert${sc.false_alerts === 1 ? "" : "s"}, ${sc.steps} steps in ${sc.wall_s} s.` : "");
    list.textContent = "";
    ep.rows.forEach((r, k) => {
      const li = el("li");
      const body = el("div", "body");
      let n = "", ph = r.phase || r.kind;
      if (r.kind === "start") {
        body.append(el("div", "why", `Starts at t = ${r.now} s with a budget of ${r.budget.max_steps} steps.`), el("div", "res", `perception: ${r.vision_source.detect}; spectrum: ${r.vision_source.spectrum}`));
      } else if (r.kind === "step") {
        n = String(r.step);
        body.append(el("div", "why", r.why));
        body.append(el("div", "tool", `${r.tool}(${Object.entries(r.args).filter(([a]) => a !== "seq").map(([a, v]) => `${a}=${JSON.stringify(v)}`).join(", ")})${r.guard !== "ok" ? "  guard: " + r.guard : ""}`));
        body.append(el("div", "res", `→ ${summarize(r.tool, r.result)}${r.tool_ms != null ? `  ·  ${r.tool_ms} ms` : ""}`));
        if (r.tool === "ask_human") { li.classList.add("approval"); body.append(askBox(ep, r)); }
      } else if (r.kind === "end") {
        ph = "end";
        body.append(el("div", "why", `Verdict: ${r.verdict}. ${r.alerts.length} alert${r.alerts.length === 1 ? "" : "s"}, ${r.steps} steps, ${r.rejections} rejected by the guard.`), el("div", "res", `${r.tool_ms} ms of tool time, ${r.wall_s} s wall`));
      } else {
        body.append(el("div", "why", r.reason || r.error || r.kind), el("div", "res", r.detail || ""));
      }
      li.append(el("span", "n", n), el("span", "ph" + (ph === "perception" ? " dim" : ""), ph), body);
      list.append(li);
      setTimeout(() => li.classList.add("in"), reduce ? 0 : 60 * k);
    });
  };
  eps.forEach((ep, i) => {
    const b = el("button", "btn", `${ep.episode} · ${ep.planner}`);
    b.addEventListener("click", () => pick(ep, b));
    bar.append(b);
  });
  const first = Math.max(0, eps.findIndex((e) => e.episode === hero.id));
  pick(eps[first], bar.children[first]);
}

function askBox(ep, r) {
  const box = el("div", "ask");
  box.append(el("div", "why", r.args.question));
  const rec = el("span", "cap", r.result ? `In the recorded run the answer came from: ${r.result.responder}.` : "");
  const send = async (decision) => {
    rec.textContent = "Recording…";
    try {
      const res = await fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episode: ep.episode, step: r.step, decision }) });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      rec.textContent = `Recorded on the server: ${d.decision} at ${d.utc}. Nothing external was triggered. Decisions on this step so far: ${d.approvals} approve, ${d.rejections} reject.`;
    } catch (e) { rec.textContent = `Could not record the decision (${e.message}).`; }
  };
  const a = el("button", "btn primary", "Approve alert"), j = el("button", "btn", "Reject alert");
  a.addEventListener("click", () => send("approve"));
  j.addEventListener("click", () => send("reject"));
  box.append(a, j, rec);
  return box;
}

async function resultsSection() {
  const d = await fetch("/api/results").then((r) => r.json()).catch(() => null);
  const fa = $("fa");
  const f = d && d.false_alarms;
  const pair = el("div", "pair");
  const cell = (label, v, note) => { const c = el("div"); c.append(el("div", "label", label), el("div", "v", v), el("div", "cap", note || "")); return c; };
  if (f && f.rgb_only && f.rgb_event) {
    pair.append(cell("RGB only", String(f.rgb_only.false_alarms), f.rgb_only.note), cell("RGB + events", String(f.rgb_event.false_alarms), f.rgb_event.note));
    fa.append(pair, el("p", "cap", f.source || ""));
  } else {
    pair.append(cell("RGB only", "pending"), cell("RGB + events", "pending"));
    fa.append(pair, el("p", "cap", "Shown when the evaluation lane writes its result file."));
  }
  const b = d && d.bench, tb = $("bench").querySelector("tbody");
  if (!b || b.status !== "ok") { tb.innerHTML = `<tr><td colspan="4">pending</td></tr>`; return; }
  b.ops.forEach((o) => {
    const tr = el("tr");
    tr.append(el("td", "", o.op.replace("connectedComponentsWithStats", "connectedComponents").replace("dnn_forward", "DNN forward (YOLOX-S)")), el("td", "", fmt(o.graviton4_ms, 3)), el("td", "", fmt(o.x86_ms, 3)), el("td", "", `${fmt(o.x86_ms / o.graviton4_ms, 2)}×`));
    tb.append(tr);
  });
  $("benchcap").textContent = `${b.graviton4.instance} (Graviton4) vs ${b.x86.instance} (x86), ${b.graviton4.threads} threads, OpenCV ${b.graviton4.opencv} from pip. Above 1× means Graviton4 is faster. Source: ${b.graviton4.file}, ${b.x86.file}.`;
}

heroSection();
spectrumSection();
agentSection();
resultsSection();
cloudSection().catch((e) => { $("cloudcap").textContent = `3D view failed to load: ${e.message}`; });

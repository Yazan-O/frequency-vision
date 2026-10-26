import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = getComputedStyle(document.documentElement);
const INK = css.getPropertyValue("--ink").trim();
const OFF = css.getPropertyValue("--off").trim();
const HUM = css.getPropertyValue("--hum").trim();
const fmt = (v, d = 1) => (v == null || Number.isNaN(+v) ? "–" : Number(v).toFixed(d));
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const icon = (id, cls = "ic") => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("class", cls); s.setAttribute("aria-hidden", "true"); const u = document.createElementNS("http://www.w3.org/2000/svg", "use"); u.setAttribute("href", "#" + id); s.append(u); return s; };
if (reduce) document.querySelectorAll("svg").forEach((s) => s.pauseAnimations && s.pauseAnimations());

const [clipsDoc, tracesDoc] = await Promise.all([fetch("/data/clips.json").then((r) => r.json()), fetch("/data/traces.json").then((r) => r.json())]);
const clips = clipsDoc.clips;
const hero = clips.find((c) => c.hum && c.hum.median_hz) || clips[0];
const bg = clips.find((c) => !c.drone) || clips[clips.length - 1];
const HZ = hero.hum && hero.hum.median_hz ? hero.hum.median_hz : null;
const PROV = hero.provenance;
const cropBuf = hero.cloud.crop ? new Uint16Array(await fetch("/" + hero.cloud.crop.src).then((r) => r.arrayBuffer())) : null;

const tip = $("tip");
document.querySelectorAll("[data-prov]").forEach((b) => {
  const text = `${PROV} · ${hero.source}`;
  b.setAttribute("aria-label", `Data source: ${text}`);
  const show = () => { const r = b.getBoundingClientRect(); tip.textContent = text; tip.hidden = false; tip.style.left = Math.max(8, Math.min(innerWidth - 290, r.right - 280)) + "px"; tip.style.top = r.bottom + 6 + "px"; };
  const hide = () => { tip.hidden = true; };
  b.addEventListener("mouseenter", show); b.addEventListener("focus", show);
  b.addEventListener("mouseleave", hide); b.addEventListener("blur", hide);
  b.addEventListener("click", () => (tip.hidden ? show() : hide()));
});

function loadFrames(clip) {
  if (!clip._imgs) clip._imgs = clip.frames.map((f) => { const i = new Image(); i.src = "/" + f.src; return i; });
  return clip._imgs;
}

function rhythm(nb) {
  const d = new Float32Array(nb), span = hero.cloud.ms * 1000;
  if (!cropBuf) return d;
  for (let k = 0; k < cropBuf.length / 4; k++) d[Math.min(nb - 1, Math.floor(cropBuf[4 * k + 2] / span * nb))] += cropBuf[4 * k + 3] ? 1 : -1;
  return d;
}

function drawRhythm(cv, opt) {
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height, d = rhythm(80), nb = d.length, span = hero.cloud.ms * 1000;
  const m = Math.max(...d.map(Math.abs)) || 1, bw = W / nb, mid = H * (opt.dark ? 0.5 : 0.5), amp = H * (opt.dark ? 0.36 : 0.44);
  ctx.fillStyle = opt.dark ? "#0b0b0b" : "#FEFEFE"; ctx.fillRect(0, 0, W, H);
  if (HZ) {
    ctx.fillStyle = opt.dark ? "rgba(255,90,31,.16)" : "rgba(255,90,31,.10)";
    for (let t = 0, i = 0; t < span; t += 1e6 / HZ, i++) if (i % 2 === 0) ctx.fillRect(t / span * W, 0, (1e6 / HZ) / span * W / 2, H);
  }
  for (let k = 0; k < nb; k++) {
    const v = d[k] / m * amp, x = k * bw;
    const lit = opt.head == null || x <= opt.head * W;
    ctx.fillStyle = v >= 0 ? (opt.dark ? (lit ? "#FFFFFF" : "#3a3a3a") : INK) : (opt.dark ? (lit ? "#8a8a8a" : "#262626") : OFF);
    ctx.fillRect(x + 1, v >= 0 ? mid - v : mid, bw - 2, Math.abs(v));
  }
  if (HZ) { ctx.fillStyle = HUM; for (let t = 0; t < span; t += 1e6 / HZ) ctx.fillRect(t / span * W - 1, H - 14, 3, 14); }
  if (opt.head != null) { ctx.fillStyle = HUM; ctx.fillRect(opt.head * W - 2, 0, 4, H); }
  if (opt.dark) {
    ctx.fillStyle = "#FFFFFF"; ctx.font = "500 30px 'JetBrains Mono', monospace";
    ctx.fillText(`0`, 16, H - 26); const t = `${hero.cloud.ms} ms`; ctx.fillText(t, W - ctx.measureText(t).width - 16, H - 26);
    ctx.fillStyle = HUM; ctx.font = "500 34px 'JetBrains Mono', monospace";
    if (HZ) ctx.fillText(`${Math.round(HZ)} Hz`, 16, 46);
  }
}

function slide1() {
  if (HZ) {
    $("headline").textContent = `A bird and a drone look alike at 30 fps. Only one hums at ${Math.round(HZ)} Hz.`;
    $("hz").textContent = `${Math.round(HZ)} Hz`;
    $("period").textContent = `${(1000 / HZ).toFixed(1)} ms`;
    const h = hero.hum;
    $("sr-hum").textContent = `Measured blade-pass frequency inside the drone box, FRED sequence ${hero.seq} (${hero.classes.join(", ")}): median ${h.median_hz} Hz over the ${h.n_clear} of ${h.n_windows} event windows of ${h.window_ms} ms that pass the hum test; middle half ${h.p25_hz} to ${h.p75_hz} Hz. Computed by tools/export_web.py with strobe.freq.box_spectrum.`;
  }
  const cv = $("rgb"), ctx = cv.getContext("2d"), imgs = loadFrames(hero);
  let playing = !reduce, i = Math.floor(hero.frames.length / 2), last = 0;
  const draw = () => {
    const img = imgs[i], fr = hero.frames[i];
    if (!(img.complete && img.naturalWidth)) return;
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
    const db = fr.boxes.find((b) => b.kind === "drone");
    if (!db) return;
    const sx = cv.width / hero.width, sy = cv.height / hero.height, [x0, y0, x1, y1] = db.box;
    ctx.lineWidth = 5; ctx.strokeStyle = "#FFFFFF"; ctx.strokeRect(x0 * sx - 6, y0 * sy - 6, (x1 - x0) * sx + 12, (y1 - y0) * sy + 12);
    const k = img.naturalWidth / hero.width, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, sw = 120, sh = 68;
    const iw = cv.width * 0.42, ih = iw * sh / sw, ix = cv.width - iw - 18, iy = 18;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, (cx - sw / 2) * k, (cy - sh / 2) * k, sw * k, sh * k, ix, iy, iw, ih);
    ctx.imageSmoothingEnabled = true;
    ctx.lineWidth = 5; ctx.strokeRect(ix, iy, iw, ih);
    ctx.beginPath(); ctx.moveTo(x1 * sx + 6, y0 * sy - 6); ctx.lineTo(ix, iy + ih); ctx.lineWidth = 2; ctx.stroke();
  };
  const tick = (now) => {
    if (playing && now - last >= 1000 / 30) { i = (i + 1) % imgs.length; last = now; draw(); }
    requestAnimationFrame(tick);
  };
  imgs.forEach((im) => im.addEventListener("load", draw));
  requestAnimationFrame(tick);
  const btn = $("play");
  const sync = () => { btn.setAttribute("aria-label", playing ? "Pause video" : "Play video"); btn.replaceChildren(icon(playing ? "i-pause" : "i-play")); };
  btn.addEventListener("click", () => { playing = !playing; sync(); draw(); });
  sync();
  const scope = $("scope");
  let t0 = performance.now();
  const sweep = (now) => {
    const f = reduce ? null : ((now - t0) / 4000) % 1;
    drawRhythm(scope, { dark: true, head: f });
    if (!reduce) requestAnimationFrame(sweep);
  };
  requestAnimationFrame(sweep);
}

let cloudStarted = false;
async function slide2() {
  if (cloudStarted) return;
  cloudStarted = true;
  drawRhythm($("bars"), { dark: false, head: null });
  $("cloudms").textContent = `${hero.cloud.ms} ms`;
  const host = $("cloud");
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(new THREE.Color("#FEFEFE"));
  host.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 16 / 9, 0.01, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.enableZoom = false; controls.autoRotate = !reduce; controls.autoRotateSpeed = 0.9;
  controls.addEventListener("start", () => { controls.autoRotate = false; });
  const group = new THREE.Group(); scene.add(group);
  const cache = {}, c = hero.cloud;
  async function show(view) {
    const spec = view === "crop" && c.crop ? c.crop : c.scene;
    const buf = cache[spec.src] || (cache[spec.src] = spec === c.crop && cropBuf ? cropBuf : new Uint16Array(await fetch("/" + spec.src).then((r) => r.arrayBuffer())));
    const n = buf.length / 4;
    const q = (o, a) => { const v = []; for (let k = 0; k < n; k++) v.push(buf[4 * k + o]); v.sort((x, y) => x - y); return v[Math.floor(a * (n - 1))]; };
    const [bx0, by0, bx1, by1] = view === "crop" ? [q(0, 0.02), q(1, 0.02), q(0, 0.98) + 1, q(1, 0.98) + 1] : [0, 0, hero.width, hero.height];
    const w = bx1 - bx0, h = by1 - by0, span = c.ms * 1000;
    const s = view === "crop" ? Math.min(0.9 / h, 1.4 / w) : 1 / Math.max(w, h), depth = 1.6;
    const order = [...Array(n).keys()].sort((a, b) => buf[4 * a + 3] - buf[4 * b + 3]);
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3), on = new THREE.Color(INK), off = new THREE.Color("#C9C9C9");
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
    group.add(new THREE.Points(g, new THREE.PointsMaterial({ size: view === "crop" ? 3.2 : 1.3, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.9 })));
    group.add(new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(-depth / 2, -h * s / 2, -w * s / 2), new THREE.Vector3(depth / 2, h * s / 2, w * s / 2)), new THREE.Color("#CFCFCF")));
    if (HZ && view === "crop") {
      const mat = new THREE.LineBasicMaterial({ color: new THREE.Color(HUM), transparent: true, opacity: 0.55 });
      for (let t = 0; t < span; t += 1e6 / HZ) {
        const x = (t / span - 0.5) * depth;
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, -h * s / 2, w * s / 2), new THREE.Vector3(x, -h * s / 2, -w * s / 2)]), mat));
      }
    }
    camera.position.set(0.35, 0.3, 2.3); controls.target.set(0, 0, 0); controls.update();
  }
  const resize = () => { const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  new ResizeObserver(resize).observe(host); resize();
  const loop = () => { if (current === 1) { controls.update(); renderer.render(scene, camera); } requestAnimationFrame(loop); };
  loop();
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-view]").forEach((o) => { const sel = o === b; o.classList.toggle("on", sel); o.setAttribute("aria-pressed", String(sel)); });
    show(b.dataset.view);
  }));
  await show(c.crop ? "crop" : "scene");
}

const spec = { win: 100, sides: {} };
function slide3() {
  const wins = $("winbtns");
  [20, 50, 100, 300].forEach((w) => {
    const b = el("button", "btn", `${w} ms`);
    b.setAttribute("aria-pressed", String(w === spec.win));
    b.addEventListener("click", () => { spec.win = w; [...wins.querySelectorAll("button")].forEach((o) => o.setAttribute("aria-pressed", String(o === b))); Object.values(spec.sides).forEach((s) => s.run()); });
    wins.append(b);
  });
  document.querySelectorAll(".side").forEach((host) => {
    const isDrone = host.dataset.side === "drone", clip = isDrone ? hero : bg;
    const firstFrame = () => {
      const mid = Math.floor(clip.frames.length / 2);
      for (let d = 0; d < clip.frames.length; d++) for (const f of [mid - d, mid + d]) if (f >= 0 && f < clip.frames.length && clip.frames[f].boxes.length) return f;
      return mid;
    };
    const st = { clip, frame: firstFrame(), box: 0, req: 0, played: false };
    st.box = Math.max(0, clip.frames[st.frame].boxes.findIndex((b) => b.kind === (isDrone ? "drone" : "other")));
    const head = el("div", "head");
    head.append(icon(isDrone ? "i-drone" : "i-nodrone"));
    const verdict = el("span", "verdict", "…"); const score = el("span", "score2");
    const prov = el("button", "prov"); prov.dataset.prov = ""; prov.append(icon("i-data"));
    prov.setAttribute("aria-label", `Data source: ${clip.provenance}, ${clip.title}`);
    prov.addEventListener("mouseenter", () => { const r = prov.getBoundingClientRect(); tip.textContent = `${clip.provenance} · ${clip.title} · seq ${clip.seq}`; tip.hidden = false; tip.style.left = Math.max(8, Math.min(innerWidth - 290, r.right - 280)) + "px"; tip.style.top = r.bottom + 6 + "px"; });
    prov.addEventListener("mouseleave", () => { tip.hidden = true; }); prov.addEventListener("focus", () => prov.dispatchEvent(new Event("mouseenter"))); prov.addEventListener("blur", () => { tip.hidden = true; });
    head.append(verdict, score, prov);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 600 300"); svg.setAttribute("class", "spec"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Event spectrum of a box in the ${isDrone ? "drone" : "no-drone"} clip`);
    const row = el("div", "thumbrow");
    const thumb = el("div", "thumb"); const cv = el("canvas"); cv.width = 640; cv.height = 360; cv.setAttribute("aria-label", "Frame with clickable boxes"); thumb.append(cv);
    const right = el("div"); right.style.flex = "1"; right.style.minWidth = "0";
    const boxes = el("div", "boxbtns"); const range = el("input"); range.type = "range"; range.min = 0; range.max = clip.frames.length - 1; range.value = st.frame;
    range.setAttribute("aria-label", "Frame");
    right.append(boxes, range); row.append(thumb, right);
    host.append(head, svg, row);
    const ctx = cv.getContext("2d"), imgs = loadFrames(clip);
    const paint = () => {
      const f = clip.frames[st.frame], img = imgs[st.frame];
      if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, cv.width, cv.height); else img.onload = paint;
      const sx = cv.width / clip.width, sy = cv.height / clip.height;
      f.boxes.forEach((b, i) => {
        const [x0, y0, x1, y1] = b.box, p = b.kind === "drone" ? 3 : 7;
        ctx.lineWidth = i === st.box ? 4 : 2; ctx.strokeStyle = i === st.box ? HUM : "#FFFFFF";
        ctx.setLineDash(b.kind === "drone" ? [] : [6, 4]);
        ctx.strokeRect(x0 * sx - p, y0 * sy - p, (x1 - x0) * sx + 2 * p, (y1 - y0) * sy + 2 * p);
      });
      ctx.setLineDash([]);
      boxes.replaceChildren(...f.boxes.map((b, i) => {
        const btn = el("button", "iconbtn"); btn.append(icon(b.kind === "drone" ? "i-drone" : "i-frame"));
        btn.setAttribute("aria-label", `${b.kind === "drone" ? "Drone box (FRED annotation)" : "Other moving thing (event blob)"} ${Math.round(b.box[2] - b.box[0])} by ${Math.round(b.box[3] - b.box[1])} px`);
        btn.setAttribute("aria-pressed", String(i === st.box));
        btn.addEventListener("click", () => { st.box = i; paint(); st.run(); });
        return btn;
      }));
    };
    cv.addEventListener("click", (e) => {
      const r = cv.getBoundingClientRect(), f = clip.frames[st.frame];
      const x = (e.clientX - r.left) / r.width * clip.width, y = (e.clientY - r.top) / r.height * clip.height, tol = 18 / r.width * clip.width;
      let best = -1, area = Infinity;
      f.boxes.forEach((b, i) => { const [x0, y0, x1, y1] = b.box; if (x >= x0 - tol && x <= x1 + tol && y >= y0 - tol && y <= y1 + tol && (x1 - x0) * (y1 - y0) < area) { best = i; area = (x1 - x0) * (y1 - y0); } });
      if (best >= 0) { st.box = best; paint(); st.run(); }
    });
    range.addEventListener("input", () => { st.frame = +range.value; st.box = 0; paint(); clearTimeout(st.deb); st.deb = setTimeout(() => st.run(), 150); });
    st.run = async () => {
      const f = clip.frames[st.frame], b = f.boxes[st.box];
      if (!b) { verdict.textContent = "–"; score.textContent = ""; svg.innerHTML = ""; return; }
      const id = ++st.req;
      try {
        const r = await fetch("/api/spectrum", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip: clip.id, box: b.box, t: f.t, window_ms: spec.win, frame: st.frame, box_index: st.box }) });
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        if (id !== st.req) return;
        st.data = d;
        verdict.className = "verdict" + (d.clear ? " hum" : "");
        verdict.replaceChildren(icon(d.clear ? "i-wave" : "i-x"), document.createTextNode(d.clear ? `${Math.round(d.peak_hz)} Hz` : "no hum"));
        score.textContent = `${d.n_events.toLocaleString()} ev`;
        score.title = `peak score ${fmt(d.snr, 1)} (hum needs ${d.clear_snr}), ${d.mode === "live" ? `computed live in ${d.compute_ms} ms by ${d.source}` : d.source}`;
        svg.setAttribute("aria-label", `${isDrone ? "Drone" : "No-drone"} clip box spectrum: ${d.clear ? "hums at " + Math.round(d.peak_hz) + " Hz" : "no hum"}, peak score ${fmt(d.snr, 1)}, ${d.n_events} events, ${d.window_ms} ms window, ${d.mode}`);
        animateSpec(svg, d, current === 2 || st.played);
        st.played = st.played || current === 2;
      } catch (e) { if (id === st.req) verdict.textContent = "offline"; }
    };
    st.svg = svg;
    spec.sides[host.dataset.side] = st;
    paint(); st.run();
  });
}

function animateSpec(svg, d, animate) {
  const W = 600, H = 300, L = 40, R = 8, T = 10, B = 26, fmax = 1200;
  const X = (f) => L + (f / fmax) * (W - L - R);
  const Y = (v) => T + (1 - (Math.log10(Math.max(v, 0.1)) + 1) / 5) * (H - T - B);
  let s = `<rect class="band" x="${X(150)}" y="${T}" width="${X(1000) - X(150)}" height="${H - T - B}"/>`;
  [1, 10, 100, 1000].forEach((v) => { s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#ECECEC"/><text x="${L - 5}" y="${Y(v) + 4}" text-anchor="end">${v >= 1000 ? "1k" : v}</text>`; });
  [0, 300, 600, 900, 1200].forEach((f) => { s += `<text x="${X(f)}" y="${H - 8}" text-anchor="middle">${f}</text>`; });
  s += `<text x="${W - R}" y="${T + 12}" text-anchor="end">Hz</text><path class="curve${d.clear ? " hum" : ""}" d=""/>`;
  svg.innerHTML = s;
  const path = svg.querySelector("path");
  const pts = d.power.map((p, k) => [X(k * d.df), Math.log10(Math.max(p, 0.1))]).filter(([x]) => x <= X(fmax));
  const base = -1, k = Math.round(d.peak_hz / d.df), pv = d.power[k] || 1;
  const frame = (e) => {
    path.setAttribute("d", "M" + pts.map(([x, lv]) => `${x.toFixed(1)},${(T + (1 - (base + (lv - base) * e + 1) / 5) * (H - T - B)).toFixed(1)}`).join("L"));
  };
  const finish = () => {
    if (!d.clear) return;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.innerHTML = `<circle class="pk pulse" cx="${X(d.peak_hz)}" cy="${Y(pv)}" r="9" filter="url(#glow)"/><circle class="pk" cx="${X(d.peak_hz)}" cy="${Y(pv)}" r="4.5"/><text class="pkl" x="${X(d.peak_hz) + 14}" y="${Math.max(Y(pv) + 6, T + 18)}">${Math.round(d.peak_hz)} Hz</text>`;
    svg.append(g);
  };
  if (!animate || reduce) { frame(1); finish(); return; }
  const t0 = performance.now();
  const step = (now) => { const u = Math.min((now - t0) / 1100, 1), e = 1 - Math.pow(1 - u, 3); frame(e); if (u < 1) requestAnimationFrame(step); else finish(); };
  requestAnimationFrame(step);
}

const NODES = [
  { id: "look", icon: "i-camera", tools: ["detect_frame"] },
  { id: "listen", icon: "i-wave", tools: ["box_spectrum", "request_window", "frequency_map", "event_map"] },
  { id: "follow", icon: "i-track", tools: ["track"] },
  { id: "ask", icon: "i-human", tools: ["ask_human"] },
  { id: "alert", icon: "i-alert", tools: ["raise_alert"] },
  { id: "done", icon: "i-flag", tools: ["finish"] },
];
const nodeOf = (tool) => NODES.findIndex((n) => n.tools.includes(tool)) >= 0 ? NODES.findIndex((n) => n.tools.includes(tool)) : 1;

function brief(r) {
  const x = r.result || {};
  if (r.guard && r.guard !== "ok") return { what: "blocked", sub: r.guard };
  if (x.error) return { what: "error", sub: x.error };
  switch (r.tool) {
    case "detect_frame": return { what: `${x.detections.length} box${x.detections.length === 1 ? "" : "es"}`, sub: `t = ${x.t} s` };
    case "box_spectrum": case "request_window": return { what: `${Math.round(x.peak_hz)} Hz · ${x.verdict}`, sub: `${fmt(x.snr, 1)}× · ${x.window_ms} ms · ${x.n_events.toLocaleString()} ev` };
    case "frequency_map": return { what: `${x.hum_pixels} / ${x.active_pixels} px hum`, sub: `${x.dominant_hz} Hz dominant` };
    case "track": return { what: `${fmt(x.displacement_px, 0)} px moved`, sub: x.lost ? "lost" : `${x.steps} steps` };
    case "ask_human": return { what: "approve?", sub: `${r.args.severity}` };
    case "raise_alert": return { what: `alert · ${x.severity}`, sub: `#${x.alert_id}` };
    case "finish": return { what: x.verdict === "drone_alerted" ? "drone" : x.verdict === "no_drone" ? "no drone" : x.verdict, sub: "" };
    default: return { what: r.tool, sub: "" };
  }
}

const agent = { ep: null, i: 0, playing: !reduce, timer: null };
function slide4() {
  const eps = tracesDoc.episodes || [];
  const bar = $("epbtns"), flow = $("flow");
  if (!eps.length) { $("stepcard").append(el("div", "what", "pending")); return; }
  flow.replaceChildren(...NODES.map((n) => { const d = el("div", "node"); const ring = el("div", "ring"); ring.append(icon(n.icon)); d.append(ring, el("span", "name", n.id), el("span", "count", "")); return d; }));
  eps.forEach((ep) => {
    const clip = clips.find((c) => c.id === ep.episode);
    const b = el("button", "btn"); b.append(icon(clip && clip.drone ? "i-drone" : "i-nodrone"), document.createTextNode(ep.planner));
    b.setAttribute("aria-label", `Episode ${ep.episode}, ${ep.planner} planner${ep.model ? " " + ep.model : ""}`);
    b.addEventListener("click", () => pickEp(ep, b));
    bar.append(b);
  });
  $("aplay").addEventListener("click", () => { agent.playing = !agent.playing; syncPlay(); if (agent.playing) schedule(); });
  const first = Math.max(0, eps.findIndex((e) => e.episode === hero.id));
  pickEp(eps[first], bar.children[first]);
}
function syncPlay() { const b = $("aplay"); b.setAttribute("aria-label", agent.playing ? "Pause" : "Play"); b.replaceChildren(icon(agent.playing ? "i-pause" : "i-play")); }
function pickEp(ep, btn) {
  [...$("epbtns").children].forEach((o) => o.setAttribute("aria-pressed", String(o === btn)));
  agent.ep = ep; agent.steps = ep.rows.filter((r) => r.kind === "step"); agent.i = 0;
  const sc = ep.score, score = $("score");
  score.replaceChildren();
  if (sc) {
    const a = el("span", "good"); a.append(icon("i-check"), document.createTextNode(sc.true_alerts));
    const b = el("span", "bad"); b.append(icon("i-x"), document.createTextNode(sc.false_alerts));
    score.append(a, b);
    score.setAttribute("aria-label", `Scored against FRED boxes: ${sc.true_alerts} true alerts, ${sc.false_alerts} false alerts, ${sc.success ? "success" : "fail"}`);
    score.title = `${sc.true_alerts} true / ${sc.false_alerts} false alerts vs FRED boxes · ${sc.steps} steps · ${sc.wall_s} s`;
  }
  $("stepdots").replaceChildren(...agent.steps.map((r, k) => {
    const b = el("button"); b.append(icon(NODES[nodeOf(r.tool)].icon)); b.setAttribute("aria-label", `Step ${r.step}: ${r.tool}`);
    b.addEventListener("click", () => { agent.playing = false; syncPlay(); showStep(k); });
    return b;
  }));
  syncPlay(); showStep(0); schedule();
}
function schedule() {
  clearTimeout(agent.timer);
  if (!agent.playing || current !== 4) return;
  agent.timer = setTimeout(() => { showStep(agent.i + 1 >= agent.steps.length ? 0 : agent.i + 1); schedule(); }, agent.i + 1 >= agent.steps.length ? 3200 : 1700);
}
function showStep(k) {
  agent.i = k;
  const steps = agent.steps, r = steps[k];
  const counts = NODES.map(() => 0);
  steps.slice(0, k + 1).forEach((s) => counts[nodeOf(s.tool)]++);
  const ni = nodeOf(r.tool);
  [...$("flow").children].forEach((n, j) => {
    n.classList.toggle("seen", counts[j] > 0); n.classList.toggle("now", j === ni);
    n.querySelector(".count").textContent = counts[j] ? `×${counts[j]}` : "";
  });
  [...$("stepdots").children].forEach((b, j) => { b.classList.toggle("seen", j < k); b.classList.toggle("now", j === k); b.setAttribute("aria-current", String(j === k)); });
  const card = $("stepcard"), bf = brief(r);
  const body = el("div"); body.append(el("div", "what", bf.what), el("div", "sub", `${r.tool} · ${bf.sub}`));
  const sr = el("span", "sr-only", `Step ${r.step} of ${steps.length}: ${r.tool}. ${r.why || ""} Result: ${bf.what}.`); body.append(sr);
  if (r.tool === "ask_human") body.append(approval(r));
  card.replaceChildren(icon(NODES[ni].icon, "ic bigic"), body, el("span", "stepn", `${r.step}/${steps.length}`));
}
function approval(r) {
  const box = el("div", "approve");
  const rec = el("span", "rec");
  rec.title = r.result ? `In the recorded run: ${r.result.responder}` : "";
  const send = async (decision) => {
    agent.playing = false; syncPlay(); clearTimeout(agent.timer);
    try {
      const res = await fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episode: agent.ep.episode, step: r.step, decision }) });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      rec.replaceChildren(icon(decision === "approve" ? "i-check" : "i-x"), document.createTextNode(`${d.approvals} · ${d.rejections}`));
      rec.setAttribute("aria-label", `Recorded on the server at ${d.utc}: ${d.decision}. Nothing external was triggered. ${d.approvals} approvals and ${d.rejections} rejections on this step so far.`);
      rec.title = `Recorded on the server, ${d.utc}. Nothing external triggered. ${d.approvals} approve / ${d.rejections} reject so far.`;
    } catch (e) { rec.textContent = "offline"; }
  };
  const a = el("button", "btn yes"); a.append(icon("i-check"), document.createTextNode("Approve")); a.addEventListener("click", () => send("approve"));
  const j = el("button", "btn"); j.append(icon("i-x"), document.createTextNode("Reject")); j.addEventListener("click", () => send("reject"));
  box.append(icon("i-human"), a, j, rec);
  return box;
}

async function slide5() {
  const d = await fetch("/api/results").then((r) => r.json()).catch(() => null);
  const f = d && d.false_alarms, fa = $("fa");
  const cell = (ics, label, v) => {
    const c = el("div", "facell"); const who = el("div", "who"); ics.forEach((i) => who.append(icon(i)));
    c.setAttribute("aria-label", `${label}: ${v}`);
    c.append(who, el("div", "v" + (v === "pending" ? " pending" : ""), v)); return c;
  };
  const ok = f && f.rgb_only && f.rgb_event;
  fa.append(cell(["i-camera"], "RGB only", ok ? String(f.rgb_only.false_alarms) : "pending"), cell(["i-camera", "i-wave"], "RGB plus events", ok ? String(f.rgb_event.false_alarms) : "pending"));
  const b = d && d.bench, bb = $("benchbars");
  if (!b || b.status !== "ok") { bb.append(el("div", "win5", "pending")); return; }
  const short = { connectedComponentsWithStats: "components", dnn_forward: "DNN", GaussianBlur: "blur", cvtColor: "cvtColor", resize: "resize", dft: "DFT" };
  const wins = b.ops.filter((o) => o.graviton4_ms < o.x86_ms).length;
  const w = $("winner"); w.append(document.createTextNode(`${wins}/${b.ops.length}`)); const sm = el("small", "", "faster on Graviton4"); w.append(sm);
  w.setAttribute("aria-label", `Graviton4 ${b.graviton4.instance} faster than x86 ${b.x86.instance} on ${wins} of ${b.ops.length} OpenCV 5 operations, ${b.graviton4.threads} threads, p50 ms. Source ${b.graviton4.file} and ${b.x86.file}.`);
  b.ops.forEach((o) => {
    const m = Math.max(o.graviton4_ms, o.x86_ms), r = o.x86_ms / o.graviton4_ms;
    const row = el("div", "bbrow"); row.title = `${o.op}: Graviton4 ${fmt(o.graviton4_ms, 3)} ms, x86 ${fmt(o.x86_ms, 3)} ms`;
    const bars = el("div", "bars2"); const g = el("div", "b g4"), x = el("div", "b x86");
    g.style.width = (o.graviton4_ms / m * 100) + "%"; x.style.width = (o.x86_ms / m * 100) + "%";
    g.style.transform = x.style.transform = "scaleX(0)";
    bars.append(g, x);
    row.append(el("span", "", short[o.op] || o.op), bars, el("span", "r" + (r > 1 ? " win" : ""), `${fmt(r, 2)}×`));
    bb.append(row);
  });
}
function growBars() { document.querySelectorAll(".bbrow .b").forEach((b) => { b.style.transform = "scaleX(1)"; }); }

async function getSpec(clip, frame, box, win) {
  const f = clip.frames[frame], b = f.boxes[box];
  const r = await fetch("/api/spectrum", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip: clip.id, box: b.box, t: f.t, window_ms: win, frame, box_index: box }) });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
function firstBox(clip, kind) {
  const mid = Math.floor(clip.frames.length / 2);
  for (let d = 0; d < clip.frames.length; d++) for (const f of [mid - d, mid + d]) {
    if (f < 0 || f >= clip.frames.length) continue;
    const j = clip.frames[f].boxes.findIndex((b) => b.kind === kind);
    if (j >= 0) return [f, j];
  }
  return null;
}
const logx = (f, x0, x1) => x0 + (Math.log10(Math.max(f, 1)) / 4) * (x1 - x0);
function blades(ctx, cx, cy, R, ang, alpha, color) {
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(ang); ctx.globalAlpha = alpha; ctx.fillStyle = color;
  for (const sgn of [1, -1]) { ctx.beginPath(); ctx.moveTo(0, 0); ctx.bezierCurveTo(sgn * R * 0.25, -sgn * R * 0.12, sgn * R * 0.8, -sgn * R * 0.16, sgn * R, -sgn * R * 0.05); ctx.bezierCurveTo(sgn * R * 0.8, sgn * R * 0.08, sgn * R * 0.25, sgn * R * 0.1, 0, 0); ctx.fill(); }
  ctx.restore();
}
function specPlot(ctx, d, box, opt) {
  const [x0, y0, x1, y1] = box, f0 = opt.f0 ?? 0, f1 = opt.f1 ?? 1200, lo = opt.lo ?? -1, hi = opt.hi ?? 4;
  const X = (f) => x0 + (f - f0) / (f1 - f0) * (x1 - x0), Y = (v) => y1 - (Math.log10(Math.max(v, 10 ** lo)) - lo) / (hi - lo) * (y1 - y0);
  const b0 = Math.max(150, f0), b1 = Math.min(1000, f1);
  if (b1 > b0) { ctx.fillStyle = "rgba(255,90,31,.10)"; ctx.fillRect(X(b0), y0, X(b1) - X(b0), y1 - y0); }
  ctx.strokeStyle = d.clear ? HUM : INK; ctx.lineWidth = 2.2; ctx.beginPath();
  let first = true;
  d.power.forEach((p, k) => { const f = k * d.df; if (f < f0 || f > f1) return; const x = X(f), y = Y(p); if (first) ctx.moveTo(x, y); else ctx.lineTo(x, y); first = false; });
  ctx.stroke();
  ctx.fillStyle = "#777"; ctx.font = "400 18px 'JetBrains Mono', monospace";
  (opt.ticks || [0, 300, 600, 900, 1200]).forEach((f) => ctx.fillText(String(f), X(f) - 14, y1 + 22));
  if (d.clear && d.peak_hz > 0) {
    const pv = d.power[Math.round(d.peak_hz / d.df)] || 1;
    ctx.save(); ctx.shadowColor = HUM; ctx.shadowBlur = 22; ctx.fillStyle = HUM; ctx.beginPath(); ctx.arc(X(d.peak_hz), Y(pv), 8, 0, 7); ctx.fill(); ctx.restore();
    ctx.fillStyle = HUM; ctx.font = "500 26px 'JetBrains Mono', monospace"; ctx.fillText(`${Math.round(d.peak_hz)} Hz`, Math.min(X(d.peak_hz) + 14, x1 - 120), Math.max(Y(pv) + 8, y0 + 24));
  }
  return { X, Y };
}

const M = { started: false };
async function slideMath() {
  if (M.started) return;
  M.started = true;
  const sm = await fetch("/api/summary").then((r) => r.json());
  const ht = sm.hum_test;
  M.fs = ht.fs_hz; M.amb = ht.ambiguous_score; M.clear = ht.clear_score; M.local = ht.local_hz;
  const k = Math.round(HZ / 30), alias = Math.abs(HZ - k * 30);
  $("fx-nyq").innerHTML = `f<sub>alias</sub> = |f &minus; k&middot;30| = |${Math.round(HZ)} &minus; ${k}&middot;30| = ${alias.toFixed(1)} Hz &nbsp;&middot;&nbsp; f<sub>Nyq</sub> = f<sub>s</sub>/2 : 15 Hz vs ${M.fs / 2000} kHz`;
  const [hf, hb] = firstBox(hero, "drone"), bgb = firstBox(bg, "other");
  const fCloud = hero.frames.findIndex((f) => f.t === hero.cloud.t_end);
  const [d100, dbg, d40] = await Promise.all([getSpec(hero, hf, hb, 100), bgb ? getSpec(bg, bgb[0], bgb[1], 100) : null,
    getSpec(hero, fCloud >= 0 ? fCloud : hf, fCloud >= 0 ? Math.max(0, hero.frames[fCloud].boxes.findIndex((b) => b.kind === "drone")) : hb, hero.cloud.ms)]);
  M.d100 = d100; M.dbg = dbg; M.d40 = d40;
  $("sr-math-live").textContent = `Live numbers: measured blade-pass ${HZ} Hz aliases at 30 fps to ${alias.toFixed(1)} Hz (k = ${k}). Event bins of ${1e3 / M.fs} ms give a Nyquist limit of ${M.fs / 2} Hz. Drone box score at 100 ms: ${fmt(d100.snr, 1)} (hum above ${M.clear}); no-drone box score: ${dbg ? fmt(dbg.snr, 1) : "n/a"} (ambiguous above ${M.amb}).`;

  const nyq = $("nyq"), nc = nyq.getContext("2d");
  const drawNyq = (t) => {
    const W = nyq.width;
    nc.fillStyle = "#FEFEFE"; nc.fillRect(0, 0, W, nyq.height);
    const th = (tt) => 2 * Math.PI * (HZ / 2) * tt, R = 92;
    nc.strokeStyle = "#E4E4E4"; nc.lineWidth = 2;
    [[170, 130], [470, 130]].forEach(([x, y]) => { nc.beginPath(); nc.arc(x, y, R + 6, 0, 7); nc.stroke(); });
    for (let s = 0; s < 24; s++) blades(nc, 170, 130, R, th(t + s / 60 / 24), 0.07, INK);
    blades(nc, 470, 130, R, th(Math.floor(t * 30) / 30), 0.9, INK);
    [[170, 130], [470, 130]].forEach(([x, y]) => { nc.fillStyle = "#2a2a2a"; nc.beginPath(); nc.arc(x, y, 12, 0, 7); nc.fill(); });
    nc.font = "500 30px 'JetBrains Mono', monospace";
    nc.fillStyle = HUM; nc.fillText(`${Math.round(HZ)} Hz`, 640, 110);
    nc.fillStyle = INK; nc.fillText(`${alias.toFixed(1)} Hz`, 640, 170);
    nc.font = "400 20px 'JetBrains Mono', monospace"; nc.fillStyle = "#777";
    nc.fillText("real", 145, 22); nc.fillText("30 fps", 437, 22);
    nc.fillText("real", 800, 110); nc.fillText("seen", 800, 170);
    const ax0 = 40, ax1 = W - 30, ay = 330;
    nc.fillStyle = "rgba(255,90,31,.14)"; nc.fillRect(ax0, ay - 34, logx(M.fs / 2, ax0, ax1) - ax0, 26);
    nc.fillStyle = "#CFCFCF"; nc.fillRect(ax0, ay - 34, logx(15, ax0, ax1) - ax0, 26);
    nc.fillStyle = "#444"; nc.font = "500 16px 'JetBrains Mono', monospace";
    nc.fillText("≤15", ax0 + 6, ay - 15); nc.fillText(`events ≤${M.fs / 2000} kHz`, logx(M.fs / 2, ax0, ax1) - 190, ay - 15);
    nc.strokeStyle = INK; nc.lineWidth = 2; nc.beginPath(); nc.moveTo(ax0, ay); nc.lineTo(ax1, ay); nc.stroke();
    nc.font = "400 16px 'JetBrains Mono', monospace"; nc.fillStyle = "#777";
    [1, 10, 100, 1000, 10000].forEach((f) => { const x = logx(f, ax0, ax1); nc.fillRect(x - 1, ay, 2, 8); nc.fillText(f >= 1000 ? f / 1000 + "k" : String(f), x - 10, ay + 28); });
    const xh = logx(HZ, ax0, ax1), xa = logx(alias, ax0, ax1);
    nc.strokeStyle = HUM; nc.lineWidth = 2.5; nc.setLineDash([6, 5]); nc.beginPath(); nc.moveTo(xh, ay - 38); nc.quadraticCurveTo((xh + xa) / 2, ay - 110, xa + 6, ay - 38); nc.stroke(); nc.setLineDash([]);
    nc.fillStyle = HUM; nc.beginPath(); nc.arc(xh, ay, 8, 0, 7); nc.fill();
    nc.fillStyle = INK; nc.beginPath(); nc.arc(xa, ay, 7, 0, 7); nc.fill();
  };

  const ft = $("ft"), fc = ft.getContext("2d");
  const N = Math.round(hero.cloud.ms * M.fs / 1000), sig = new Float32Array(N);
  for (let i = 0; i < cropBuf.length / 4; i++) sig[Math.min(N - 1, Math.floor(cropBuf[4 * i + 2] / (hero.cloud.ms * 1000) * N))] += cropBuf[4 * i + 3] ? 1 : -1;
  const smax = Math.max(...sig.map(Math.abs)) || 1;
  const hann = (n) => 0.5 - 0.5 * Math.cos(2 * Math.PI * n / (N - 1));
  M.stage = 0;
  const ftb = $("ftbtns");
  const drawFt = () => {
    const W = ft.width, H = ft.height;
    [...ftb.children].forEach((b, j) => b.setAttribute("aria-pressed", String(j === M.stage)));
    fc.fillStyle = "#FEFEFE"; fc.fillRect(0, 0, W, H);
    const top = M.stage < 2, y0 = top ? 30 : 16, hh = top ? 300 : 120, mid = y0 + hh / 2, bw = (W - 60) / N;
    for (let n = 0; n < N; n++) {
      const w = M.stage >= 1 ? hann(n) : 1, v = sig[n] / smax * (hh / 2 - 6), vw = v * w;
      if (M.stage >= 1) { fc.fillStyle = "#E6E6E6"; fc.fillRect(30 + n * bw, v >= 0 ? mid - v : mid, Math.max(bw, 1), Math.abs(v)); }
      fc.fillStyle = v >= 0 ? INK : OFF; fc.fillRect(30 + n * bw, vw >= 0 ? mid - vw : mid, Math.max(bw, 1), Math.abs(vw));
    }
    if (M.stage >= 1) { fc.strokeStyle = HUM; fc.lineWidth = 2.5; fc.beginPath(); for (let n = 0; n < N; n++) { const x = 30 + n * bw, y = mid - hann(n) * (hh / 2 - 6); if (n) fc.lineTo(x, y); else fc.moveTo(x, y); } fc.stroke(); }
    fc.fillStyle = "#777"; fc.font = "400 18px 'JetBrains Mono', monospace"; fc.fillText("0", 30, y0 + hh + 20); fc.fillText(`${hero.cloud.ms} ms`, W - 110, y0 + hh + 20);
    if (M.stage === 2) {
      fc.fillStyle = INK; fc.font = "500 20px 'JetBrains Mono', monospace"; fc.fillText("cv.dft ↓", W / 2 - 40, 180);
      specPlot(fc, M.d40, [40, 196, W - 20, H - 34], {});
    }
  };
  ["x(t)", "·w(t)", "|X(f)|²"].forEach((lab, j) => { const b = el("button", "btn", lab); b.addEventListener("click", () => { M.stage = j; M.ftHold = performance.now() + 8000; drawFt(); }); ftb.append(b); });

  const snr = $("snr"), scx = snr.getContext("2d");
  const drawSnr = () => {
    const W = snr.width, H = snr.height, d = M.d100;
    scx.fillStyle = "#FEFEFE"; scx.fillRect(0, 0, W, H);
    const f0 = Math.max(0, d.peak_hz - 160), f1 = d.peak_hz + 160;
    scx.fillStyle = "rgba(30,30,30,.05)";
    const pre = (f) => 40 + (f - f0) / (f1 - f0) * 560;
    scx.fillRect(pre(d.peak_hz - M.local), 20, pre(d.peak_hz + M.local) - pre(d.peak_hz - M.local), H - 60);
    const { X, Y } = specPlot(scx, d, [40, 20, 600, H - 40], { f0, f1, ticks: [Math.round(d.peak_hz - 100), Math.round(d.peak_hz), Math.round(d.peak_hz + 100)] });
    const loc = d.power.filter((p, k2) => Math.abs(k2 * d.df - d.peak_hz) <= M.local).slice().sort((a, b) => a - b);
    const med = loc[Math.floor(loc.length / 2)];
    scx.strokeStyle = INK; scx.lineWidth = 2; scx.setLineDash([8, 6]); scx.beginPath(); scx.moveTo(X(d.peak_hz - M.local), Y(med)); scx.lineTo(X(d.peak_hz + M.local), Y(med)); scx.stroke(); scx.setLineDash([]);
    scx.fillStyle = INK; scx.font = "500 18px 'JetBrains Mono', monospace"; scx.fillText("median", X(d.peak_hz + M.local) - 70, Y(med) + 24);
    const gx = 770, gy0 = 24, gy1 = H - 40, GY = (v) => gy1 - Math.log10(Math.max(v, 1)) / 4 * (gy1 - gy0);
    scx.fillStyle = "rgba(255,90,31,.16)"; scx.fillRect(gx - 26, gy0, 52, GY(M.clear) - gy0);
    scx.fillStyle = "#E6E6E6"; scx.fillRect(gx - 26, GY(M.clear), 52, GY(M.amb) - GY(M.clear));
    scx.strokeStyle = INK; scx.lineWidth = 2; scx.strokeRect(gx - 26, gy0, 52, gy1 - gy0);
    scx.font = "500 18px 'JetBrains Mono', monospace"; scx.fillStyle = INK;
    [[M.amb, `${M.amb}`], [M.clear, `${M.clear}`]].forEach(([v, l]) => { scx.fillRect(gx - 34, GY(v) - 1, 68, 2); scx.fillText(l, gx - 84, GY(v) + 6); });
    const mark = (v, color, lab) => { const y = GY(v); scx.fillStyle = color; scx.beginPath(); scx.moveTo(gx + 30, y); scx.lineTo(gx + 44, y - 9); scx.lineTo(gx + 44, y + 9); scx.fill(); scx.font = "500 18px 'JetBrains Mono', monospace"; scx.fillText(`${lab} ${Math.round(v)}`, gx + 48, y + 7); };
    mark(d.snr, HUM, "drone");
    if (M.dbg) mark(M.dbg.snr, INK, "none");
  };

  const wins = [20, 50, 100, 150, 200, 300], mw = $("mwin"), mp = $("mwplot"), mc = mp.getContext("2d");
  const drawWin = async () => {
    const w = wins[+mw.value]; $("mwinv").textContent = `${w} ms`;
    mw.setAttribute("aria-valuetext", `${w} ms`);
    const id = (M.wreq = (M.wreq || 0) + 1);
    const d = await getSpec(hero, hf, hb, w);
    if (id !== M.wreq) return;
    mc.fillStyle = "#FEFEFE"; mc.fillRect(0, 0, mp.width, mp.height);
    specPlot(mc, d, [40, 14, mp.width - 260, mp.height - 30], { f0: 100, f1: 700, ticks: [100, 300, 500, 700] });
    mc.fillStyle = INK; mc.font = "500 30px 'JetBrains Mono', monospace"; mc.fillText(`Δf ${(1000 / w).toFixed(1)} Hz`, mp.width - 240, 60);
    mc.fillStyle = d.clear ? HUM : "#777"; mc.font = "500 24px 'JetBrains Mono', monospace"; mc.fillText(`score ${Math.round(d.snr)}`, mp.width - 240, 110);
    mc.fillStyle = "#777"; mc.font = "400 18px 'JetBrains Mono', monospace"; mc.fillText(`${d.compute_ms ?? "–"} ms live`, mp.width - 240, 150);
  };
  mw.addEventListener("input", () => { clearTimeout(M.wt); M.wt = setTimeout(drawWin, 120); });
  drawWin();

  const eps = tracesDoc.episodes || [];
  const ep = eps.find((e) => e.episode === hero.id && e.planner !== "rule") || eps[0];
  if (ep) {
    const alias2 = {}, key = (b) => JSON.stringify(b), root = (k2) => (alias2[k2] ? root(alias2[k2]) : k2);
    const groups = {}, order = [], alerted = new Set();
    ep.rows.filter((r) => r.kind === "step" && r.guard === "ok").forEach((r) => {
      if (r.tool === "track" && r.result && r.result.box) alias2[key(r.result.box)] = key(r.args.box);
      if (["box_spectrum", "request_window"].includes(r.tool) && r.result && r.result.verdict) {
        const g = root(key(r.args.box)); if (!groups[g]) { groups[g] = []; order.push(g); } groups[g].push(r);
      }
      if (r.tool === "raise_alert") alerted.add(root(key(r.args.box)));
    });
    $("chain").replaceChildren(...order.map((g) => {
      const row = el("div", "row"); row.append(icon(alerted.has(g) ? "i-drone" : "i-frame"));
      groups[g].forEach((r, j) => {
        if (j) { const a = el("span", "", "→"); if (r.tool === "request_window") a.append(icon("i-clock")); row.append(a); }
        const c = el("span", "chip " + r.result.verdict, `${r.result.window_ms}ms·${Math.round(r.result.snr)}`);
        c.title = `step ${r.step}: ${r.tool}, ${r.result.window_ms} ms window, score ${r.result.snr}, ${r.result.verdict}, ${r.result.peak_hz} Hz`;
        row.append(c);
      });
      row.append(el("span", "", "→"), icon(alerted.has(g) ? "i-alert" : "i-x"));
      return row;
    }));
    $("chain").title = `Real ${ep.planner} trace, episode ${ep.episode}`;
  }

  const ops = [["i-hist", "calcHist"], ["i-wave", "dft"], ["i-blobs", "connectedComponentsWithStats"], ["i-net", "dnn"]];
  const row = $("cvrow");
  ops.forEach(([ic, n], j) => { if (j) row.append(el("span", "arr", "→")); const o = el("span", "op"); o.append(icon(ic), document.createTextNode("cv." + n)); row.append(o); });
  const opEls = [...row.querySelectorAll(".op")];
  const t0 = performance.now();
  const loop = (now) => {
    if (current === 3) {
      const t = (now - t0) / 1000;
      drawNyq(reduce ? 0 : t);
      if (!reduce && !(M.ftHold > now)) { const st = Math.floor(t / 2.4) % 3; if (st !== M.stage) { M.stage = st; drawFt(); } }
      opEls.forEach((o, j) => o.classList.toggle("lit", reduce ? true : Math.floor(t / 0.8) % (opEls.length + 1) >= j + 1));
    }
    requestAnimationFrame(loop);
  };
  drawFt(); drawSnr(); requestAnimationFrame(loop);
}

const deck = $("deck"), slides = [...deck.querySelectorAll(".slide")];
let current = -1;
const pager = $("pager");
slides.forEach((s, i) => { const b = el("button"); b.setAttribute("aria-label", `Go to slide ${i + 1}: ${s.getAttribute("aria-label")}`); b.addEventListener("click", () => go(i)); pager.append(b); });
function go(i, smooth = !reduce) { i = Math.max(0, Math.min(slides.length - 1, i)); deck.scrollTo({ left: i * deck.clientWidth, behavior: smooth ? "smooth" : "auto" }); enter(i); }
function enter(i) {
  if (i === current) return;
  current = i;
  [...pager.children].forEach((b, j) => b.setAttribute("aria-current", String(j === i)));
  document.querySelectorAll(".steps button").forEach((b) => b.classList.toggle("on", +b.dataset.go === i));
  $("prev").disabled = i === 0; $("next").disabled = i === slides.length - 1;
  history.replaceState(null, "", "#" + slides[i].id);
  slides.forEach((s, j) => s.toggleAttribute("inert", j !== i));
  if (i === 1) slide2();
  if (i === 2) Object.values(spec.sides).forEach((s) => { if (s.data && !s.played) { s.played = true; animateSpec(s.svg, s.data, true); } });
  if (i === 3) slideMath();
  if (i === 4) schedule(); else clearTimeout(agent.timer);
  if (i === 5) requestAnimationFrame(growBars);
}
deck.addEventListener("scroll", () => { clearTimeout(deck._t); deck._t = setTimeout(() => enter(Math.round(deck.scrollLeft / deck.clientWidth)), 80); });
$("prev").addEventListener("click", () => go(current - 1));
$("next").addEventListener("click", () => go(current + 1));
document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); go(+b.dataset.go); }));
addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input")) return;
  const k = e.key;
  if (k === "ArrowRight" || k === "PageDown") { e.preventDefault(); go(current + 1); }
  else if (k === "ArrowLeft" || k === "PageUp") { e.preventDefault(); go(current - 1); }
  else if (k === "Home") { e.preventDefault(); go(0); }
  else if (k === "End") { e.preventDefault(); go(slides.length - 1); }
});
let wheelLock = 0;
deck.addEventListener("wheel", (e) => {
  if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
  const s = slides[current];
  if (s.scrollHeight > s.clientHeight + 4) { const atTop = s.scrollTop <= 0, atBottom = s.scrollTop + s.clientHeight >= s.scrollHeight - 2; if ((e.deltaY > 0 && !atBottom) || (e.deltaY < 0 && !atTop)) return; }
  e.preventDefault();
  const now = performance.now();
  if (now < wheelLock || Math.abs(e.deltaY) < 8) return;
  wheelLock = now + 750;
  go(current + (e.deltaY > 0 ? 1 : -1));
}, { passive: false });
addEventListener("resize", () => deck.scrollTo({ left: current * deck.clientWidth }));
let drag = null;
deck.addEventListener("pointerdown", (e) => { if (e.pointerType === "touch" || e.button !== 0 || e.target.closest("button,input,a,#cloud,canvas.thumb,.thumb")) return; drag = { x: e.clientX, y: e.clientY }; });
addEventListener("pointerup", (e) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = null; if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(current + (dx < 0 ? 1 : -1)); });

slide1();
slide3();
slide4();
slide5();
const start = Math.max(0, slides.findIndex((s) => "#" + s.id === location.hash));
go(start, false);

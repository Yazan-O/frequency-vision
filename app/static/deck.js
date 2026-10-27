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
const minPx = (ctx, f) => { const cw = ctx.canvas.clientWidth; if (!cw || cw >= 600) return f; const m = 12 * ctx.canvas.width / cw; return f.replace(/(\d+(?:\.\d+)?)px/, (_, v) => `${Math.ceil(Math.max(+v, m))}px`); };
const txt = (ctx, s, x, y, o = {}) => { ctx.save(); ctx.font = minPx(ctx, o.font || "400 18px 'JetBrains Mono', monospace"); ctx.textAlign = o.align || "left"; ctx.lineWidth = 6; ctx.lineJoin = "round"; ctx.strokeStyle = o.back || "#FEFEFE"; ctx.strokeText(s, x, y); ctx.fillStyle = o.color || "#777"; ctx.fillText(s, x, y); ctx.restore(); };
if (reduce) document.querySelectorAll("svg").forEach((s) => s.pauseAnimations && s.pauseAnimations());

const [clipsDoc, tracesDoc] = await Promise.all([fetch("/data/clips.json").then((r) => r.json()), fetch("/data/traces.json").then((r) => r.json())]);
const clips = clipsDoc.clips;
const hzOf = (c) => (c.hum && c.hum.median_hz) || null;
const droneClips = clips.filter((c) => c.role === "demo" && hzOf(c) && c.cloud.crop).sort((a, b) => hzOf(a) - hzOf(b));
const bg = clips.find((c) => !c.drone) || clips[clips.length - 1];
const nice = (s) => String(s).replace(/cineape20ger/gi, "Cineape20 (GER)").replace(/cineape20(?! \(GER\))/gi, "Cineape20");
const modelOf = (c) => nice((c.hum && c.hum.model) || (c.classes && c.classes[0]) || "drone");
const showHz = (d, ref) => Math.round(ref && Math.abs(d.peak_hz - ref) <= 1.5 * Math.max(d.df || 0, 1) ? ref : d.peak_hz);
const shortName = (c) => modelOf(c).replace(/^(DJI|DarwinFPV|Betafpv)\s+/i, "");
const cur = { clip: null, crop: null, HZ: null, imgs: null, i: 0 };
const bufs = {};
const bufOf = (src) => bufs[src] || (bufs[src] = fetch("/" + src).then((r) => r.arrayBuffer()).then((b) => new Uint16Array(b)));
const summaryP = fetch("/api/summary").then((r) => r.json());
const specCache = new Map();
const specKey = (b) => JSON.stringify({ clip: b.clip, window_ms: b.window_ms, t: b.t, box: b.box, frame: b.frame, box_index: b.box_index });
const postSpec = (k, signal) => fetch("/api/spectrum", { method: "POST", headers: { "Content-Type": "application/json" }, body: k, signal }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
const fetchSpec = (body, signal) => {
  const k = specKey(body);
  if (specCache.has(k)) return specCache.get(k);
  if (signal) return postSpec(k, signal).then((d) => { specCache.set(k, Promise.resolve(d)); return d; });
  const p = postSpec(k).catch((e) => { specCache.delete(k); throw e; });
  specCache.set(k, p);
  return p;
};

const tip = $("tip");
function tipOn(b, text) {
  const show = () => { const r = b.getBoundingClientRect(); tip.textContent = typeof text === "function" ? text() : text; tip.hidden = false; tip.style.left = Math.max(8, Math.min(innerWidth - 290, r.right - 280)) + "px"; tip.style.top = r.bottom + 6 + "px"; };
  const hide = () => { tip.hidden = true; };
  b.addEventListener("mouseenter", show); b.addEventListener("focus", show);
  b.addEventListener("mouseleave", hide); b.addEventListener("blur", hide);
  b.addEventListener("click", () => (tip.hidden ? show() : hide()));
}
document.querySelectorAll("[data-prov]").forEach((b) => tipOn(b, () => `${cur.clip.provenance} · ${cur.clip.source} · seq ${cur.clip.seq}`));

function loadFrames(clip) {
  if (!clip._imgs) clip._imgs = clip.frames.map((f) => { const i = new Image(); i.src = "/" + f.src; return i; });
  return clip._imgs;
}

function rhythm(nb) {
  const d = new Float32Array(nb), span = cur.clip.cloud.ms * 1000, b = cur.crop;
  if (!b) return d;
  for (let k = 0; k < b.length / 4; k++) d[Math.min(nb - 1, Math.floor(b[4 * k + 2] / span * nb))] += b[4 * k + 3] ? 1 : -1;
  return d;
}

function drawRhythm(cv, opt) {
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height, d = rhythm(80), nb = d.length, span = cur.clip.cloud.ms * 1000, HZ = cur.HZ;
  const m = Math.max(...d.map(Math.abs)) || 1, bw = W / nb, mid = H * 0.5, amp = H * (opt.dark ? 0.34 : 0.4);
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
    const back = "#0b0b0b";
    txt(ctx, "0 ms", 16, H - 26, { font: "500 28px 'JetBrains Mono', monospace", color: "#fff", back });
    txt(ctx, `${cur.clip.cloud.ms} ms`, W - 16, H - 26, { font: "500 28px 'JetBrains Mono', monospace", color: "#fff", back, align: "right" });
    txt(ctx, HZ ? `orange tick = one blade pass, every ${(1000 / HZ).toFixed(1)} ms` : "no steady rhythm", 16, 46, { font: "500 32px 'JetBrains Mono', monospace", color: HZ ? HUM : "#aaa", back });
  }
}

function slide1() {
  const cv = $("rgb"), ctx = cv.getContext("2d");
  let playing = !reduce, last = 0;
  const draw = () => {
    const clip = cur.clip, img = cur.imgs[cur.i], fr = clip.frames[cur.i];
    if (!(img && img.complete && img.naturalWidth)) return;
    ctx.drawImage(img, 0, 0, cv.width, cv.height);
    const dt = cur.det;
    if (dt && dt.clip === clip.id && dt.frame === cur.i) {
      const sx = cv.width / clip.width, sy = cv.height / clip.height;
      ctx.lineWidth = 6; ctx.strokeStyle = HUM;
      dt.boxes.forEach(([x0, y0, x1, y1], j) => {
        ctx.strokeRect(x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy);
        txt(ctx, `drone ${dt.scores[j].toFixed(2)}`, x0 * sx, Math.max(30, y0 * sy - 12), { font: "600 28px 'JetBrains Mono', monospace", color: HUM, back: "#000" });
      });
      return;
    }
    const db = fr.boxes.find((b) => b.kind === "drone");
    if (!db) return;
    const sx = cv.width / clip.width, sy = cv.height / clip.height, [x0, y0, x1, y1] = db.box;
    ctx.lineWidth = 5; ctx.strokeStyle = "#FFFFFF"; ctx.strokeRect(x0 * sx - 6, y0 * sy - 6, (x1 - x0) * sx + 12, (y1 - y0) * sy + 12);
    const k = img.naturalWidth / clip.width, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, sw = Math.max(120, (x1 - x0) * 1.2), sh = sw * 68 / 120;
    const iw = cv.width * 0.42, ih = iw * sh / sw, ix = cx * sx > cv.width / 2 ? 18 : cv.width - iw - 18, iy = cy * sy > cv.height / 2 ? 18 : cv.height - ih - 18;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, (cx - sw / 2) * k, (cy - sh / 2) * k, sw * k, sh * k, ix, iy, iw, ih);
    ctx.imageSmoothingEnabled = true;
    ctx.lineWidth = 5; ctx.strokeRect(ix, iy, iw, ih);
    ctx.beginPath(); ctx.moveTo(cx * sx, cy * sy); ctx.lineTo(ix + iw / 2, iy + ih / 2); ctx.lineWidth = 2; ctx.stroke();
  };
  cur.drawVideo = draw;
  const tick = (now) => {
    if (playing && cur.imgs && now - last >= 1000 / 15) { cur.i = (cur.i + 1) % cur.imgs.length; last = now; draw(); }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  const btn = $("play");
  const sync = () => { btn.setAttribute("aria-label", playing ? "Pause video" : "Play video"); btn.replaceChildren(icon(playing ? "i-pause" : "i-play")); };
  btn.addEventListener("click", () => { playing = !playing; cur.det = null; $("detout").textContent = ""; sync(); draw(); });
  sync();
  const dbtn = $("det"), out = $("detout");
  dbtn.addEventListener("click", async () => {
    playing = false; sync();
    const clip = cur.clip, frame = cur.i;
    dbtn.disabled = true; out.textContent = "running OpenCV dnn on the server…";
    try {
      const r = await fetch("/api/detect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip: clip.id, frame }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      cur.det = d;
      out.textContent = `${d.boxes.length} box${d.boxes.length === 1 ? "" : "es"} · ${d.latency_ms} ms · OpenCV ${d.opencv}${d.cool ? " (COOL)" : ""} dnn`;
    } catch (e) { cur.det = null; out.textContent = `detector unavailable: ${e.message}`; }
    dbtn.disabled = false; draw();
  });
  const scope = $("scope");
  let t0 = performance.now();
  const sweep = (now) => {
    if (cur.clip) drawRhythm(scope, { dark: true, head: reduce ? null : ((now - t0) / 8000) % 1 });
    if (!reduce) requestAnimationFrame(sweep);
  };
  requestAnimationFrame(sweep);
}

function applySlide1() {
  const c = cur.clip, HZ = cur.HZ, h = c.hum || {}, model = modelOf(c);
  $("headline").textContent = HZ ? `A 30 fps camera sees a blur. The event camera hears the ${shortName(c)}'s propellers.`
    : `Hard case: this ${shortName(c)} gives no clean hum.`;
  $("hz").textContent = HZ ? `${Math.round(HZ)} Hz` : "no peak";
  $("hz").classList.toggle("none", !HZ);
  $("hzbig").setAttribute("aria-label", HZ ? `${model}, FRED sequence ${c.seq}: median ${h.median_hz} Hz; ${h.n_clear} of ${h.n_windows} windows of ${h.window_ms} ms pass the hum test; one blade pass every ${(1000 / HZ).toFixed(1)} ms` : `${model}, FRED sequence ${c.seq}: ${h.n_clear} of ${h.n_windows} windows of ${h.window_ms} ms pass the hum test`);
  $("sr-hum").textContent = HZ ? `Measured blade-pass frequency inside the drone box, FRED sequence ${c.seq} (${model}): median ${h.median_hz} Hz over the ${h.n_clear} of ${h.n_windows} event windows of ${h.window_ms} ms that pass the hum test; middle half ${h.p25_hz} to ${h.p75_hz} Hz. Computed by tools/export_web.py with box_spectrum.`
    : `Hard case, FRED sequence ${c.seq} (${model}): ${h.n_clear} of ${h.n_windows} event windows of ${h.window_ms} ms pass the hum test, so no blade-pass frequency is claimed.`;
  cur.imgs = loadFrames(c); cur.i = Math.floor(c.frames.length / 2); cur.det = null; $("detout").textContent = "";
  if (!c._bound) { c._bound = true; cur.imgs.forEach((im) => im.addEventListener("load", () => { if (cur.clip === c) cur.drawVideo(); })); }
  cur.drawVideo();
}

const S = { started: false, view: "crop", labels: [] };
async function slide2() {
  if (S.started) return;
  S.started = true;
  const host = $("cloud"), lab = $("cloudlabels");
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
  const depth = 1.6;
  const label = (text, pos, cls = "") => { const e = el("span", cls, text); lab.append(e); S.labels.push({ e, pos }); };
  const points = (buf, bx0, by0, w, h, s, yOff, size, mask) => {
    const idx = [];
    for (let k = 0; k < buf.length / 4; k++) if (!mask || mask(buf[4 * k], buf[4 * k + 1])) idx.push(k);
    idx.sort((a, b) => buf[4 * a + 3] - buf[4 * b + 3]);
    const n = idx.length, span = cur.clip.cloud.ms * 1000;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3), on = new THREE.Color(INK), off = new THREE.Color("#C9C9C9");
    idx.forEach((k, j) => {
      pos[3 * j] = (buf[4 * k + 2] / span - 0.5) * depth;
      pos[3 * j + 1] = -(buf[4 * k + 1] - by0 - h / 2) * s + yOff;
      pos[3 * j + 2] = (buf[4 * k] - bx0 - w / 2) * s;
      const cc = buf[4 * k + 3] ? on : off;
      col[3 * j] = cc.r; col[3 * j + 1] = cc.g; col[3 * j + 2] = cc.b;
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    group.add(new THREE.Points(g, new THREE.PointsMaterial({ size, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.9 })));
    const hs = h * s, ws = w * s;
    group.add(new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(-depth / 2, yOff - hs / 2, -ws / 2), new THREE.Vector3(depth / 2, yOff + hs / 2, ws / 2)), new THREE.Color("#CFCFCF")));
    return { hs, ws, n };
  };
  const line = (a, b, color, opacity = 0.55) => group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: new THREE.Color(color), transparent: true, opacity })));
  async function show(view) {
    S.view = view;
    const c = cur.clip, span = c.cloud.ms * 1000, HZ = cur.HZ;
    group.clear(); lab.replaceChildren(); S.labels = [];
    const whole = view === "scene" || !cur.crop;
    const buf = whole ? await bufOf(c.cloud.scene.src) : cur.crop;
    if (c !== cur.clip || S.view !== view) return;
    const [bx0, by0, bx1, by1] = whole ? [0, 0, c.width, c.height] : c.cloud.crop.box;
    const w = bx1 - bx0, h = by1 - by0;
    const s = whole ? 1 / Math.max(w, h) : view === "duo" ? Math.min(0.42 / h, 1.4 / w) : Math.min(0.9 / h, 1.4 / w);
    const top = points(buf, bx0, by0, w, h, s, 0, whole ? 1.3 : 3.2);
    const { hs, ws } = top;
    const lo = -hs / 2;
    let base = lo;
    if (HZ && !whole) {
      const mat = new THREE.LineBasicMaterial({ color: new THREE.Color(HUM), transparent: true, opacity: 0.55 });
      const xs = [];
      for (let t = 0; t < span; t += 1e6 / HZ) { const x = (t / span - 0.5) * depth; xs.push(x); group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, lo, ws / 2), new THREE.Vector3(x, lo, -ws / 2)]), mat)); }
      const k = Math.floor(xs.length / 2) - 1, x1 = xs[k], x2 = xs[k + 1], yb = hs / 2 + 0.05, z = ws / 2;
      line(new THREE.Vector3(x1, yb, z), new THREE.Vector3(x2, yb, z), HUM, 1);
      line(new THREE.Vector3(x1, yb - 0.025, z), new THREE.Vector3(x1, yb + 0.025, z), HUM, 1);
      line(new THREE.Vector3(x2, yb - 0.025, z), new THREE.Vector3(x2, yb + 0.025, z), HUM, 1);
      label(`one blade pass, ${(1000 / HZ).toFixed(1)} ms`, new THREE.Vector3((x1 + x2) / 2, yb + 0.07, z), "hum");
    } else if (!whole) {
      label("no stripes: no steady hum", new THREE.Vector3(0, hs / 2 + 0.1, ws / 2), "hum");
    }
    if (view === "duo") {
      label(`${modelOf(c)}, drone box`, new THREE.Vector3(-depth / 2 + 0.3, hs / 2 + 0.22, ws / 2), "title");
      const sb = await bufOf(bg.cloud.scene.src);
      if (c !== cur.clip || S.view !== view) return;
      const bf = bg.frames[Math.floor(bg.frames.length / 2)], ob = bf.boxes[0] ? bf.boxes[0].box : [bg.width / 2, bg.height / 2, bg.width / 2, bg.height / 2];
      const cx = Math.min(bg.width - w / 2, Math.max(w / 2, (ob[0] + ob[2]) / 2)), cy = Math.min(bg.height - h / 2, Math.max(h / 2, (ob[1] + ob[3]) / 2));
      const px0 = cx - w / 2, py0 = cy - h / 2;
      const yOff = -(hs + 0.14);
      const low = points(sb, px0, py0, w, h, s, yOff, 3.2, (x, y) => x >= px0 && x < px0 + w && y >= py0 && y < py0 + h);
      label(`no drone, same size patch (${low.n} events)`, new THREE.Vector3(-depth / 2 + 0.3, yOff + hs / 2 + 0.08, ws / 2), "title");
      base = yOff - hs / 2;
      controls.target.set(0, yOff / 2, 0);
    } else controls.target.set(0, 0, 0);
    group.add(new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(-depth / 2, base - 0.04, ws / 2 + 0.04), depth, new THREE.Color(INK), 0.06, 0.03));
    label(`time, ${c.cloud.ms} ms`, new THREE.Vector3(0, base - 0.11, ws / 2 + 0.04));
    label("x", new THREE.Vector3(depth / 2 + 0.06, base - 0.02, 0));
    label("y", new THREE.Vector3(depth / 2 + 0.06, 0, ws / 2 + 0.03));
    fit();
  }
  const fit = () => { const a = camera.aspect || 1, d = 2.3 * Math.max(1, 1.8 / a) * (S.view === "duo" ? 1.15 : 1); camera.position.set(0.15 * d, 0.13 * d + controls.target.y, d); controls.update(); };
  const resize = () => { const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  new ResizeObserver(resize).observe(host); resize();
  const v = new THREE.Vector3();
  const loop = () => {
    if (current === 1) {
      controls.update(); renderer.render(scene, camera);
      const W = host.clientWidth, H = host.clientHeight;
      S.labels.forEach(({ e, pos }) => { v.copy(pos).project(camera); e.style.left = ((v.x + 1) / 2 * W).toFixed(1) + "px"; e.style.top = ((1 - v.y) / 2 * H).toFixed(1) + "px"; });
    }
    requestAnimationFrame(loop);
  };
  loop();
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-view]").forEach((o) => { const sel = o === b; o.classList.toggle("on", sel); o.setAttribute("aria-pressed", String(sel)); });
    show(b.dataset.view);
  }));
  S.show = show;
  await show(cur.crop ? "crop" : "scene");
}

function applySlide2() {
  const c = cur.clip, HZ = cur.HZ;
  $("hl2").textContent = HZ ? `Each dot is a pixel change. The propellers draw ${Math.round(HZ)} stripes a second.`
    : `Each dot is a pixel change. No stripes: no steady hum.`;
  drawRhythm($("bars"), { dark: false, head: null });
  if (S.started) S.show(S.view);
}

const spec = { win: 100, sides: {} };
function slide3() {
  const wins = $("winbtns");
  [20, 50, 100, 300].forEach((w) => {
    const b = el("button", "btn", w === 100 ? "100 ms · best" : `${w} ms`);
    b.setAttribute("aria-pressed", String(w === spec.win));
    if (w === 100) b.title = "Best window on the FRED test split: area under the curve 0.758 against the busiest no-drone patch (50 ms: 0.753, 20 ms: 0.702). Source: results/engine/summary.json";
    b.addEventListener("click", () => { if (spec.win === w) return; spec.win = w; [...wins.querySelectorAll("button")].forEach((o) => o.setAttribute("aria-pressed", String(o === b))); Object.values(spec.sides).forEach((s) => s.run()); });
    wins.append(b);
  });
  document.querySelectorAll(".side").forEach((host) => {
    const isDrone = host.dataset.side === "drone";
    const st = { clip: null, frame: 0, box: 0, req: 0, played: false };
    const head = el("div", "head");
    const verdict = el("span", "verdict", "…"); const score = { set textContent(v) { verdict.title = v; } };
    const prov = el("button", "prov"); prov.append(icon("i-data")); prov.setAttribute("aria-label", "Data source");
    tipOn(prov, () => `${st.clip.provenance} · ${st.clip.title} · seq ${st.clip.seq}`);
    head.append(verdict, prov);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 600 300"); svg.setAttribute("class", "spec"); svg.setAttribute("role", "img");
    const row = el("div", "thumbrow");
    const thumb = el("div", "thumb"); const cv = el("canvas"); cv.width = 640; cv.height = 360; cv.setAttribute("aria-label", "Frame with clickable boxes"); thumb.append(cv);
    const right = el("div", "right");
    const boxes = el("div", "boxbtns"); const range = el("input"); range.type = "range"; range.min = 0;
    range.setAttribute("aria-label", "Frame");
    right.append(boxes, range); row.append(thumb, right);
    host.append(head, svg, row);
    const ctx = cv.getContext("2d");
    const firstFrame = (clip) => {
      const mid = Math.floor(clip.frames.length / 2);
      for (let d = 0; d < clip.frames.length; d++) for (const f of [mid - d, mid + d]) if (f >= 0 && f < clip.frames.length && clip.frames[f].boxes.length) return f;
      return mid;
    };
    const paint = () => {
      const clip = st.clip, f = clip.frames[st.frame], img = loadFrames(clip)[st.frame];
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
        const btn = el("button", "btn chip", b.kind === "drone" ? "drone" : `box ${i + 1}`);
        btn.setAttribute("aria-label", `${b.kind === "drone" ? "Drone box (FRED annotation)" : b.label} ${Math.round(b.box[2] - b.box[0])} by ${Math.round(b.box[3] - b.box[1])} px`);
        btn.setAttribute("aria-pressed", String(i === st.box));
        btn.addEventListener("click", () => { st.box = i; paint(); st.run(); });
        return btn;
      }));
    };
    cv.addEventListener("click", (e) => {
      const clip = st.clip, r = cv.getBoundingClientRect(), f = clip.frames[st.frame];
      const x = (e.clientX - r.left) / r.width * clip.width, y = (e.clientY - r.top) / r.height * clip.height, tol = 18 / r.width * clip.width;
      let best = -1, area = Infinity;
      f.boxes.forEach((b, i) => { const [x0, y0, x1, y1] = b.box; if (x >= x0 - tol && x <= x1 + tol && y >= y0 - tol && y <= y1 + tol && (x1 - x0) * (y1 - y0) < area) { best = i; area = (x1 - x0) * (y1 - y0); } });
      if (best >= 0) { st.box = best; paint(); st.run(); }
    });
    range.addEventListener("input", () => { st.frame = +range.value; st.box = 0; paint(); clearTimeout(st.deb); st.deb = setTimeout(() => st.run(), 150); });
    st.run = async () => {
      const clip = st.clip, f = clip.frames[st.frame], b = f.boxes[st.box];
      const id = ++st.req;
      if (st.ctl) st.ctl.abort();
      st.ctl = new AbortController();
      st.data = null; svg._tok = (svg._tok || 0) + 1; svg.innerHTML = "";
      verdict.className = "verdict"; verdict.textContent = "…";
      if (!b) { verdict.textContent = "–"; score.textContent = "no box in this frame"; return; }
      try {
        const d = await fetchSpec({ clip: clip.id, box: b.box, t: f.t, window_ms: spec.win, frame: st.frame, box_index: st.box }, st.ctl.signal);
        if (id !== st.req || clip !== st.clip) return;
        st.data = d;
        verdict.className = "verdict" + (d.clear ? " hum" : "");
        verdict.textContent = `${isDrone ? "Drone box" : "No drone"}: ${d.clear ? `${showHz(d, hzOf(clip))} Hz` : "no hum"}`;
        score.textContent = `score ${fmt(d.snr, 0)} (hum ≥ ${d.clear_snr}) · ${d.n_events.toLocaleString()} events`;
        verdict.title += ` · peak ${d.peak_hz} Hz, ${d.mode === "live" ? `computed live in ${d.compute_ms} ms by ${d.source}` : d.source}`;
        svg.setAttribute("aria-label", `${isDrone ? "Drone" : "No-drone"} clip box spectrum: ${d.clear ? "hums at " + showHz(d, hzOf(clip)) + " Hz" : "no hum"}, peak score ${fmt(d.snr, 1)}, ${d.n_events} events, ${d.window_ms} ms window, ${d.mode}`);
        animateSpec(svg, d, current === 2 || st.played, showHz(d, hzOf(clip)));
        st.played = st.played || current === 2;
      } catch (e) { if (id === st.req && e.name !== "AbortError") verdict.textContent = "offline"; }
    };
    st.setClip = (clip) => {
      st.clip = clip; st.frame = firstFrame(clip);
      st.box = Math.max(0, clip.frames[st.frame].boxes.findIndex((b) => b.kind === (isDrone ? "drone" : "other")));
      range.max = clip.frames.length - 1; range.value = st.frame;
      svg.setAttribute("aria-label", `Event spectrum of a box in the ${isDrone ? "drone" : "no-drone"} clip, FRED sequence ${clip.seq}`);
      paint(); st.run();
    };
    st.svg = svg; st.isDrone = isDrone;
    spec.sides[host.dataset.side] = st;
  });
  spec.sides.bg.setClip(bg);
}

function animateSpec(svg, d, animate, hzLabel) {
  const W = 600, H = 300, L = 44, R = 8, T = 10, B = 40, fmax = 1200;
  const X = (f) => L + (f / fmax) * (W - L - R);
  const Y = (v) => T + (1 - (Math.log10(Math.max(v, 0.1)) + 1) / 5) * (H - T - B);
  let s = `<rect class="band" x="${X(150)}" y="${T}" width="${X(1000) - X(150)}" height="${H - T - B}"/>`;
  [1, 10, 100, 1000].forEach((v) => { s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#ECECEC"/><text x="${L - 5}" y="${Y(v) + 4}" text-anchor="end">${v >= 1000 ? "1k" : v}</text>`; });
  [0, 300, 600, 900, 1200].forEach((f) => { s += `<text x="${f === 1200 ? W - R : X(f)}" y="${H - 24}" text-anchor="${f === 1200 ? "end" : "middle"}">${f}</text>`; });
  s += `<text x="${W - R}" y="${H - 7}" text-anchor="end">Hz</text>`;
  s += `<path class="curve${d.clear ? " hum" : ""}" d=""/>`;
  const tok = svg._tok = (svg._tok || 0) + 1;
  svg.innerHTML = s;
  const path = svg.querySelector("path");
  const pts = d.power.map((p, k) => [X(k * d.df), Math.log10(Math.max(p, 0.1))]).filter(([x]) => x <= X(fmax));
  const base = -1, k = Math.round(d.peak_hz / d.df), pv = d.power[k] || 1;
  const frame = (e) => {
    path.setAttribute("d", "M" + pts.map(([x, lv]) => `${x.toFixed(1)},${(T + (1 - (base + (lv - base) * e + 1) / 5) * (H - T - B)).toFixed(1)}`).join("L"));
  };
  const finish = () => {
    if (!d.clear || svg._tok !== tok) return;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const px = X(d.peak_hz), py = Y(pv), right = px < W - 130;
    g.innerHTML = `<circle class="pk pulse" cx="${px}" cy="${py}" r="9" filter="url(#glow)"/><circle class="pk" cx="${px}" cy="${py}" r="4.5"/><text class="pkl" x="${right ? px + 14 : px - 14}" y="${Math.max(py - 12, T + 18)}" text-anchor="${right ? "start" : "end"}">${hzLabel ?? Math.round(d.peak_hz)} Hz</text>`;
    svg.append(g);
  };
  if (!animate || reduce) { frame(1); finish(); return; }
  const t0 = performance.now();
  const step = (now) => { if (svg._tok !== tok) return; const u = Math.min((now - t0) / 1100, 1), e = 1 - Math.pow(1 - u, 3); frame(e); if (u < 1) requestAnimationFrame(step); else finish(); };
  requestAnimationFrame(step);
}

const STAGE = { detect_frame: "look", track: "look", box_spectrum: "listen", request_window: "listen", frequency_map: "listen", event_map: "listen", ask_human: "decide", raise_alert: "decide", finish: "decide" };
const TOOL_ICON = { detect_frame: "i-camera", track: "i-track", box_spectrum: "i-sine", request_window: "i-clock", frequency_map: "i-events", event_map: "i-events", ask_human: "i-human", raise_alert: "i-alert", finish: "i-flag" };
const ACT = { detect_frame: "camera", track: "follow", box_spectrum: "listen", request_window: "listen longer", frequency_map: "hum map", event_map: "motion map", ask_human: "ask you", raise_alert: "alert", finish: "finish" };
const LANES = [["look", "Look", "camera and follow"], ["listen", "Listen", "event camera hum"], ["decide", "Decide", "ask, alert, finish"]];
const epKind = (ep) => { const c = clips.find((x) => x.id === ep.episode); return /^late/.test(ep.episode) ? "late" : (c ? !c.drone : /^background/.test(ep.episode)) ? "none" : "drone"; };
const EP_LABEL = { drone: "drone", late: "late drone", none: "no drone" };
const EP_ICON = { drone: "i-drone", late: "i-late", none: "i-nodrone" };
const STORY = { late: "The camera detector sees nothing. The hum map finds the drone it missed.", drone: "The camera proposes boxes. Listening tells which one hums.", none: "No boxes and no hum spots, so no alert.", rule: "Fixed rules on the same tools, for comparison." };
const agent = { ep: null, timer: null, run: false, wait: null, items: [], k: 0, hz: null, live: null };
const epHz = (ep) => { const r = ep.rows.slice().reverse().find((x) => x.kind === "step" && x.result && x.result.verdict === "hum"); return r ? r.result.peak_hz : null; };
const heading = (v) => { const a = Math.abs(v[0]) >= Math.abs(v[1]); return a ? (v[0] >= 0 ? "right" : "left") : (v[1] >= 0 ? "down" : "up"); };

function cardFor(r, k, steps) {
  const x = r.result || {}, stage = STAGE[r.tool] || "listen", li = el("li", stage);
  li.dataset.st = stage; li.style.setProperty("--d", `${k * 45}ms`);
  if (r.tool === "ask_human" && !agent.live) return askCard(r, k, steps, li);
  const top = el("div", "top"); top.append(icon(TOOL_ICON[r.tool] || "i-wave"), el("span", "n", ACT[r.tool] || r.tool));
  let v = r.tool, w = null, cls = "";
  if (r.guard && r.guard !== "ok") { v = "blocked"; cls = "nohum"; }
  else if (x.error) { v = "error"; cls = "nohum"; }
  else switch (r.tool) {
    case "detect_frame": { const n = (x.detections || []).length; v = n ? `${n} box${n === 1 ? "" : "es"}` : "nothing"; w = n ? "possible drone" : "no drone seen"; cls = n ? "" : "nohum"; break; }
    case "box_spectrum": case "request_window":
      v = `${Math.round(x.peak_hz)} Hz`; w = `${x.verdict === "hum" ? "hums" : x.verdict === "ambiguous" ? "unsure" : "no hum"}, ${x.window_ms} ms`;
      cls = x.verdict === "hum" ? "hum" : x.verdict === "ambiguous" ? "maybe" : "nohum"; break;
    case "frequency_map": case "event_map": { const s = (x.hum_spots || []).length; v = x.dominant_hz ? `${Math.round(x.dominant_hz)} Hz` : "no hum"; w = s ? "humming spot found" : "no humming spot"; cls = s ? "maybe" : "nohum"; break; }
    case "track": v = x.lost ? "lost it" : "still there"; w = x.lost ? null : `moving ${heading(x.velocity_px_s || [0, 0])}`; cls = x.lost ? "nohum" : ""; break;
    case "raise_alert": v = "alert sent"; w = x.severity || null; cls = "alert"; break;
    case "ask_human": if (x.timeout) { v = "no answer"; w = "alert withheld"; cls = "maybe"; break; } v = x.approved ? "approved" : "not approved"; w = /^live page visitor/.test(x.responder || "") ? "by you" : x.responder || null; cls = x.approved ? "" : "nohum"; break;
    case "finish": v = x.verdict === "drone_alerted" ? "drone" : x.verdict === "no_drone" ? "no drone" : String(x.verdict); w = "final answer"; cls = "fin"; break;
  }
  if (cls) li.classList.add(cls);
  li.append(top, el("span", "v", v));
  if (w) li.append(el("span", "w", w));
  const verdict = x.verdict ? `, verdict ${x.verdict}${x.snr != null ? `, score ${fmt(x.snr, 1)}` : ""}${x.n_events != null ? `, ${x.n_events} events` : ""}` : "";
  li.setAttribute("aria-label", `Step ${r.step}, ${stage}: ${ACT[r.tool] || r.tool}, ${v}${w ? ", " + w : ""}${verdict}`);
  li.title = `step ${r.step} · ${r.tool} · ${v}${verdict}`;
  li.tabIndex = 0;
  li.addEventListener("click", () => focusCard(k));
  return li;
}

function askCard(r, k, steps, li) {
  const prior = steps.slice(0, k).reverse().find((s) => s.result && s.result.verdict === "hum");
  const hz = prior ? Math.round(prior.result.peak_hz) : null;
  li.classList.add("ask");
  const top = el("div", "top"); top.append(icon("i-human"), el("span", "n", ACT.ask_human));
  const q = el("div", "q", hz ? `Drone humming at ${hz} Hz. Raise the alert?` : "Raise the alert?");
  const acts = el("div", "acts"), rec = el("span", "rec");
  const send = async (decision) => {
    resume(li, decision);
    try {
      const res = await fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episode: agent.ep.episode, step: r.step, decision }) });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      rec.replaceChildren(icon(decision === "approve" ? "i-check" : "i-x"), document.createTextNode(`${d.approvals} · ${d.rejections}`));
      rec.setAttribute("aria-label", `Recorded on the server at ${d.utc}: ${d.decision}. Nothing external was triggered. ${d.approvals} approvals and ${d.rejections} rejections on this step so far.`);
      rec.title = `Recorded on the server, ${d.utc}. Nothing external triggered. ${d.approvals} approve / ${d.rejections} reject so far.`;
    } catch (e) { rec.textContent = "not recorded"; }
  };
  const a = el("button", "btn yes"); a.append(icon("i-check"), document.createTextNode("Approve")); a.addEventListener("click", () => send("approve"));
  const j = el("button", "btn no"); j.append(icon("i-x"), document.createTextNode("Reject")); j.addEventListener("click", () => send("reject"));
  acts.append(a, j, rec);
  li.append(top, q, acts);
  li.setAttribute("aria-label", `Step ${r.step}, decide: the agent asks a human (severity ${r.args && r.args.severity}). In the recorded run: ${r.result ? r.result.responder : "no answer"}. Your Approve or Reject is recorded on the server only.`);
  li.title = r.args && r.args.question ? r.args.question : "";
  return li;
}

function focusCard(k) {
  agent.items.forEach((c, j) => c.classList.toggle("now", j === k));
  const st = agent.items[k] ? agent.items[k].dataset.st : null;
  document.querySelectorAll("#cards .lane").forEach((s) => s.classList.toggle("on", s.dataset.st === st));
}

function playBtn(state) {
  const b = $("replay");
  b.classList.toggle("running", state !== "idle");
  b.replaceChildren(icon(state === "idle" ? "i-play" : "i-pause"), el("span", "", state === "idle" ? "Play" : state === "wait" ? "Waiting for you" : "Stop"));
  b.setAttribute("aria-label", state === "idle" ? "Play the agent steps one by one" : "Stop the replay");
}

function stopPlay() {
  clearTimeout(agent.timer); agent.run = false; agent.wait = null;
  playBtn("idle");
}

function showAll() { agent.items.forEach((c) => c.classList.remove("hid")); $("agentnote").textContent = ""; }

function step() {
  if (!agent.run) return;
  const c = agent.items[agent.k];
  c.classList.remove("hid"); focusCard(agent.k);
  if (!reduce) c.animate([{ opacity: 0, transform: "translateY(10px) scale(.96)" }, { opacity: 1, transform: "none" }], { duration: 320, easing: "cubic-bezier(.2,.8,.2,1)" });
  if (c.classList.contains("ask")) { agent.wait = c; playBtn("wait"); return; }
  agent.k += 1;
  if (agent.k < agent.items.length) agent.timer = setTimeout(step, reduce ? 300 : 600); else stopPlay();
}

function resume(li, decision) {
  if (!agent.run || agent.wait !== li) return;
  agent.wait = null;
  if (decision === "approve") { playBtn("run"); agent.k += 1; if (agent.k < agent.items.length) agent.timer = setTimeout(step, reduce ? 300 : 600); else stopPlay(); return; }
  stopPlay();
  $("agentnote").textContent = "You rejected, so the replay stops here with no alert. In the recorded run the operator stand-in approved.";
}

function play() {
  if (agent.live) return;
  if (agent.run) { stopPlay(); showAll(); focusCard(-1); return; }
  agent.run = true; agent.k = 0; $("agentnote").textContent = "";
  playBtn("run");
  $("cards").classList.remove("anim");
  agent.items.forEach((c) => c.classList.add("hid"));
  step();
}

function slide4() {
  const eps = tracesDoc.episodes || [];
  const bar = $("epbtns");
  if (!eps.length) { $("cards").append(el("li", "nohum", "pending")); return; }
  eps.forEach((ep) => {
    const kind = epKind(ep), rule = ep.planner === "rule", sc = ep.score;
    const b = el("button", "btn"); b.append(icon(rule ? "i-rule" : EP_ICON[kind]), el("span", "", rule ? "rules only" : EP_LABEL[kind]));
    b.setAttribute("aria-label", `${rule ? "Fixed-rule baseline" : `Agent planned by ${ep.model || ep.planner}`}, ${EP_LABEL[kind]} episode (${ep.episode})${sc ? `: ${sc.true_alerts} true alerts, ${sc.false_alerts} false alerts against FRED boxes, ${sc.steps} steps` : ""}`);
    b.title = `${rule ? "fixed rules" : ep.model || ep.planner} · ${ep.episode}${sc ? ` · ${sc.true_alerts} true / ${sc.false_alerts} false alerts` : ""}`;
    b.addEventListener("click", () => pickEp(ep, b));
    bar.append(b);
  });
  $("replay").addEventListener("click", play);
  $("live").addEventListener("click", runLive);
  stopPlay();
  let first = eps.findIndex((e) => e.planner !== "rule" && epKind(e) === "late");
  if (first < 0) first = Math.max(0, eps.findIndex((e) => e.planner !== "rule"));
  pickEp(eps[first], bar.children[first]);
}

function makeLanes() {
  return LANES.map(([st, name, sub]) => { const li = el("li", "lane"); li.dataset.st = st; const h = el("div", "lh"); h.append(el("b", "", name), el("span", "", sub)); const ol = el("ol", "row"); li.append(h, ol); return li; });
}
function addCard(lanes, c) { lanes[LANES.findIndex((l) => l[0] === c.dataset.st)].querySelector(".row").append(c); }

function liveAsk(id, ask) {
  const li = el("li", "decide ask pending"); li.dataset.st = "decide";
  const m = /([\d.]+) Hz/.exec(ask.question || ""), top = el("div", "top");
  top.append(icon("i-human"), el("span", "n", "asks you, live"));
  const q = el("div", "q", m ? `Drone humming at ${Math.round(+m[1])} Hz. Raise a critical alert?` : "Raise a critical alert?");
  const acts = el("div", "acts");
  const send = async (decision) => {
    acts.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try { const r = await fetch(`/api/agent/live/${id}/decide`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) }); if (!r.ok) throw new Error(r.status); }
    catch (e) { $("agentnote").textContent = `Decision not sent: ${e.message}`; }
  };
  const a = el("button", "btn yes"); a.append(icon("i-check"), document.createTextNode("Approve")); a.addEventListener("click", () => send("approve"));
  const j = el("button", "btn no"); j.append(icon("i-x"), document.createTextNode("Reject")); j.addEventListener("click", () => send("reject"));
  acts.append(a, j);
  li.append(top, q, acts);
  li.setAttribute("aria-label", `The live agent asks you: ${q.textContent} Approve or Reject; it waits up to ${agent.live ? agent.live.wait : 60} seconds.`);
  return li;
}

function stopLive() { if (agent.live) { clearTimeout(agent.live.t); agent.live = null; } clearInterval(agent.busyT); $("live").disabled = false; }
const LIVE_PLANNER = (p) => !p || !p.ran ? "" : p.ran === "bedrock" ? "Claude Sonnet 4.6 on Amazon Bedrock" : "fixed rules";

function busyNote(d) {
  clearInterval(agent.busyT);
  let left = Math.max(1, +d.retry_s || 30);
  const msg = d.busy === "you" ? "Your live run is still going." : `${d.message || "The server is busy"}.`;
  const show = () => { $("agentnote").textContent = left > 0 ? `${msg} Try again in ${left} s.` : `${msg} Try again now.`; if (left <= 0) { clearInterval(agent.busyT); $("live").disabled = false; } left -= 1; };
  $("live").disabled = true; show(); agent.busyT = setInterval(show, 1000);
}

function liveDone(d) {
  const s = d.summary || {}, ex = d.expected || {}, p = d.planner || {};
  if (d.error) return `Live run failed: ${d.error}`;
  const hum = d.rows.filter((r) => r.kind === "step" && r.result && r.result.verdict === "hum").map((r) => r.result.peak_hz);
  const last = d.gt.length ? d.gt[d.gt.length - 1] : null;
  const al = s.alerts && s.alerts[0];
  const head = s.verdict === "unconfirmed_waiting_for_operator" ? `No answer in ${d.wait_s} s, so the run ends unconfirmed, waiting for an operator. The alert was withheld.`
    : al ? (al.severity === "critical" ? "Critical alert raised after your approval." : `Alert raised at ${al.severity} level.`)
    : s.verdict === "drone_alerted" ? "Drone reported." : "No alert.";
  const hz = ex.median_hz ? ` Expected about ${Math.round(ex.median_hz)} Hz (this clip's median)${hum.length ? `; measured ${Math.round(hum[hum.length - 1])} Hz` : "; no hum measured"}.` : "";
  const ov = last ? ` Its box overlaps the FRED ground-truth box: IoU ${fmt(last.iou, 2)}.` : "";
  const by = ` Planner: ${LIVE_PLANNER(p)}${p.fallback && p.fallback.length ? ` (switched from Bedrock: ${p.fallback[0]})` : p.note ? ` (${p.note})` : ""}. ${s.steps} steps in ${fmt(s.wall_s, 1)} s.`;
  return head + hz + ov + by;
}

async function runLive() {
  if (agent.live) return;
  stopPlay();
  const btn = $("live"), clip = cur.clip; btn.disabled = true;
  let id;
  try {
    const r = await fetch("/api/agent/live", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip: clip.id }) });
    const d = await r.json();
    if (r.status === 429 && d.detail && d.detail.retry_s) { busyNote(d.detail); return; }
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : r.status);
    id = d.id; agent.wait_s = d.wait_s;
  } catch (e) { $("agentnote").textContent = `Live run not started: ${e.message}`; btn.disabled = false; return; }
  [...$("epbtns").children].forEach((o) => o.setAttribute("aria-pressed", "false"));
  agent.live = { id, n: 0, t: null, wait: agent.wait_s || 60 };
  const lanes = makeLanes();
  $("cards").classList.remove("anim");
  $("cards").replaceChildren(...lanes); agent.items = [];
  $("story").textContent = "Live: the agent is calling the real OpenCV 5 tools on the server now. It waits for you before a critical alert.";
  $("replaytag").textContent = `Live run on the server · ${modelOf(clip)} · FRED sequence ${clip.seq}`;
  $("replaytag").title = "";
  $("agentnote").textContent = "Running on the server…";
  const poll = async () => {
    if (!agent.live || agent.live.id !== id) return;
    let d;
    try { d = await fetch(`/api/agent/live/${id}`).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }); }
    catch (e) { agent.live.t = setTimeout(poll, 800); return; }
    if (!agent.live || agent.live.id !== id) return;
    const pn = LIVE_PLANNER(d.planner);
    if (pn) $("replaytag").textContent = `Live run on the server · ${modelOf(clip)} · FRED sequence ${clip.seq} · planned by ${pn}`;
    const steps = d.rows.filter((r) => r.kind === "step");
    for (let k = agent.live.n; k < steps.length; k++) {
      const c = cardFor(steps[k], k, steps); agent.items.push(c); addCard(lanes, c); focusCard(agent.items.length - 1);
      const x = steps[k].result || {};
      if (x.verdict === "hum") { agent.hz = x.peak_hz; if (current === 4) setLogoHz(agent.hz); }
    }
    agent.live.n = steps.length;
    const pend = $("cards").querySelector(".pending");
    if (d.status === "waiting" && d.ask && !pend) { const c = liveAsk(id, d.ask); addCard(lanes, c); c.querySelector(".yes").focus({ preventScroll: true }); }
    if (d.status !== "waiting" && pend) pend.remove();
    if (d.status === "done") { $("agentnote").textContent = liveDone(d); stopLive(); return; }
    $("agentnote").textContent = d.status === "waiting" ? `Waiting for you: Approve or Reject (${d.wait_s} s).` : `Running on the server${pn ? `, planned by ${pn}` : ""}…`;
    agent.live.t = setTimeout(poll, 400);
  };
  poll();
}

const plannerName = (ep) => ep.planner === "rule" ? "fixed rules" : /claude-sonnet-4-6/.test(ep.model || "") ? "Claude Sonnet 4.6 on Amazon Bedrock" : (ep.model || ep.planner);
function pickEp(ep, btn) {
  stopPlay(); stopLive();
  [...$("epbtns").children].forEach((o) => o.setAttribute("aria-pressed", String(o === btn)));
  agent.ep = ep;
  const steps = ep.rows.filter((r) => r.kind === "step");
  const host = $("cards");
  host.classList.remove("anim"); void host.offsetWidth; host.classList.add("anim");
  const lanes = LANES.map(([st, name, sub]) => { const li = el("li", "lane"); li.dataset.st = st; const h = el("div", "lh"); h.append(el("b", "", name), el("span", "", sub)); const ol = el("ol", "row"); li.append(h, ol); return li; });
  agent.items = steps.map((r, k) => cardFor(r, k, steps));
  agent.items.forEach((c) => lanes[LANES.findIndex((l) => l[0] === c.dataset.st)].querySelector(".row").append(c));
  host.replaceChildren(...lanes);
  const sc = ep.rows.find((r) => r.kind === "start"), seq = sc && sc.scenario ? sc.scenario.seq : "";
  $("story").textContent = STORY[ep.planner === "rule" ? "rule" : epKind(ep)];
  $("replaytag").textContent = `Replay of a recorded run · FRED sequence ${seq} · ${ep.planner === "rule" ? "fixed rules" : "planned by Claude Sonnet 4.6"}`;
  $("replaytag").title = `Planner: ${plannerName(ep)}. Episode ${ep.episode}.`;
  $("agentnote").textContent = "";
  agent.hz = epHz(ep);
  if (current === 4) setLogoHz(agent.hz);
  focusCard(-1);
}

function paintThumb(cv, c) {
  const fi = Math.floor(c.frames.length / 2), f = c.frames[fi], img = loadFrames(c)[fi];
  const draw = () => {
    const r = cv.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
    if (!r.width || !r.height || !img.naturalWidth) return;
    cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
    const ctx = cv.getContext("2d"), k = img.naturalWidth / c.width, a = cv.width / cv.height;
    const db = f.boxes.find((x) => x.kind === "drone"), [x0, y0, x1, y1] = db ? db.box : [0, 0, c.width, c.height];
    let sw = Math.min(c.width, Math.max((x1 - x0) * 3.2, (y1 - y0) * 3.2 * a, 160)), sh = sw / a;
    if (sh > c.height) { sh = c.height; sw = sh * a; }
    const sx = Math.min(c.width - sw, Math.max(0, (x0 + x1) / 2 - sw / 2)), sy = Math.max(0, Math.min(c.height * 0.95 - sh, (y0 + y1) / 2 - sh / 2));
    ctx.drawImage(img, sx * k, sy * k, sw * k, sh * k, 0, 0, cv.width, cv.height);
    if (db) { const z = cv.width / sw, p = 6 * dpr; ctx.lineWidth = 2.5 * dpr; ctx.strokeStyle = HUM; ctx.strokeRect((x0 - sx) * z - p, (y0 - sy) * z - p, (x1 - x0) * z + 2 * p, (y1 - y0) * z + 2 * p); }
  };
  if (img.complete && img.naturalWidth) draw(); else img.addEventListener("load", draw);
  new ResizeObserver(draw).observe(cv);
}

function clipCards() {
  const host = $("clipcards");
  host.replaceChildren(...droneClips.map((c) => {
    const HZ = hzOf(c), h = c.hum || {}, b = el("button", "cc");
    b.dataset.clip = c.id;
    b.setAttribute("aria-label", `${modelOf(c)}, FRED sequence ${c.seq}: median ${HZ} Hz, ${h.n_clear} of ${h.n_windows} windows of ${h.window_ms} ms pass the hum test. Show this clip.`);
    b.title = `${modelOf(c)} · FRED seq ${c.seq} · ${h.n_clear}/${h.n_windows} windows pass`;
    const cv = el("canvas");
    const meter = el("span", "meter"); const fill = el("i"); fill.style.width = `${h.n_windows ? (100 * h.n_clear / h.n_windows) : 0}%`; meter.append(fill);
    b.append(cv, el("span", "model", shortName(c)), el("span", "v", `${Math.round(HZ)} Hz`), meter);
    b.addEventListener("click", () => { setClip(c); go(0); });
    paintThumb(cv, c);
    return b;
  }));
}

const COOL_CPU = ["sve", "sve2", "asimd", "asimddp", "asimdhp", "bf16", "i8mm", "avx2", "avx512f"];
async function verifyCool() {
  const b = $("coolbtn"), box = $("coolv");
  b.disabled = true; b.querySelector("span").textContent = "Checking…";
  box.replaceChildren(); box.hidden = false;
  const hd = el("div", "hd"); hd.append(icon("i-chip"), el("span", "", "Live from this server"));
  const x = el("button", "iconbtn"); x.setAttribute("aria-label", "Close the COOL check"); x.append(icon("i-x")); x.onclick = () => { box.hidden = true; b.focus(); };
  hd.append(x); box.append(hd);
  try {
    const r = await fetch("/api/cool", { cache: "no-store" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`);
    const i = d.instance || {}, hal = (d.build_hal || []).find((l) => /HAL/.test(l)) || "–";
    const cpu = (d.cpu_features || []).filter((f) => COOL_CPU.includes(f));
    const dl = el("dl"), row = (k, v, cls) => { dl.append(el("dt", "", k), el("dd", cls || "", v)); };
    row("cv2 loaded from", d.cv2_file);
    row("OpenCV", `${d.opencv} · ${d.cool ? "COOL build (/opt/cool)" : "not the COOL build"}`, d.cool ? "ok" : "");
    row("HAL", hal.replace(/^Custom HAL:\s*/, ""), d.kleidicv ? "ok" : "");
    row("instance", i.instance_type ? `${i.instance_type} · ${i.instance_id} · ${i.ami_id}` : i.source || "–");
    if (i.product_codes) row("Marketplace product", i.product_codes);
    row("CPU features", cpu.length ? cpu.join(" ") : (d.cpu_features_opencv || "–"));
    row("OpenCV threads", String(d.threads));
    box.append(dl);
    const t = d.timing || {};
    if (t.status === "ok") {
      const tb = el("table"), h = el("tr"); ["op", "runs", "p50 ms"].forEach((s) => h.append(el("th", "", s))); tb.append(h);
      t.ops.forEach((o) => { const tr = el("tr"); tr.append(el("td", "", o.op), el("td", "", String(o.runs)), el("td", "ms", fmt(o.p50_ms, 3))); tb.append(tr); });
      tb.setAttribute("aria-label", `Timed on this server just now: ${t.ops.map((o) => `${o.op} ${fmt(o.p50_ms, 3)} ms median over ${o.runs} runs`).join(", ")}`);
      box.append(tb, el("p", "src", `Timed now in ${fmt(t.total_ms, 0)} ms on ${t.input}.`));
    } else box.append(el("p", "src", `Timing ${t.status || "unavailable"}.`));
    const a = el("a", "", "raw JSON"); a.href = "/api/cool"; a.target = "_blank"; a.rel = "noopener";
    const p = el("p", "src"); p.append(a); box.append(p);
  } catch (e) {
    box.append(el("p", "src", `Check failed: ${e.message}`));
  } finally { b.disabled = false; b.querySelector("span").textContent = "Verify COOL live"; }
}
$("coolbtn").addEventListener("click", verifyCool);

async function slide5() {
  clipCards();
  const d = await fetch("/api/results").then((r) => r.json()).catch(() => null);
  const f = d && d.false_alarms, fa = $("fa");
  const ok = f && f.rgb_only && f.rgb_event;
  const mins = ok && /([\d.]+) min/.exec(f.rgb_only.note || "");
  if (mins) $("fatag").textContent = `false alarms · ${Math.round(+mins[1])} min of test video`;
  const cell = (ics, label, v, good) => {
    const c = el("div", "facell" + (good ? " good" : "")); const who = el("div", "who"); ics.forEach((i) => who.append(icon(i))); who.append(el("span", "", label));
    c.setAttribute("aria-label", `${label}: ${v} false alarms`);
    c.append(who, el("div", "v" + (v === "pending" ? " pending" : ""), v)); return c;
  };
  if (ok) {
    const a = f.rgb_only.false_alarms, b2 = f.rgb_event.false_alarms, drop = el("div", "fadrop");
    drop.append(icon("i-right"), el("span", "", `−${Math.round(100 * (1 - b2 / a))}%`));
    drop.setAttribute("aria-label", `${Math.round(100 * (1 - b2 / a))}% fewer false alarms with the hum check${f.rgb_only.recall === f.rgb_event.recall ? `, at the same recall ${f.rgb_event.recall}` : ""}. ${f.rgb_event.note}. Source: ${f.source}`);
    fa.append(cell(["i-camera"], "RGB", a.toLocaleString()), drop, cell(["i-camera", "i-sine"], "+ hum", b2.toLocaleString(), true));
    fa.title = `${f.rgb_only.note}; ${f.rgb_event.note}. ${f.source}`;
  } else fa.append(cell(["i-camera"], "RGB", "pending"), el("span"), cell(["i-camera", "i-sine"], "+ hum", "pending"));
  const cp = d && d.cool_vs_pip, cb = $("coolbars");
  if (cp && cp.status === "ok") {
    const cmax = Math.max(...cp.ops.map((o) => o.ratio));
    cp.ops.forEach((o) => {
      const row = el("div", "bbrow"); row.title = `${o.op}: COOL ${o.cool_ms} ms, pip ${o.pip_ms} ms (${o.scope}, ${cp.instance})`;
      const bars = el("div", "bars2"), g = el("div", "b g4"); g.style.width = (o.ratio / cmax * 100) + "%"; g.style.transform = "scaleX(0)";
      const one = el("i", "one"); one.style.left = (100 / cmax) + "%"; bars.append(g, one);
      row.append(el("span", "", o.label), bars, el("span", "r win", `${fmt(o.ratio, 2)}×`));
      cb.append(row);
    });
    const e = cp.end_to_end;
    $("coolnote").textContent = `Times faster under COOL ${cp.cool} than pip ${cp.pip}. End to end, pip is ${e.pip_faster_pct}% faster (${e.pip_p50_ms} vs ${e.cool_p50_ms} ms per window): the detector runs slower under COOL.`;
    cb.setAttribute("aria-label", `COOL versus pip OpenCV on one ${cp.instance}: ${cp.ops.map((o) => `${o.label} ${o.ratio} times faster under COOL`).join(", ")}. End to end pip is ${e.pip_faster_pct}% faster. Source: ${cp.files.join(", ")}.`);
  } else cb.append(el("div", "win5", "pending"));
  if (ok) $("hl6").textContent = `${Math.round(100 * (1 - f.rgb_event.false_alarms / f.rgb_only.false_alarms))}% fewer false alarms, a pitch for each drone, and OpenCV 5 speed on Graviton4.`;
  const b = d && d.bench, bb = $("benchbars");
  if (!b || b.status !== "ok") { bb.append(el("div", "win5", "pending")); return; }
  const short = { connectedComponentsWithStats: "components", dnn_forward: "DNN", GaussianBlur: "blur", cvtColor: "cvtColor", resize: "resize", dft: "DFT" };
  const ratio = (o) => o.x86_over_graviton4 || o.x86_ms / o.graviton4_ms;
  const ops = b.ops.slice().sort((p, q) => ratio(q) - ratio(p)), top = ops[0], rmax = ratio(top);
  const wins = b.ops.filter((o) => o.graviton4_ms < o.x86_ms).length;
  const w = $("winner"); w.append(document.createTextNode(`${fmt(ratio(top), 2)}×`)); w.append(el("small", "", `${short[top.op] || top.op} on Graviton4 · ${wins} of ${b.ops.length} faster`));
  w.setAttribute("aria-label", `${top.op} runs ${fmt(ratio(top), 2)} times faster on Graviton4 ${b.graviton4.instance} than on x86 ${b.x86.instance}; Graviton4 is faster on ${wins} of ${b.ops.length} OpenCV 5 operations, ${b.graviton4.threads} threads, p50 ms. Source ${b.graviton4.file} and ${b.x86.file}.`);
  ops.forEach((o) => {
    const r = ratio(o);
    const row = el("div", "bbrow"); row.title = `${o.op}: Graviton4 ${fmt(o.graviton4_ms, 3)} ms, x86 ${fmt(o.x86_ms, 3)} ms`;
    const bars = el("div", "bars2"); const g = el("div", "b g4" + (r < 1 ? " lose" : ""));
    g.style.width = (r / rmax * 100) + "%"; g.style.transform = "scaleX(0)";
    const one = el("i", "one"); one.style.left = (100 / rmax) + "%";
    bars.append(g, one);
    row.append(el("span", "", short[o.op] || o.op), bars, el("span", "r" + (r > 1 ? " win" : ""), `${fmt(r, 2)}×`));
    bb.append(row);
  });
}
function growBars() { document.querySelectorAll(".bbrow .b").forEach((b) => { b.style.transform = "scaleX(1)"; }); }

function getSpec(clip, frame, box, win) {
  const f = clip.frames[frame], b = f.boxes[box];
  return fetchSpec({ clip: clip.id, box: b.box, t: f.t, window_ms: win, frame, box_index: box });
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
  const tk = opt.ticks || [0, 300, 600, 900, 1200];
  tk.forEach((f, j) => txt(ctx, j === tk.length - 1 ? `${f} Hz` : String(f), j === tk.length - 1 ? x1 : X(f), y1 + 22, { align: j === tk.length - 1 ? "right" : "center" }));
  if (d.peak_hz > 0) {
    const pv = d.power[Math.round(d.peak_hz / d.df)] || 1, px = X(d.peak_hz), py = Y(pv), right = px < x1 - 150;
    if (d.clear) { ctx.save(); ctx.shadowColor = HUM; ctx.shadowBlur = 22; ctx.fillStyle = HUM; ctx.beginPath(); ctx.arc(px, py, 8, 0, 7); ctx.fill(); ctx.restore(); }
    txt(ctx, d.clear ? `${showHz(d, cur.HZ)} Hz` : `${Math.round(d.peak_hz)} Hz, no hum`, right ? px + 14 : px - 14, Math.max(py - 14, y0 + 22), { font: "500 24px 'JetBrains Mono', monospace", color: d.clear ? HUM : "#777", align: right ? "left" : "right" });
  }
  return { X, Y };
}

const M = { init: false, ready: false, clipId: null };
function mathTabs() {
  const tabs = $("mtabs"), panels = [...document.querySelectorAll("#mgrid .mp")];
  [["i-camera", "30 fps"], ["i-wave", "dft"], ["i-sigma", "score"], ["i-clock", "window"]].forEach(([ic, lab], j) => {
    const b = el("button", "btn"); b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(j === 0)); b.append(icon(ic), el("span", "", lab));
    b.addEventListener("click", () => { [...tabs.children].forEach((o, k) => o.setAttribute("aria-selected", String(k === j))); panels.forEach((p, k) => p.classList.toggle("on", k === j)); });
    tabs.append(b);
  });
}
async function slideMath() {
  if (!M.initP) M.initP = summaryP.then((sm) => { const ht = sm.hum_test; M.fs = ht.fs_hz; M.amb = ht.ambiguous_score; M.clear = ht.clear_score; M.local = ht.local_hz; });
  await M.initP;
  if (!M.init) {
    M.init = true;
    ["x(t)", "·w(t)", "|X(f)|²"].forEach((lab, j) => { const b = el("button", "btn", lab); b.addEventListener("click", () => { M.stage = j; drawFt(); }); $("ftbtns").append(b); });
    const ops = [["i-hist", "calcHist"], ["i-wave", "dft"], ["i-blobs", "connectedComponents"], ["i-net", "dnn"]];
    const row = $("cvrow");
    ops.forEach(([ic, n], j) => { if (j) row.append(el("span", "arr", "→")); const o = el("span", "op"); o.append(icon(ic), document.createTextNode("cv." + n)); row.append(o); });
    M.opEls = [...row.querySelectorAll(".op")];
    $("mwin").addEventListener("input", () => { clearTimeout(M.wt); M.wt = setTimeout(drawWin, 120); });
    M.stage = 2;
    const t0 = performance.now();
    const loop = (now) => {
      if (current === 3 && M.ready) {
        const t = (now - t0) / 1000;
        drawNyq(reduce ? 0 : t);
      }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
  if (M.clipId === cur.clip.id) return;
  M.ready = false; M.clipId = cur.clip.id;
  const clip = cur.clip, ref = cur.HZ ? clip : droneClips.find((c) => hzOf(c)), HZ = hzOf(ref);
  M.hz = HZ; M.refName = `${shortName(ref)} · ${Math.round(HZ)} Hz`;
  const k = Math.round(HZ / 30), alias = Math.abs(HZ - k * 30);
  M.alias = alias;
  const [hf, hb] = firstBox(clip, "drone"), bgb = firstBox(bg, "other");
  M.hf = hf; M.hb = hb;
  const fCloud = clip.frames.findIndex((f) => f.t === clip.cloud.t_end);
  const [d100, dbg, d40] = await Promise.all([getSpec(clip, hf, hb, 100), bgb ? getSpec(bg, bgb[0], bgb[1], 100) : null,
    getSpec(clip, fCloud >= 0 ? fCloud : hf, fCloud >= 0 ? Math.max(0, clip.frames[fCloud].boxes.findIndex((b) => b.kind === "drone")) : hb, clip.cloud.ms)]);
  if (M.clipId !== clip.id) return;
  M.d100 = d100; M.dbg = dbg; M.d40 = d40;
  const N = Math.round(clip.cloud.ms * M.fs / 1000), sig = new Float32Array(N), cb = cur.crop;
  for (let i = 0; i < cb.length / 4; i++) sig[Math.min(N - 1, Math.floor(cb[4 * i + 2] / (clip.cloud.ms * 1000) * N))] += cb[4 * i + 3] ? 1 : -1;
  M.sig = sig; M.N = N; M.smax = Math.max(...sig.map(Math.abs)) || 1;
  $("sr-math-live").textContent = `Live numbers for ${modelOf(clip)}, FRED sequence ${clip.seq}: ${cur.HZ ? `measured blade-pass ${HZ} Hz aliases at 30 fps to ${alias.toFixed(1)} Hz (k = ${k})` : `no clean hum; the aliasing panel uses ${M.refName}`}. Event bins of ${1e3 / M.fs} ms give a Nyquist limit of ${M.fs / 2} Hz. Drone box score at 100 ms: ${fmt(d100.snr, 1)} (hum above ${M.clear}); no-drone box score: ${dbg ? fmt(dbg.snr, 1) : "n/a"} (ambiguous above ${M.amb}).`;
  M.ready = true;
  drawFt(); drawSnr(); drawWin();
}

function drawNyq(t) {
  const nyq = $("nyq"), nc = nyq.getContext("2d"), W = nyq.width, HZ = M.hz, alias = M.alias;
  nc.fillStyle = "#FEFEFE"; nc.fillRect(0, 0, W, nyq.height);
  const th = (tt) => 2 * Math.PI * (HZ / 2) * tt, R = 92;
  nc.strokeStyle = "#E4E4E4"; nc.lineWidth = 2;
  [[170, 130], [470, 130]].forEach(([x, y]) => { nc.beginPath(); nc.arc(x, y, R + 6, 0, 7); nc.stroke(); });
  for (let s = 0; s < 24; s++) blades(nc, 170, 130, R, th(t + s / 60 / 24), 0.07, INK);
  blades(nc, 470, 130, R, th(Math.floor(t * 30) / 30), 0.9, INK);
  [[170, 130], [470, 130]].forEach(([x, y]) => { nc.fillStyle = "#2a2a2a"; nc.beginPath(); nc.arc(x, y, 12, 0, 7); nc.fill(); });
  const ph = nyq.clientWidth > 0 && nyq.clientWidth < 600, hx = ph ? 600 : 640, lx = ph ? 770 : 800;
  txt(nc, `${Math.round(HZ)} Hz`, hx, 110, { font: "500 30px 'JetBrains Mono', monospace", color: HUM });
  if (!cur.HZ) txt(nc, `(${M.refName})`, hx, 60, { font: "400 16px 'JetBrains Mono', monospace" });
  txt(nc, `${alias.toFixed(1)} Hz`, hx, 170, { font: "500 30px 'JetBrains Mono', monospace", color: INK });
  txt(nc, ph ? "real" : "real propeller", 170, 22, { font: "400 18px 'JetBrains Mono', monospace", align: "center" });
  txt(nc, ph ? "at 30 fps" : "what 30 fps sees", 470, 22, { font: "400 18px 'JetBrains Mono', monospace", align: "center" });
  txt(nc, "real", lx, 110, { font: "400 20px 'JetBrains Mono', monospace" });
  txt(nc, "at 30 fps", lx, 170, { font: "400 20px 'JetBrains Mono', monospace" });
  const ax0 = 40, ax1 = W - 30, ay = 330;
  nc.fillStyle = "rgba(255,90,31,.14)"; nc.fillRect(ax0, ay - 34, logx(M.fs / 2, ax0, ax1) - ax0, 26);
  nc.fillStyle = "#CFCFCF"; nc.fillRect(ax0, ay - 34, logx(15, ax0, ax1) - ax0, 26);
  txt(nc, "30 fps sees ≤15 Hz", ax0, ay - 42, { font: "500 16px 'JetBrains Mono', monospace", color: "#444" });
  txt(nc, `events see ≤${M.fs / 2000} kHz`, logx(M.fs / 2, ax0, ax1), ay - 42, { font: "500 16px 'JetBrains Mono', monospace", color: "#444", align: "right" });
  nc.strokeStyle = INK; nc.lineWidth = 2; nc.beginPath(); nc.moveTo(ax0, ay); nc.lineTo(ax1, ay); nc.stroke();
  [1, 10, 100, 1000, 10000].forEach((f) => { const x = logx(f, ax0, ax1), last = f === 10000; nc.fillStyle = "#777"; nc.fillRect(x - 1, ay, 2, 8); txt(nc, last ? "10k Hz" : f >= 1000 ? f / 1000 + "k" : String(f), last ? ax1 : x, ay + 28, { font: "400 16px 'JetBrains Mono', monospace", align: last ? "right" : "center" }); });
  const xh = logx(HZ, ax0, ax1), xa = logx(alias, ax0, ax1);
  nc.strokeStyle = HUM; nc.lineWidth = 2.5; nc.setLineDash([6, 5]); nc.beginPath(); nc.moveTo(xh, ay - 38); nc.quadraticCurveTo((xh + xa) / 2, ay - 110, xa + 6, ay - 38); nc.stroke(); nc.setLineDash([]);
  txt(nc, "folds down", (xh + xa) / 2, ay - 84, { font: "400 15px 'JetBrains Mono', monospace", color: HUM, align: "center" });
  nc.fillStyle = HUM; nc.beginPath(); nc.arc(xh, ay, 8, 0, 7); nc.fill();
  nc.fillStyle = INK; nc.beginPath(); nc.arc(xa, ay, 7, 0, 7); nc.fill();
}

function drawFt() {
  const ft = $("ft"), fc = ft.getContext("2d"), W = ft.width, H = ft.height, N = M.N, sig = M.sig, smax = M.smax;
  [...$("ftbtns").children].forEach((b, j) => b.setAttribute("aria-pressed", String(j === M.stage)));
  fc.fillStyle = "#FEFEFE"; fc.fillRect(0, 0, W, H);
  if (!sig) return;
  const hann = (n) => 0.5 - 0.5 * Math.cos(2 * Math.PI * n / (N - 1));
  const top = M.stage < 2, y0 = top ? 34 : 20, hh = top ? 290 : 116, mid = y0 + hh / 2, bw = (W - 60) / N;
  for (let n = 0; n < N; n++) {
    const w = M.stage >= 1 ? hann(n) : 1, v = sig[n] / smax * (hh / 2 - 6), vw = v * w;
    if (M.stage >= 1) { fc.fillStyle = "#E6E6E6"; fc.fillRect(30 + n * bw, v >= 0 ? mid - v : mid, Math.max(bw, 1), Math.abs(v)); }
    fc.fillStyle = v >= 0 ? INK : OFF; fc.fillRect(30 + n * bw, vw >= 0 ? mid - vw : mid, Math.max(bw, 1), Math.abs(vw));
  }
  if (M.stage >= 1) { fc.strokeStyle = HUM; fc.lineWidth = 2; fc.beginPath(); for (let n = 0; n < N; n++) { const x = 30 + n * bw, y = mid - hann(n) * (hh / 2 - 6); if (n) fc.lineTo(x, y); else fc.moveTo(x, y); } fc.stroke(); }
  txt(fc, M.stage === 0 ? "brighter minus darker, per 0.1 ms" : M.stage === 1 ? "× Hanning window" : "windowed signal", 30, 28, { font: "400 16px 'JetBrains Mono', monospace" });
  txt(fc, "0", 30, y0 + hh + 20, { font: "400 16px 'JetBrains Mono', monospace" });
  txt(fc, `${cur.clip.cloud.ms} ms`, W - 30, y0 + hh + 20, { font: "400 16px 'JetBrains Mono', monospace", align: "right" });
  if (M.stage === 2) {
    txt(fc, "cv.dft ↓", W / 2, 182, { font: "500 20px 'JetBrains Mono', monospace", color: INK, align: "center" });
    specPlot(fc, M.d40, [40, 200, W - 20, H - 34], {});
  }
}

function drawSnr() {
  const snr = $("snr"), scx = snr.getContext("2d"), W = snr.width, H = snr.height, d = M.d100;
  scx.fillStyle = "#FEFEFE"; scx.fillRect(0, 0, W, H);
  const f0 = Math.max(0, d.peak_hz - 160), f1 = d.peak_hz + 160;
  scx.fillStyle = "rgba(30,30,30,.05)";
  const pre = (f) => 40 + (f - f0) / (f1 - f0) * 560;
  scx.fillRect(pre(d.peak_hz - M.local), 20, pre(d.peak_hz + M.local) - pre(d.peak_hz - M.local), H - 60);
  const { X, Y } = specPlot(scx, d, [40, 20, 600, H - 40], { f0, f1, ticks: [showHz(d, cur.HZ) - 100, showHz(d, cur.HZ), showHz(d, cur.HZ) + 100] });
  const loc = d.power.filter((p, k2) => Math.abs(k2 * d.df - d.peak_hz) <= M.local).slice().sort((a, b) => a - b);
  const med = loc[Math.floor(loc.length / 2)];
  scx.strokeStyle = INK; scx.lineWidth = 2; scx.setLineDash([8, 6]); scx.beginPath(); scx.moveTo(X(d.peak_hz - M.local), Y(med)); scx.lineTo(X(d.peak_hz + M.local), Y(med)); scx.stroke(); scx.setLineDash([]);
  txt(scx, "median within ±100 Hz", X(d.peak_hz - M.local) + 4, Y(med) + 22, { font: "500 16px 'JetBrains Mono', monospace", color: INK });
  const ph = snr.clientWidth > 0 && snr.clientWidth < 600, gx = ph ? 680 : 770, gy0 = 24, gy1 = H - 40, GY = (v) => gy1 - Math.min(4, Math.log10(Math.max(v, 1))) / 4 * (gy1 - gy0);
  scx.fillStyle = "rgba(255,90,31,.16)"; scx.fillRect(gx - 26, gy0, 52, GY(M.clear) - gy0);
  scx.fillStyle = "#E6E6E6"; scx.fillRect(gx - 26, GY(M.clear), 52, GY(M.amb) - GY(M.clear));
  scx.strokeStyle = INK; scx.lineWidth = 2; scx.strokeRect(gx - 26, gy0, 52, gy1 - gy0);
  txt(scx, "hum", gx, gy0 + 22, { font: "500 14px 'JetBrains Mono', monospace", color: HUM, align: "center" });
  txt(scx, "maybe", gx, (GY(M.clear) + GY(M.amb)) / 2 + 5, { font: "500 14px 'JetBrains Mono', monospace", color: "#555", align: "center" });
  txt(scx, "no", gx, (GY(M.amb) + gy1) / 2 + 5, { font: "500 14px 'JetBrains Mono', monospace", color: "#555", align: "center" });
  [[M.amb, `${M.amb}`], [M.clear, `${M.clear}`]].forEach(([v, l]) => { scx.fillStyle = INK; scx.fillRect(gx - 34, GY(v) - 1, 68, 2); txt(scx, l, gx - 40, GY(v) + 6, { font: "500 18px 'JetBrains Mono', monospace", color: INK, align: "right" }); });
  const mark = (v, color, lab, dy) => { const y = GY(v); scx.fillStyle = color; scx.beginPath(); scx.moveTo(gx + 30, y); scx.lineTo(gx + 44, y - 9); scx.lineTo(gx + 44, y + 9); scx.fill(); txt(scx, `${lab} ${Math.round(v)}`, gx + 48, y + 7 + dy, { font: "500 18px 'JetBrains Mono', monospace", color }); };
  mark(d.snr, HUM, ph ? "drone" : "drone box", 0);
  if (M.dbg) mark(M.dbg.snr, INK, ph ? "empty" : "no drone", Math.abs(GY(M.dbg.snr) - GY(d.snr)) < 22 ? 20 : 0);
}

const WINS = [20, 50, 100, 150, 200, 300];
async function drawWin() {
  const mw = $("mwin"), mp = $("mwplot"), mc = mp.getContext("2d"), clip = cur.clip;
  const w = WINS[+mw.value]; $("mwinv").textContent = `${w} ms`;
  mw.setAttribute("aria-valuetext", `${w} ms`);
  const id = (M.wreq = (M.wreq || 0) + 1);
  const d = await getSpec(clip, M.hf, M.hb, w);
  if (id !== M.wreq || clip !== cur.clip) return;
  mc.fillStyle = "#FEFEFE"; mc.fillRect(0, 0, mp.width, mp.height);
  specPlot(mc, d, [40, 20, mp.width - 280, mp.height - 34], { f0: 100, f1: 1000, ticks: [100, 400, 700, 1000] });
  txt(mc, `Δf = ${(1000 / w).toFixed(1)} Hz`, mp.width - 250, 90, { font: "500 32px 'JetBrains Mono', monospace", color: INK });
  txt(mc, `score ${Math.round(d.snr)}`, mp.width - 250, 160, { font: "500 32px 'JetBrains Mono', monospace", color: d.clear ? HUM : "#777" });
  mp.title = `${d.window_ms} ms window, peak ${d.peak_hz} Hz, score ${d.snr}, ${d.compute_ms ?? "–"} ms live on the server with OpenCV 5`;
}

const logo = { hz: null, from: 0, shown: 0, t0: 0 };
function drawLogo(now) {
  const hz = logo.hz, c = $("hzc"), u = Math.min(1, (now - logo.t0) / 700), k = 1 - Math.pow(1 - u, 3);
  if (hz) { logo.shown = logo.from + (hz - logo.from) * k; c.textContent = `${Math.round(logo.shown)} Hz`; } else c.textContent = "— Hz";
  c.classList.toggle("none", !hz);
  return u < 1;
}
function logoLoop(now) { if (drawLogo(now)) requestAnimationFrame(logoLoop); }
function setLogoHz(hz) {
  logo.from = logo.shown || (hz ? hz * 0.6 : 0); logo.hz = hz; logo.t0 = performance.now();
  $("hzc").setAttribute("aria-label", hz ? `Selected clip: measured propeller frequency ${Math.round(hz)} Hz` : "Selected clip: hard case, no clean propeller frequency");
  if (reduce) { logo.t0 = -1e9; drawLogo(performance.now()); } else requestAnimationFrame(logoLoop);
}

function clipBar() {
  const bar = $("clipbar");
  droneClips.forEach((c) => {
    const HZ = hzOf(c), b = el("button", "btn" + (HZ ? "" : " hard"));
    b.append(el("span", "", shortName(c)), el("b", "", HZ ? `${Math.round(HZ)} Hz` : "hard case"));
    b.setAttribute("aria-label", `${modelOf(c)}, FRED sequence ${c.seq}, ${HZ ? "median hum " + HZ + " Hz" : "hard case, no clean peak"}: ${nice(c.title)}`);
    b.dataset.clip = c.id;
    b.addEventListener("click", () => setClip(c));
    bar.append(b);
  });
  $("sr-clips").textContent = `Clip picker, all FRED test sequences: ${droneClips.map((c) => `${modelOf(c)} (sequence ${c.seq}, ${hzOf(c) ? hzOf(c) + " Hz, " + c.hum.n_clear + " of " + c.hum.n_windows + " windows pass" : "hard case, " + c.hum.n_clear + " of " + c.hum.n_windows + " windows pass"})`).join("; ")}. The no-drone side is FRED sequence ${bg.seq}. Picking a clip re-runs slides 1 to 4 on it.`;
}

function preload() {
  const idle = window.requestIdleCallback || ((f) => setTimeout(f, 300));
  idle(() => {
    [...droneClips, bg].forEach((c) => {
      loadFrames(c);
      if (c.cloud.crop) bufOf(c.cloud.crop.src);
      const fb = firstBox(c, c.drone ? "drone" : "other");
      if (fb) getSpec(c, fb[0], fb[1], 100).catch(() => {});
    });
    slideMath();
  });
}

async function setClip(clip) {
  if (cur.clip === clip) return;
  cur.clip = clip; cur.HZ = hzOf(clip); cur.crop = null;
  if (current !== 4) setLogoHz(cur.HZ);
  document.querySelectorAll("#clipbar [data-clip]").forEach((b) => { const on = b.dataset.clip === clip.id; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  const crop = clip.cloud.crop ? await bufOf(clip.cloud.crop.src) : null;
  if (cur.clip !== clip) return;
  cur.crop = crop;
  applySlide1();
  applySlide2();
  spec.sides.drone.setClip(clip);
  if (M.init) slideMath();
}

const deck = $("deck"), slides = [...deck.querySelectorAll(".slide")];
let current = -1;
const pager = $("pager");
slides.forEach((s, i) => { const b = el("button"); b.setAttribute("aria-label", `Go to slide ${i + 1}: ${s.getAttribute("aria-label")}`); b.addEventListener("click", () => go(i)); pager.append(b); });
deck.classList.add("byindex");
function go(i, smooth = !reduce) {
  i = Math.max(0, Math.min(slides.length - 1, i));
  deck.classList.toggle("still", !smooth);
  deck.style.setProperty("--i", i);
  if (deck.scrollLeft || deck.scrollTop) deck.scrollTo(0, 0);
  enter(i);
}
function enter(i) {
  if (i === current) return;
  const prev = current;
  current = i;
  document.body.dataset.slide = i;
  [...pager.children].forEach((b, j) => b.setAttribute("aria-current", String(j === i)));
  document.querySelectorAll(".steps button").forEach((b) => b.classList.toggle("on", +b.dataset.go === i));
  $("prev").disabled = i === 0; $("next").disabled = i === slides.length - 1;
  history.replaceState(null, "", "#" + slides[i].id);
  slides.forEach((s, j) => s.toggleAttribute("inert", j !== i));
  if (i === 1 && cur.crop) slide2();
  if (i === 2) Object.values(spec.sides).forEach((s) => { if (s.data && !s.played) { s.played = true; animateSpec(s.svg, s.data, true, showHz(s.data, hzOf(s.clip))); } });
  if (i === 3 && cur.crop) slideMath();
  if (i !== 4 && agent.run) { stopPlay(); showAll(); focusCard(-1); }
  if (i === 4) setLogoHz(agent.hz); else if (prev === 4) setLogoHz(cur.HZ);
  if (i === 5) requestAnimationFrame(growBars);
}
deck.addEventListener("scroll", () => { if (deck.scrollLeft || deck.scrollTop) deck.scrollTo(0, 0); });
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
  const d = Math.abs(e.deltaY) > Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
  e.preventDefault();
  const now = performance.now();
  if (now < wheelLock || Math.abs(d) < 8) return;
  wheelLock = now + 750;
  go(current + (d > 0 ? 1 : -1));
}, { passive: false });
addEventListener("hashchange", () => { const k = slides.findIndex((s) => location.hash === "#" + s.id); if (k >= 0 && k !== current) go(k); });
let drag = null;
deck.addEventListener("pointerdown", (e) => { if ((e.pointerType !== "touch" && e.button !== 0) || e.target.closest("button,input,a,#cloud,canvas.thumb,.thumb,.cards")) return; drag = { x: e.clientX, y: e.clientY }; });
addEventListener("pointercancel", () => { drag = null; });
addEventListener("pointerup", (e) => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag = null; if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(current + (dx < 0 ? 1 : -1)); });

clipBar();
mathTabs();
slide1();
slide3();
slide4();
slide5();
await setClip(droneClips.find((c) => c.id === "clear_mini2_seq202") || droneClips[0]);
preload();
const start = Math.max(0, slides.findIndex((s) => location.hash.startsWith("#" + s.id)));
go(start, false);

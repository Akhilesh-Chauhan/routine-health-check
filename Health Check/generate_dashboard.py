"""Generate a self-contained, visually-polished HTML dashboard from master_report.json.

Reads:  _hc_artifacts/master_report.json
Writes: dashboard.html   (open in any browser; no server required)
"""
import base64
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT  = os.path.join(HERE, "_hc_artifacts", "master_report.json")
ART_DIR = os.path.join(HERE, "_hc_artifacts")
OUT     = os.path.join(HERE, "dashboard.html")
MAX_EMBED_BYTES = 4 * 1024 * 1024   # don't inline screenshots larger than 4 MB

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NeGD myScheme Health Dashboard</title>
<style>
:root {
  --bg-0: #eef1f6;
  --bg-1: #eceff4;
  --bg-2: #ffffff;
  --bg-3: #e2e7ef;
  --bd:   #d2d9e4;
  --text: #15243d;
  --text-2: #4b5a72;
  --text-3: #7b8799;
  --up:   #15803d;
  --up-bg: #e6f4ea;
  --warn: #b45309;
  --warn-bg: #faecd9;
  --down: #c1271d;
  --down-bg: #fbe7e4;
  --info: #1d4ed8;
  --info-bg: #e6edfc;
  --shadow: 0 1px 3px rgba(21,36,61,0.10), 0 1px 2px rgba(21,36,61,0.06);
  --shadow-sm: 0 1px 2px rgba(21,36,61,0.07);
  --r: 8px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: var(--bg-0); color: var(--text); font-family:
  -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased; line-height: 1.5; }
body { min-height: 100vh; padding-bottom: 48px; }

/* GOVERNMENT TOP BAR */
.topbar { background: #0f2c5c; border-bottom: 3px solid #ff9933; }
.topbar-inner { max-width: 1440px; margin: 0 auto; padding: 11px 32px;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.topbar-brand { color: #ffffff; font-weight: 700; font-size: 13px;
  letter-spacing: 0.2px; }
.topbar-sep { color: #5d79ad; }
.topbar-sub { color: #b9c6e2; font-size: 12px; }

.container { max-width: 1440px; margin: 0 auto; padding: 24px 32px 0; }

/* HERO */
.hero { display: grid; grid-template-columns: 1.4fr 1fr; gap: 24px;
        align-items: stretch; margin-bottom: 28px; }
.hero-left { background: var(--bg-2);
             border: 1px solid var(--bd); border-radius: var(--r);
             padding: 26px 30px; box-shadow: var(--shadow-sm);
             display: flex; flex-direction: column; justify-content: space-between; }
.hero-eyebrow { font-size: 11px; color: var(--text-3); text-transform: uppercase;
                letter-spacing: 2px; font-weight: 600; }
.hero-title  { font-size: 27px; font-weight: 700; margin-top: 6px;
                color: var(--text); letter-spacing: -0.3px; }
.hero-sub   { color: var(--text-2); font-size: 13px; margin-top: 8px; }
.hero-meta  { display: flex; gap: 24px; margin-top: 22px; }
.hero-meta-item { font-size: 12px; }
.hero-meta-item .k { color: var(--text-3); text-transform: uppercase;
                     letter-spacing: 1px; font-weight: 600; font-size: 10px; }
.hero-meta-item .v { color: var(--text); font-size: 14px; margin-top: 3px;
                     font-variant-numeric: tabular-nums; font-weight: 500; }
.hero-status { display: flex; align-items: center; gap: 18px; }
.hero-pulse { width: 14px; height: 14px; border-radius: 50%; position: relative; }
.hero-pulse::after { content: ""; position: absolute; inset: -4px;
                     border-radius: 50%; opacity: .5;
                     animation: pulse 2s ease-out infinite; }
.hero-pulse.up    { background: var(--up); }
.hero-pulse.up::after    { background: var(--up); }
.hero-pulse.warn  { background: var(--warn); }
.hero-pulse.warn::after  { background: var(--warn); }
.hero-pulse.down  { background: var(--down); }
.hero-pulse.down::after  { background: var(--down); }
@keyframes pulse { 0%{transform:scale(1);opacity:.6} 100%{transform:scale(2.5);opacity:0} }
.hero-verdict { font-size: 26px; font-weight: 700; letter-spacing: 0.5px; }
.hero-verdict.up   { color: var(--up); }
.hero-verdict.warn { color: var(--warn); }
.hero-verdict.down { color: var(--down); }

.hero-right { background: var(--bg-2);
              border: 1px solid var(--bd); border-radius: var(--r); padding: 24px;
              box-shadow: var(--shadow-sm); display: flex; align-items: center;
              justify-content: center; gap: 24px; }
.donut { position: relative; width: 180px; height: 180px; flex-shrink: 0; }
.donut svg { transform: rotate(-90deg); }
.donut .center { position: absolute; inset: 0; display: flex;
                 flex-direction: column; align-items: center; justify-content: center; }
.donut .center .n { font-size: 38px; font-weight: 700;
                    font-variant-numeric: tabular-nums; }
.donut .center .l { font-size: 11px; color: var(--text-3);
                    text-transform: uppercase; letter-spacing: 1.5px; }
.legend { display: flex; flex-direction: column; gap: 10px; min-width: 180px; }
.legend-row { display: flex; align-items: center; justify-content: space-between;
              gap: 12px; font-size: 13px; }
.legend-row .left { display: flex; align-items: center; gap: 8px; }
.legend-dot { width: 10px; height: 10px; border-radius: 3px; }
.legend-row .n { font-weight: 600; font-variant-numeric: tabular-nums; }
.legend-row .l { color: var(--text-2); }

/* SUMMARY STATS */
.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
             margin-bottom: 28px; }
.stat-card { background: var(--bg-2); border: 1px solid var(--bd);
             border-radius: var(--r); padding: 16px 20px;
             position: relative; overflow: hidden; transition: transform .15s;
             box-shadow: var(--shadow-sm); }
.stat-card:hover { transform: translateY(-2px); }
.stat-card .accent { position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
                     border-radius: 3px 0 0 3px; }
.stat-card.total .accent { background: var(--info); }
.stat-card.up    .accent { background: var(--up); }
.stat-card.warn  .accent { background: var(--warn); }
.stat-card.down  .accent { background: var(--down); }
.stat-card .label { font-size: 11px; color: var(--text-3);
                    text-transform: uppercase; letter-spacing: 1.5px;
                    font-weight: 600; }
.stat-card .value { font-size: 34px; font-weight: 700; margin-top: 4px;
                    font-variant-numeric: tabular-nums; line-height: 1.05; }
.stat-card.total .value { color: var(--text); }
.stat-card.up    .value { color: var(--up); }
.stat-card.warn  .value { color: var(--warn); }
.stat-card.down  .value { color: var(--down); }
.stat-card .sub  { font-size: 12px; color: var(--text-2); margin-top: 4px; }

/* SECTIONS */
section { margin-bottom: 28px; }
.sect-head { display: flex; align-items: center; justify-content: space-between;
             margin-bottom: 14px; padding: 0 4px; }
.sect-head .h { display: flex; align-items: center; gap: 10px; }
.sect-head h2 { font-size: 13px; font-weight: 600; color: var(--text);
                text-transform: uppercase; letter-spacing: 1.5px; }
.sect-head .count { background: var(--bg-3); padding: 2px 9px; border-radius: 10px;
                     font-size: 11px; color: var(--text-2); font-weight: 600; }
.search { width: 320px; padding: 8px 14px; background: var(--bg-2);
          border: 1px solid var(--bd); border-radius: 8px; color: var(--text);
          font-size: 13px; transition: border-color .15s; }
.search:focus { outline: none; border-color: var(--info); }

/* CHIPS / FILTER */
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { background: var(--bg-2); border: 1px solid var(--bd); color: var(--text-2);
        padding: 6px 14px; border-radius: 18px; font-size: 12px; cursor: pointer;
        transition: all .15s; font-weight: 500; }
.chip:hover { background: var(--bg-3); color: var(--text); }
.chip.active { background: var(--info-bg); color: var(--info);
               border-color: var(--info); }

/* LIVENESS GRID */
.live-group { background: var(--bg-2); border: 1px solid var(--bd);
              border-radius: var(--r); padding: 16px 20px; margin-bottom: 14px;
              box-shadow: var(--shadow-sm); }
.live-group .head { display: flex; align-items: center; justify-content: space-between;
                     margin-bottom: 12px; }
.live-group .head .name { font-size: 13px; font-weight: 600;
                           text-transform: uppercase; letter-spacing: 1.5px; }
.live-group .head .mini-stats { display: flex; gap: 14px; font-size: 12px; }
.live-group .head .mini-stats span { color: var(--text-2);
                                       font-variant-numeric: tabular-nums; }
.live-group .head .mini-stats span b { color: var(--text); margin-right: 3px; }
.live-grid { display: grid;
             grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
             gap: 8px; }
.url-card { background: var(--bg-1); border: 1px solid var(--bd);
            border-radius: 8px; padding: 9px 12px; display: flex;
            align-items: center; gap: 12px; transition: all .15s; }
.url-card:hover { border-color: var(--bd); background: var(--bg-3); }
.url-card .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.url-card .body { flex: 1; min-width: 0; }
.url-card .lab { font-size: 13px; font-weight: 600;
                 white-space: nowrap; overflow: hidden;
                 text-overflow: ellipsis; color: var(--text); }
.url-card .url { font-size: 11px; color: var(--info); font-family: ui-monospace,
                  SFMono-Regular, Menlo, monospace; display: block;
                  white-space: nowrap; overflow: hidden;
                  text-overflow: ellipsis; margin-top: 2px;
                  text-decoration: none; }
.url-card .url:hover { color: #93c5fd; text-decoration: underline; }
.url-card .meta { font-size: 11px; color: var(--text-3); margin-top: 3px;
                  font-variant-numeric: tabular-nums; }
.bar { width: 60px; height: 4px; background: var(--bg-3); border-radius: 4px;
       overflow: hidden; flex-shrink: 0; }
.bar > div { height: 100%; border-radius: 4px; background: var(--up); }
.dot.up   { background: var(--up); }
.dot.slow { background: var(--warn); }
.dot.down { background: var(--down); }
.env-badge { display: inline-block; font-size: 9px; font-weight: 700;
             letter-spacing: .5px; padding: 1px 5px; border-radius: 4px;
             margin-right: 6px; vertical-align: 1px; }
.env-badge.prod { background: var(--up-bg); color: var(--up); }
.env-badge.dev  { background: var(--warn-bg); color: var(--warn); }
.proj-spoc { font-size: 10px; color: var(--text-3); margin-top: 2px; }

/* TIMELINE */
.timeline-card { background: var(--bg-2); border: 1px solid var(--bd);
                  border-radius: var(--r); padding: 20px 24px;
                  box-shadow: var(--shadow-sm); }
.timeline { display: flex; flex-direction: column; gap: 8px; }
.tl-row { display: grid; grid-template-columns: 200px 1fr 80px;
          gap: 14px; align-items: center; }
.tl-row .name { font-size: 12px; color: var(--text-2);
                white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }
.tl-bar-track { background: var(--bg-1); border-radius: 6px;
                height: 22px; position: relative; overflow: hidden; }
.tl-bar { height: 100%; border-radius: 6px; position: absolute;
           top: 0; min-width: 4px; transition: all .3s;
           display: flex; align-items: center;
           padding: 0 8px; font-size: 11px; color: rgba(255,255,255,0.9);
           font-variant-numeric: tabular-nums; overflow: hidden; }
.tl-bar.up    { background: var(--up); }
.tl-bar.warn  { background: var(--warn); }
.tl-bar.down  { background: var(--down); }
.tl-row .dur { font-size: 12px; color: var(--text-2); text-align: right;
               font-variant-numeric: tabular-nums; }

/* ENV partition */
.env-block { margin-bottom: 22px; }
.env-header { display: flex; align-items: center; justify-content: space-between;
              padding: 14px 18px; background: var(--bg-1);
              border: 1px solid var(--bd); border-radius: var(--r) var(--r) 0 0;
              border-bottom: none; }
.env-title { display: flex; align-items: center; gap: 14px; }
.env-bar { width: 4px; height: 34px; border-radius: 2px; }
.env-icon { font-size: 22px; line-height: 1; }
.env-name { font-size: 16px; font-weight: 700; letter-spacing: 0.2px; }
.env-desc { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.env-stats { display: flex; align-items: center; gap: 14px; }
.env-tally { font-size: 11px; color: var(--text-2); font-weight: 500;
             font-variant-numeric: tabular-nums; }
.env-tally b { margin-right: 3px; font-size: 13px; }
.env-block .scripts { border: 1px solid var(--bd); border-top: none;
                       border-radius: 0 0 var(--r) var(--r); padding: 10px;
                       background: var(--bg-1); }

/* SCRIPTS */
.scripts { display: flex; flex-direction: column; gap: 10px; }
.script { background: var(--bg-2); border: 1px solid var(--bd);
          border-radius: var(--r); overflow: hidden; transition: all .15s;
          box-shadow: var(--shadow-sm); }
.script:hover { box-shadow: var(--shadow); }
.script.open { border-color: var(--info); }
.script-head { padding: 14px 20px; display: grid;
               grid-template-columns: 28px 1fr auto auto;
               gap: 16px; align-items: center; cursor: pointer; user-select: none; }
.script-head:hover { background: var(--bg-1); }
.script-head .chev { color: var(--text-3); transition: transform .2s;
                     font-size: 12px; text-align: center; }
.script.open .script-head .chev { transform: rotate(90deg); }
.script-head .title { font-weight: 600; font-size: 14px; }
.script-head .fname { font-size: 11px; color: var(--text-3);
                      font-family: monospace; display: block; margin-top: 2px; }
.script-head .dur  { font-size: 12px; color: var(--text-2);
                     font-variant-numeric: tabular-nums; }
.pill { padding: 3px 10px; border-radius: 12px; font-size: 11px;
        font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.5px; display: inline-block; }
.pill.up      { background: var(--up-bg); color: var(--up); }
.pill.warn    { background: var(--warn-bg); color: var(--warn); }
.pill.down    { background: var(--down-bg); color: var(--down); }
.pill.unknown { background: var(--bg-3); color: var(--text-3); }
.script-body { padding: 0 20px 20px 64px; max-height: 0;
               overflow: hidden; transition: max-height .3s ease-out;
               border-top: 1px solid transparent; }
.script.open .script-body { max-height: 12000px; padding-top: 12px;
                             border-top-color: var(--bd); }
.script-body h3 { font-size: 12px; color: var(--text-2); margin-top: 12px;
                   margin-bottom: 6px; text-transform: uppercase;
                   letter-spacing: 1px; font-weight: 600; }
.steps-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.steps-table th { text-align: left; padding: 7px 10px; font-size: 10px;
                   text-transform: uppercase; letter-spacing: 1px;
                   color: var(--text-3); font-weight: 600;
                   border-bottom: 1px solid var(--bd); }
.steps-table td { padding: 10px; border-bottom: 1px solid var(--bg-3);
                   vertical-align: top; }
.steps-table tr:last-child td { border-bottom: none; }
.steps-table .name-cell { font-weight: 500; color: var(--text); }
.steps-table .url-mono { font-family: monospace; font-size: 10px;
                          color: var(--text-3); word-break: break-all;
                          margin-top: 3px; display: block; }
.steps-table .detail { color: var(--text-2); font-size: 12px; line-height: 1.45; }

/* SCREENSHOT + LIGHTBOX */
.code-tag { display: inline-block; font-family: monospace; font-size: 11px;
            font-weight: 700; padding: 1px 7px; border-radius: 5px;
            margin-right: 6px; background: var(--bg-3); color: var(--text-2); }
.code-tag.bad { background: var(--down-bg); color: var(--down); }
.shot-wrap { margin-top: 10px; }
.shot-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
              color: var(--text-3); font-weight: 600; margin-bottom: 5px; }
.shot { max-width: 260px; max-height: 160px; border: 1px solid var(--bd);
        border-radius: 6px; cursor: zoom-in; display: block;
        background: var(--bg-1); transition: border-color .15s, transform .15s; }
.shot:hover { border-color: var(--info); transform: scale(1.03); }
.shot-missing { font-size: 11px; color: var(--text-3); font-family: monospace;
                margin-top: 9px; }
.lightbox { position: fixed; inset: 0; background: rgba(3,6,12,0.93);
            display: none; align-items: center; justify-content: center;
            z-index: 999; cursor: zoom-out; padding: 44px; }
.lightbox.open { display: flex; }
.lightbox img { max-width: 100%; max-height: 100%; border-radius: 8px;
                border: 1px solid var(--bd);
                box-shadow: 0 24px 70px rgba(0,0,0,0.7); }
.lightbox .hint { position: fixed; top: 18px; right: 24px;
                  color: var(--text-3); font-size: 12px; }

/* DRAWER (mobile) */
@media (max-width: 980px) {
  .container { padding: 18px 16px 0; }
  .topbar-inner { padding: 11px 16px; }
  .hero { grid-template-columns: 1fr; }
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .script-head { grid-template-columns: 20px 1fr auto; gap: 12px; }
  .script-head .fname { display: none; }
  .tl-row { grid-template-columns: 110px 1fr 60px; }
}

footer { text-align: center; color: var(--text-3); font-size: 11px;
         margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--bd); }
.no-report { padding: 60px; text-align: center; color: var(--text-2);
             background: var(--bg-2); border-radius: var(--r);
             border: 1px solid var(--bd); }
</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-inner">
    <span class="topbar-brand">National e-Governance Division</span>
    <span class="topbar-sep">|</span>
    <span class="topbar-sub">myScheme — Synthetic Health Monitor</span>
  </div>
</div>
<div class="container" id="root">
  <!-- populated by JS -->
</div>
<div class="lightbox" id="lightbox" onclick="this.classList.remove('open')">
  <span class="hint">click anywhere to close</span>
  <img id="lightbox-img" alt="failure screenshot">
</div>

<script>
const DATA = __DATA_PLACEHOLDER__;

function classifyVerdict(v) {
  if (!v) return "unknown";
  const s = String(v).toUpperCase();
  if (s.includes("HEALTHY") || s === "UP" || s === "PASS" || s === "PASSED") return "up";
  if (s.includes("AUTH_EXPIRED")) return "warn";
  if (s.includes("DEGRADED") || s === "SLOW") return "warn";
  if (s === "TIMEOUT" || s === "ERROR" || s === "MISSING") return "down";
  if (s.includes("DOWN") || s === "FAIL" || s === "FAILED") return "down";
  return "unknown";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

// Open a failure screenshot full-screen
function openShot(src) {
  document.getElementById("lightbox-img").src = src;
  document.getElementById("lightbox").classList.add("open");
}

// Screenshot block for a step/route/bot that carries an artifact
function shotHtml(obj) {
  if (obj.artifact_img) {
    return `<div class="shot-wrap"><div class="shot-label">📷 Failure screenshot — click to enlarge</div>`
      + `<img class="shot" src="${obj.artifact_img}" onclick="openShot(this.src)" alt="failure screenshot"></div>`;
  }
  if (obj.artifact_note) {
    return `<div class="shot-missing">📷 ${escapeHtml(obj.artifact_note)}</div>`;
  }
  if (obj.artifact) {
    return `<div class="shot-missing">📷 ${escapeHtml(String(obj.artifact).split("/").pop())} — see _hc_artifacts/</div>`;
  }
  return "";
}

function fmtTs(s) {
  if (!s) return "—";
  return s.replace("T", " ").replace(/\+\d\d:\d\d/, " IST");
}

// ====== compute aggregate stats ======
function computeStats() {
  const scripts = DATA.scripts || [];
  const live = DATA.liveness || {results:[], counts:{}};
  let up = 0, warn = 0, down = 0;
  scripts.forEach(s => {
    const c = classifyVerdict(s.verdict);
    if (c === "up") up++; else if (c === "warn") warn++; else if (c === "down") down++;
  });
  // liveness contributions
  const lup = live.counts?.UP || 0;
  const lwarn = live.counts?.SLOW || 0;
  const ldown = live.counts?.DOWN || 0;
  return {
    scripts: { total: scripts.length, up, warn, down },
    liveness: { total: (live.results||[]).length, up: lup, warn: lwarn, down: ldown },
    combined: {
      total: scripts.length + (live.results||[]).length,
      up: up + lup, warn: warn + lwarn, down: down + ldown,
    },
  };
}

function overallVerdict(stats) {
  if (stats.combined.down > 0) return "down";
  if (stats.combined.warn > 0) return "warn";
  return "up";
}

// ====== animated counter ======
function animateCounter(el, target, dur=900) {
  const start = performance.now();
  const initial = 0;
  function step(t) {
    const p = Math.min(1, (t - start) / dur);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(initial + (target - initial) * eased);
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ====== SVG donut ======
function renderDonut(stats) {
  const total = Math.max(1, stats.combined.total);
  const up = stats.combined.up;
  const warn = stats.combined.warn;
  const down = stats.combined.down;
  const radius = 70, stroke = 18, cx = 90, cy = 90;
  const circ = 2 * Math.PI * radius;
  function arc(value, color, offset) {
    const len = (value/total) * circ;
    return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="none"
       stroke="${color}" stroke-width="${stroke}"
       stroke-dasharray="${len} ${circ}" stroke-dashoffset="${-offset}"
       stroke-linecap="butt"/>`;
  }
  const upLen = (up/total)*circ, warnLen = (warn/total)*circ;
  const svg = `<svg width="180" height="180" viewBox="0 0 180 180">
    <circle cx="${cx}" cy="${cy}" r="${radius}" fill="none"
            stroke="#e4e8ef" stroke-width="${stroke}"/>
    ${arc(up,'#16a34a',0)}
    ${arc(warn,'#d97706',upLen)}
    ${arc(down,'#dc2626',upLen+warnLen)}
  </svg>`;
  const healthPct = Math.round((up / total) * 100);
  return `
    <div class="donut">
      ${svg}
      <div class="center">
        <div class="n" id="donut-pct" data-pct="${healthPct}">0%</div>
        <div class="l">Healthy</div>
      </div>
    </div>
    <div class="legend">
      <div class="legend-row"><div class="left"><span class="legend-dot" style="background:var(--up)"></span><span class="l">Healthy</span></div><span class="n">${up}</span></div>
      <div class="legend-row"><div class="left"><span class="legend-dot" style="background:var(--warn)"></span><span class="l">Degraded</span></div><span class="n">${warn}</span></div>
      <div class="legend-row"><div class="left"><span class="legend-dot" style="background:var(--down)"></span><span class="l">Down</span></div><span class="n">${down}</span></div>
      <div class="legend-row" style="margin-top:6px;padding-top:8px;border-top:1px solid var(--bd)">
        <span class="l">Total</span><span class="n">${stats.combined.total}</span>
      </div>
    </div>`;
}

// ====== hero ======
function renderHero(stats) {
  const ov = overallVerdict(stats);
  const ovLabel = ({up:"All Systems Healthy", warn:"Degraded", down:"Issues Detected"})[ov];
  return `
    <div class="hero">
      <div class="hero-left">
        <div>
          <div class="hero-eyebrow">NeGD myScheme — Synthetic Health Dashboard</div>
          <h1 class="hero-title">${ovLabel}</h1>
          <div class="hero-sub">Auto-generated from <code>master_report.json</code> — last run at ${fmtTs(DATA.ended_ist)}</div>
        </div>
        <div>
          <div class="hero-status">
            <div class="hero-pulse ${ov}"></div>
            <div class="hero-verdict ${ov}">${ov === "up" ? "HEALTHY" : (ov === "warn" ? "DEGRADED" : "DOWN")}</div>
          </div>
          <div class="hero-meta">
            <div class="hero-meta-item"><div class="k">Started</div><div class="v">${fmtTs(DATA.started_ist)}</div></div>
            <div class="hero-meta-item"><div class="k">Ended</div><div class="v">${fmtTs(DATA.ended_ist)}</div></div>
            <div class="hero-meta-item"><div class="k">Duration</div><div class="v">${DATA.total_duration_s ?? "?"}s</div></div>
          </div>
        </div>
      </div>
      <div class="hero-right">
        ${renderDonut(stats)}
      </div>
    </div>`;
}

// ====== summary stats ======
function renderStats(stats) {
  const c = stats.combined;
  return `
    <div class="stats-row">
      <div class="stat-card total"><div class="accent"></div>
        <div class="label">Total checks</div>
        <div class="value" data-n="${c.total}">0</div>
        <div class="sub">${stats.scripts.total} scripts · ${stats.liveness.total} URLs</div>
      </div>
      <div class="stat-card up"><div class="accent"></div>
        <div class="label">Healthy</div>
        <div class="value" data-n="${c.up}">0</div>
        <div class="sub">${(100*c.up/Math.max(1,c.total)).toFixed(0)}% of checks</div>
      </div>
      <div class="stat-card warn"><div class="accent"></div>
        <div class="label">Degraded</div>
        <div class="value" data-n="${c.warn}">0</div>
        <div class="sub">Investigate</div>
      </div>
      <div class="stat-card down"><div class="accent"></div>
        <div class="label">Down</div>
        <div class="value" data-n="${c.down}">0</div>
        <div class="sub">Action required</div>
      </div>
    </div>`;
}

// ====== timeline (gantt-like) ======
function renderTimeline() {
  const scripts = DATA.scripts || [];
  if (!scripts.length) return "";
  const max = Math.max(1, ...scripts.map(s => s.duration_s || 0));
  let html = `<section><div class="sect-head"><div class="h"><h2>Execution Timeline</h2><span class="count">${scripts.length}</span></div></div><div class="timeline-card"><div class="timeline">`;
  scripts.forEach(s => {
    const cls = classifyVerdict(s.verdict);
    const pct = ((s.duration_s || 0) / max) * 100;
    const verdict = s.verdict || "—";
    html += `<div class="tl-row" title="${escapeHtml(verdict)}">
      <span class="name">${escapeHtml(s.label || s.filename || "")}</span>
      <div class="tl-bar-track">
        <div class="tl-bar ${cls}" style="width:${pct}%">${pct > 14 ? escapeHtml(verdict) : ""}</div>
      </div>
      <span class="dur">${s.duration_s ?? "?"}s</span>
    </div>`;
  });
  html += `</div></div></section>`;
  return html;
}

// ====== liveness grouped ======
function renderLiveness(stats) {
  const results = DATA.liveness?.results || [];
  if (!results.length) return "";
  // Group by PROJECT, preserving first-seen (registry) order.
  const groups = {};
  const projOrder = [];
  results.forEach(r => {
    const proj = r.project || "Other";
    if (!groups[proj]) { groups[proj] = []; projOrder.push(proj); }
    groups[proj].push(r);
  });
  // Within a project: down -> slow -> up, then label.
  const sev = {DOWN:0, SLOW:1, UP:2};
  projOrder.forEach(p => groups[p].sort((a,b) =>
    (sev[a.status]??9)-(sev[b.status]??9) || (a.label||"").localeCompare(b.label||"")));
  const spocs = DATA.project_spocs || {};

  let html = `<section>
    <div class="sect-head">
      <div class="h"><h2>${results.length}-URL Liveness Sweep</h2><span class="count">${projOrder.length} projects</span></div>
      <input type="text" class="search" id="live-search" placeholder="Filter URLs / projects…">
    </div>`;
  const maxMs = Math.max(1, ...results.map(r => r.ms || 0));
  projOrder.forEach(proj => {
    const arr = groups[proj];
    let up=0, slow=0, down=0;
    arr.forEach(r => { if(r.status==="UP")up++; else if(r.status==="SLOW")slow++; else down++; });
    const spoc = spocs[proj] || {};
    const spocLabel = spoc.name
      ? "SPOC: " + escapeHtml(spoc.name) + (spoc.email ? " &lt;" + escapeHtml(spoc.email) + "&gt;" : "")
      : "SPOC: unassigned";
    html += `<div class="live-group" data-project="${escapeHtml(proj)}">
      <div class="head">
        <div>
          <div class="name">${escapeHtml(proj)}</div>
          <div class="proj-spoc">${spocLabel}</div>
        </div>
        <div class="mini-stats">
          <span><b>${up}</b>up</span>
          <span><b>${slow}</b>slow</span>
          <span><b>${down}</b>down</span>
        </div>
      </div>
      <div class="live-grid">`;
    arr.forEach(r => {
      const cls = r.status === "UP" ? "up" : (r.status === "SLOW" ? "slow" : "down");
      const pct = Math.min(100, ((r.ms || 0)/maxMs)*100);
      const isDev = String(r.environment || "production").toLowerCase().startsWith("dev");
      const envBadge = isDev
        ? `<span class="env-badge dev">DEV</span>`
        : `<span class="env-badge prod">PROD</span>`;
      html += `<div class="url-card" data-label="${escapeHtml((r.label+" "+r.url+" "+proj).toLowerCase())}" title="${escapeHtml(r.url || "")}">
        <span class="dot ${cls}"></span>
        <div class="body">
          <div class="lab">${envBadge}${escapeHtml(r.label)}</div>
          <a class="url" href="${escapeHtml(r.url || "#")}" target="_blank" rel="noopener">${escapeHtml(r.url || "")}</a>
          <div class="meta">HTTP ${r.http ?? "?"} · ${r.ms ?? "?"}ms${r.err ? " · err" : ""}</div>
        </div>
        <div class="bar"><div style="width:${pct}%;background:${cls==='up'?'var(--up)':cls==='slow'?'var(--warn)':'var(--down)'}"></div></div>
      </div>`;
    });
    html += `</div></div>`;
  });
  html += `</section>`;
  return html;
}

// ====== scripts ======
function renderScript(s, idx) {
  const cls = classifyVerdict(s.verdict);
  const verdict = s.verdict || "UNKNOWN";
  let bodyHtml = "";
  const p = s.payload;
  if (p) {
    const top = p.overall || p.verdict;
    if (top) bodyHtml += `<h3>Overall</h3><div class="detail" style="color:var(--text-2);font-size:13px">${escapeHtml(String(top))}</div>`;
    // Domain-grouped steps (dev/umang style)
    if (Array.isArray(p.steps) && p.steps.some(x => Array.isArray(x.checks))) {
      p.steps.filter(x => Array.isArray(x.checks)).forEach(group => {
        const dcls = classifyVerdict(group.verdict);
        bodyHtml += `<h3>${escapeHtml(group.domain || group.name || "")}  <span class="pill ${dcls}" style="margin-left:8px">${escapeHtml(group.verdict || "")}</span></h3>`;
        bodyHtml += stepsTable(group.checks);
      });
    } else if (Array.isArray(p.steps) && p.steps.length) {
      bodyHtml += `<h3>Steps</h3>${stepsTable(p.steps)}`;
    }
    if (Array.isArray(p.bots) && p.bots.length) {
      bodyHtml += `<h3>Bot replies</h3>${botsTable(p.bots)}`;
    }
  } else if (s.detail) {
    bodyHtml = `<div class="detail" style="color:var(--text-2);font-size:13px;margin-top:8px">${escapeHtml(s.detail)}</div>`;
  } else if (s.stderr_tail) {
    bodyHtml = `<div class="detail" style="color:var(--text-3);font-size:12px;font-family:monospace;margin-top:8px;white-space:pre-wrap">${escapeHtml(s.stderr_tail)}</div>`;
  } else {
    bodyHtml = `<div class="detail" style="color:var(--text-3);margin-top:8px">No detailed payload captured.</div>`;
  }
  return `<div class="script" data-cls="${cls}" data-name="${escapeHtml((s.label||"").toLowerCase())}">
    <div class="script-head" onclick="this.parentElement.classList.toggle('open')">
      <span class="chev">▸</span>
      <div>
        <div class="title">${escapeHtml(s.label || "")}</div>
        <span class="fname">${escapeHtml(s.filename || "")}</span>
      </div>
      <span class="pill ${cls}">${escapeHtml(verdict)}</span>
      <span class="dur">${s.duration_s ?? "?"}s</span>
    </div>
    <div class="script-body">${bodyHtml}</div>
  </div>`;
}

function stepsTable(steps) {
  let html = `<table class="steps-table"><thead><tr>
    <th>Step</th><th>Verdict</th><th>Latency</th><th>Detail</th>
  </tr></thead><tbody>`;
  steps.forEach(st => {
    const v = st.verdict || st.status;            // dev/umang use verdict, E2E uses status
    const cls = classifyVerdict(v);
    const finalUrl = st.final_url && st.final_url !== st.url ?
      `<span class="url-mono">↳ ${escapeHtml(st.final_url.slice(0,140))}${st.final_url.length>140?"…":""}</span>` : "";
    const detail = (st.detail || "").length > 280 ? (st.detail.slice(0,280) + "…") : (st.detail || "");
    const code = (st.http_status != null)
      ? `<span class="code-tag ${st.http_status >= 400 ? "bad" : ""}">HTTP ${escapeHtml(st.http_status)}</span>` : "";
    html += `<tr>
      <td class="name-cell">${escapeHtml(st.name || "")}${st.url ? `<span class="url-mono">${escapeHtml(st.url)}</span>` : ""}</td>
      <td><span class="pill ${cls}">${escapeHtml(v || "?")}</span></td>
      <td style="color:var(--text-2);font-variant-numeric:tabular-nums">${st.duration_ms ?? "?"}ms</td>
      <td>${code}<span class="detail">${escapeHtml(detail)}</span>${finalUrl}${cls !== "up" ? shotHtml(st) : ""}</td>
    </tr>`;
  });
  return html + "</tbody></table>";
}

function botsTable(bots) {
  let html = `<table class="steps-table"><thead><tr>
    <th>Bot</th><th>Query</th><th>Verdict</th><th>Latency</th><th>Reply excerpt</th>
  </tr></thead><tbody>`;
  bots.forEach(b => {
    const cls = classifyVerdict(b.verdict);
    const reply = b.reply_excerpt || b.detail || "";
    const replyShort = reply.length > 220 ? reply.slice(0,220)+"…" : reply;
    html += `<tr>
      <td class="name-cell">${escapeHtml(b.name || "")}<span class="url-mono">${escapeHtml(b.url || "")}</span></td>
      <td><span class="detail">${escapeHtml(b.query || "")}</span></td>
      <td><span class="pill ${cls}">${escapeHtml(b.verdict || "?")}</span></td>
      <td style="color:var(--text-2);font-variant-numeric:tabular-nums">${b.reply_latency_ms ?? "?"}ms</td>
      <td><span class="detail">${escapeHtml(replyShort)}</span>${cls !== "up" ? shotHtml(b) : ""}</td>
    </tr>`;
  });
  return html + "</tbody></table>";
}

// Map a script filename to an environment partition
function scriptEnv(filename) {
  const f = (filename || "").toLowerCase();
  if (f.includes("dev_environment")) return "Dev";
  if (f.includes("umang"))            return "UMANG";
  if (f.includes("chatbot_endpoints")) return "Chatbot";
  return "Production";
}

const ENV_META = {
  "Production": {color: "var(--up)",   icon: "🏛", desc: "myScheme.gov.in production portals + public services"},
  "Chatbot":    {color: "var(--info)", icon: "💬", desc: "Standalone domain chatbots (D.o.E, PSQ, Sandarbh, NMC, TATHYA, SAI)"},
  "Dev":        {color: "var(--warn)", icon: "🛠", desc: "dev.* subdomains behind AWS Cognito perimeter"},
  "UMANG":      {color: "#a78bfa",     icon: "🌐", desc: "UMANG mirror (myapp/mycms/myforms.umangapp.in)"},
};
const ENV_ORDER = ["Production", "Chatbot", "Dev", "UMANG"];

function groupVerdict(items) {
  const cs = items.map(s => classifyVerdict(s.verdict));
  if (cs.every(c => c === "up")) return "up";
  if (cs.some(c => c === "down")) return "down";
  return "warn";
}

function renderScripts() {
  const scripts = DATA.scripts || [];
  // partition
  const groups = {};
  scripts.forEach(s => {
    const env = scriptEnv(s.filename);
    (groups[env] = groups[env] || []).push(s);
  });

  let html = `<section>
    <div class="sect-head">
      <div class="h"><h2>Functional Check Scripts</h2><span class="count">${scripts.length}</span></div>
      <div class="chips" id="script-chips">
        <span class="chip active" data-f="all">All</span>
        <span class="chip" data-f="up">Healthy</span>
        <span class="chip" data-f="warn">Degraded</span>
        <span class="chip" data-f="down">Down</span>
      </div>
    </div>
    <div id="scripts-root">`;
  ENV_ORDER.forEach(env => {
    const arr = groups[env] || [];
    if (!arr.length) return;
    const gv = groupVerdict(arr);
    const meta = ENV_META[env] || {color: "var(--text-2)", icon: "•", desc: ""};
    const up = arr.filter(s => classifyVerdict(s.verdict)==="up").length;
    const wn = arr.filter(s => classifyVerdict(s.verdict)==="warn").length;
    const dn = arr.filter(s => classifyVerdict(s.verdict)==="down").length;
    html += `<div class="env-block" data-env="${escapeHtml(env)}">
      <div class="env-header">
        <div class="env-title">
          <span class="env-bar" style="background:${meta.color}"></span>
          <span class="env-icon">${meta.icon}</span>
          <div>
            <div class="env-name">${escapeHtml(env)}</div>
            <div class="env-desc">${escapeHtml(meta.desc)}</div>
          </div>
        </div>
        <div class="env-stats">
          <span class="pill ${gv}" style="margin-right:10px">${gv === "up" ? "HEALTHY" : (gv === "warn" ? "DEGRADED" : "DOWN")}</span>
          <span class="env-tally"><b style="color:var(--up)">${up}</b> up</span>
          <span class="env-tally"><b style="color:var(--warn)">${wn}</b> degraded</span>
          <span class="env-tally"><b style="color:var(--down)">${dn}</b> down</span>
        </div>
      </div>
      <div class="scripts" data-group="${escapeHtml(env)}">
        ${arr.map((s,i) => renderScript(s,i)).join("")}
      </div>
    </div>`;
  });
  html += `</div></section>`;
  return html;
}

// ====== orchestrator ======
function render() {
  if (!DATA || !Object.keys(DATA).length) {
    document.getElementById("root").innerHTML =
      '<div class="no-report">No report data found. Run <code>master_health_check.py</code> first.</div>';
    return;
  }
  const stats = computeStats();
  const root = document.getElementById("root");
  root.innerHTML =
    renderHero(stats) +
    renderStats(stats) +
    renderTimeline() +
    renderLiveness(stats) +
    renderScripts() +
    `<footer>Generated from ${stats.scripts.total} script(s) + ${stats.liveness.total} URL(s) at ${fmtTs(DATA.ended_ist)}</footer>`;

  // Animate stat counters
  document.querySelectorAll(".stat-card .value[data-n]").forEach(el => {
    const target = parseInt(el.dataset.n, 10) || 0;
    animateCounter(el, target);
  });

  // Animate the donut's health-percentage counter
  const dp = document.getElementById("donut-pct");
  if (dp) {
    const target = parseInt(dp.dataset.pct, 10) || 0;
    const s0 = performance.now();
    (function step(t) {
      const p = Math.min(1, (t - s0) / 900);
      const e = 1 - Math.pow(1 - p, 3);
      dp.textContent = Math.round(target * e) + "%";
      if (p < 1) requestAnimationFrame(step);
    })(performance.now());
  }

  // Wire up liveness filter
  const liveSearch = document.getElementById("live-search");
  if (liveSearch) {
    liveSearch.addEventListener("input", e => {
      const f = e.target.value.toLowerCase().trim();
      document.querySelectorAll(".url-card").forEach(c => {
        c.style.display = (!f || c.dataset.label.includes(f)) ? "" : "none";
      });
    });
  }

  // Wire up script filter chips (also hides empty env blocks)
  const chips = document.getElementById("script-chips");
  if (chips) {
    chips.addEventListener("click", e => {
      const t = e.target.closest(".chip");
      if (!t) return;
      chips.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
      t.classList.add("active");
      const f = t.dataset.f;
      document.querySelectorAll(".script").forEach(s => {
        s.style.display = (f === "all" || s.dataset.cls === f) ? "" : "none";
      });
      // hide env blocks with no visible scripts
      document.querySelectorAll(".env-block").forEach(b => {
        const visible = Array.from(b.querySelectorAll(".script"))
          .filter(s => s.style.display !== "none").length;
        b.style.display = visible ? "" : "none";
      });
    });
  }
}

render();
</script>
</body>
</html>"""

def _load_project_spocs():
    """Project -> {name,email} map from url_registry.json, for dashboard display."""
    try:
        with open(os.path.join(HERE, "url_registry.json")) as f:
            reg = json.load(f)
        return {p.get("name", "Other"): p.get("spoc", {}) for p in reg.get("projects", [])}
    except Exception:
        return {}


def _is_healthy(node):
    """A step/route/bot counts as healthy if its verdict/status says so."""
    v = str(node.get("verdict") or node.get("status") or "").upper()
    return v in ("UP", "PASS", "PASSED") or "HEALTHY" in v


def _embed_screenshots(node):
    """Recursively walk the report; for any *non-healthy* object carrying an
    `artifact` screenshot path, inline the PNG as a base64 data-URI in
    `artifact_img` so the dashboard stays a single self-contained file.
    Healthy steps are skipped — screenshots are only for degraded/down/
    not-working-as-expected items. Returns the count of screenshots embedded."""
    count = 0
    if isinstance(node, dict):
        art = node.get("artifact")
        if isinstance(art, str) and art.strip() and not _is_healthy(node):
            path = art if os.path.isfile(art) else os.path.join(ART_DIR, os.path.basename(art))
            if os.path.isfile(path):
                try:
                    size = os.path.getsize(path)
                    if size <= MAX_EMBED_BYTES:
                        with open(path, "rb") as fh:
                            b64 = base64.b64encode(fh.read()).decode("ascii")
                        node["artifact_img"] = "data:image/png;base64," + b64
                        count += 1
                    else:
                        node["artifact_note"] = (
                            f"{os.path.basename(path)} ({size // 1024} KB) — too large "
                            f"to inline; see _hc_artifacts/")
                except Exception as e:
                    node["artifact_note"] = f"could not embed screenshot: {e}"
        for v in node.values():
            count += _embed_screenshots(v)
    elif isinstance(node, list):
        for v in node:
            count += _embed_screenshots(v)
    return count


def main():
    if not os.path.exists(REPORT):
        data = {}
        print(f"[warn] No master_report.json at {REPORT}; emitting empty dashboard.", flush=True)
    else:
        with open(REPORT) as f:
            data = json.load(f)
        print(f"[ok] Loaded report: {os.path.getsize(REPORT)} bytes", flush=True)
    if data:
        data["project_spocs"] = _load_project_spocs()
    shots = _embed_screenshots(data)
    if shots:
        print(f"[ok] Embedded {shots} failure screenshot(s) into the dashboard.", flush=True)
    embedded = json.dumps(data)
    out = TEMPLATE.replace("__DATA_PLACEHOLDER__", embedded)
    with open(OUT, "w") as f:
        f.write(out)
    print(f"[ok] Wrote dashboard: {OUT}")
    print(f"[ok] Open in browser:  file://{OUT}")

if __name__ == "__main__":
    main()

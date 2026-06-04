"""Luminous Glass — the one design-system source shared by both front-ends.

Spec Part A. Defined once here and reused by:
  * orchestration/dashboard.py — inlines DESIGN_TOKENS_CSS + SVG_SPRITE +
    THEME_BOOT_JS into its self-contained TEMPLATE.
  * web/ control panel — create_app() injects the same strings into
    index.html via the template context; static/style.css carries only the
    component rules that reference these tokens.

Everything here is offline-safe: fonts fall back to system stacks, icons are
inline SVG, zero external requests.

Light ("Luminous Glass") is the default; a dark variant lives under
`[data-theme="dark"]`. THEME_BOOT_JS sets the initial theme from
localStorage (falling back to prefers-color-scheme) BEFORE first paint to
avoid a flash, and exposes `toggleTheme()` for the header toggle button.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Design tokens — light default + dark override. Component CSS references
# only these custom properties, so theming is a single attribute flip.
# --------------------------------------------------------------------------
DESIGN_TOKENS_CSS = r"""
:root {
  color-scheme: light;
  /* Google / Material — light. Solid white cards lifted by elevation shadow
     (not hard borders), on a soft Google-grey base. No grid texture. */
  --bg-grad: linear-gradient(180deg, #ffffff 0%, #f1f3f4 100%);
  --grid-line: transparent;
  --grid-size: 22px;
  --glass: #ffffff;
  --glass-2: #f1f3f4;
  --glass-border: #e8eaed;            /* whisper-soft hairline; depth = shadow */
  --glass-highlight: transparent;
  --blur: 0px;
  --shadow: 0 1px 2px rgba(60,64,67,.20), 0 2px 6px 2px rgba(60,64,67,.10);
  --shadow-lg: 0 4px 8px 3px rgba(60,64,67,.13), 0 1px 3px rgba(60,64,67,.22);
  /* Google brand colours — the signature four. */
  --g-blue: #4285f4; --g-red: #ea4335; --g-yellow: #fbbc04; --g-green: #34a853;
  --accent-1: #1a73e8; --accent-2: #4285f4;
  --accent: linear-gradient(90deg, #4285f4, #1a73e8);
  /* status — Google hues, kept text-legible on the light tints */
  --up:   #1e8e3e; --up-tint:   rgba(30,142,62,.12);
  --warn: #e37400; --warn-tint: rgba(249,171,0,.16);
  --down: #d93025; --down-tint: rgba(217,48,37,.12);
  --auth: #a142f4; --auth-tint: rgba(161,66,244,.13);
  --info: #1a73e8; --info-tint: rgba(26,115,232,.12);
  /* text — Google greys */
  --text: #202124;
  --text-2: #5f6368;
  --text-3: #80868b;
  /* fonts — self-hosted Roboto (vendored woff2; see reporting/fonts.py), the
     real Material typeface, with a system fallback. Offline-safe, no fetch. */
  --font-ui: "Roboto", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: "Roboto Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --r: 12px;
  --r-sm: 8px;
}
[data-theme="dark"] {
  color-scheme: dark;
  /* Google / Material — dark. */
  --bg-grad: linear-gradient(180deg, #202124 0%, #17181a 100%);
  --grid-line: transparent;
  --glass: #2a2b2e;
  --glass-2: #35363a;
  --glass-border: #3c4043;
  --glass-highlight: transparent;
  --shadow: 0 1px 2px rgba(0,0,0,.55), 0 2px 6px 2px rgba(0,0,0,.35);
  --shadow-lg: 0 4px 10px 3px rgba(0,0,0,.5), 0 1px 3px rgba(0,0,0,.6);
  --g-blue: #8ab4f8; --g-red: #f28b82; --g-yellow: #fdd663; --g-green: #81c995;
  --accent-1: #8ab4f8; --accent-2: #aecbfa;
  --accent: linear-gradient(90deg, #aecbfa, #8ab4f8);
  --up:   #81c995; --up-tint:   rgba(129,201,149,.16);
  --warn: #fdd663; --warn-tint: rgba(253,214,99,.16);
  --down: #f28b82; --down-tint: rgba(242,139,130,.16);
  --auth: #c58af9; --auth-tint: rgba(197,138,249,.18);
  --info: #8ab4f8; --info-tint: rgba(138,180,248,.16);
  --text: #e8eaed;
  --text-2: #9aa0a6;
  --text-3: #80868b;
}

/* The textured, luminous page base both UIs share. */
.lg-body {
  background: var(--bg-grad);
  background-attachment: fixed;
  color: var(--text);
  font-family: var(--font-ui);
  -webkit-font-smoothing: antialiased;
  position: relative;
}
.lg-body::before {
  content: "";
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: var(--grid-size) var(--grid-size);
}

/* Material surface primitive — solid card, elevation shadow, soft edge. */
.glass {
  background: var(--glass);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow);
  border-radius: var(--r);
}

/* Signature Google four-colour stripe — the page's top accent, the "life". */
.google-stripe {
  height: 4px; border: 0; flex: none;
  background: linear-gradient(90deg,
    var(--g-blue)   0 25%,
    var(--g-red)   25% 50%,
    var(--g-yellow) 50% 75%,
    var(--g-green) 75% 100%);
}

/* Inline icon defaults — 1.5px Lucide-style line icons, tinted by currentColor. */
.icon {
  width: 1em; height: 1em; flex-shrink: 0;
  fill: none; stroke: currentColor;
  stroke-width: 1.75; stroke-linecap: round; stroke-linejoin: round;
  vertical-align: -0.125em;
}
.icon-fill { fill: currentColor; stroke: none; }

/* Theme toggle button — shared by both UIs. */
.theme-toggle {
  display: inline-grid; place-items: center;
  width: 34px; height: 34px; border-radius: 10px;
  background: var(--glass-2); border: 1px solid var(--glass-border);
  color: var(--text-2); cursor: pointer; padding: 0;
  transition: color .15s, transform .15s, box-shadow .15s;
}
.theme-toggle:hover { color: var(--text); box-shadow: var(--shadow); }
.theme-toggle .icon { width: 17px; height: 17px; }
.theme-toggle .i-moon { display: none; }
.theme-toggle .i-sun  { display: block; }
[data-theme="dark"] .theme-toggle .i-moon { display: block; }
[data-theme="dark"] .theme-toggle .i-sun  { display: none; }

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: .001ms !important; animation-iteration-count: 1 !important;
      transition-duration: .001ms !important; }
}
"""


# --------------------------------------------------------------------------
# Icon sprite — one inline SVG of <symbol>s, referenced via <use href="#i-..">.
# 24x24 viewBoxes, Lucide-style. No icon font, no CDN.
# --------------------------------------------------------------------------
SVG_SPRITE = r"""
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
  <symbol id="i-activity" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></symbol>
  <symbol id="i-layout-grid" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></symbol>
  <symbol id="i-braces" viewBox="0 0 24 24"><path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5a2 2 0 0 0 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5a2 2 0 0 1 2-2 2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/></symbol>
  <symbol id="i-history" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></symbol>
  <symbol id="i-refresh-cw" viewBox="0 0 24 24"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></symbol>
  <symbol id="i-play" viewBox="0 0 24 24"><polygon class="icon-fill" points="6 3 20 12 6 21 6 3"/></symbol>
  <symbol id="i-log-in" viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></symbol>
  <symbol id="i-trash" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></symbol>
  <symbol id="i-chevron" viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></symbol>
  <symbol id="i-check-circle" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></symbol>
  <symbol id="i-alert-triangle" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></symbol>
  <symbol id="i-x-circle" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></symbol>
  <symbol id="i-shield-x" viewBox="0 0 24 24"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><line x1="9.5" y1="9" x2="14.5" y2="14"/><line x1="14.5" y1="9" x2="9.5" y2="14"/></symbol>
  <symbol id="i-x" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></symbol>
  <symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></symbol>
  <symbol id="i-image" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></symbol>
  <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/></symbol>
  <symbol id="i-moon" viewBox="0 0 24 24"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></symbol>
</svg>
"""


# Markup for the toggle button itself (both icons; CSS shows the right one).
THEME_TOGGLE_BUTTON = (
    '<button class="theme-toggle" type="button" onclick="toggleTheme()" '
    'title="Toggle light / dark theme" aria-label="Toggle light / dark theme">'
    '<svg class="icon i-sun"><use href="#i-sun"></use></svg>'
    '<svg class="icon i-moon"><use href="#i-moon"></use></svg>'
    "</button>"
)


# Runs BEFORE paint (place in <head>) so there is no light->dark flash.
THEME_BOOT_JS = r"""
(function () {
  function pick() {
    try {
      var s = localStorage.getItem("hc-theme");
      if (s === "light" || s === "dark") return s;
    } catch (e) {}
    return (window.matchMedia &&
            window.matchMedia("(prefers-color-scheme: dark)").matches)
           ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", pick());
})();
function toggleTheme() {
  var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  var next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("hc-theme", next); } catch (e) {}
}
"""

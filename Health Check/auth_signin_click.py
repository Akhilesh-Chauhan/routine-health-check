"""Navigate to auth.myscheme.gov.in, click 'Already a user' platform option, see what happens."""
from playwright.sync_api import sync_playwright
import os, time, json

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_browser_profile"
TARGET = "https://auth.myscheme.gov.in/"
ART_DIR = "/home/user/NeGD/Claude Code/Health Check/_hc_artifacts"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 1366, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(TARGET, wait_until="networkidle", timeout=20_000)
    time.sleep(2)

    page.screenshot(path=f"{ART_DIR}/auth_landing.png", full_page=True)

    # Enumerate clickables under "Already a user?" section
    print("=== All clickable elements on auth page ===")
    items = page.evaluate(r"""
      () => {
        const out = [];
        document.querySelectorAll('a, button, [role="button"], img[alt], div[onclick]').forEach(el => {
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return;
          out.push({
            tag: el.tagName,
            href: el.getAttribute('href'),
            text: (el.innerText || el.getAttribute('alt') || el.getAttribute('aria-label') || '').slice(0, 80).replace(/\s+/g,' '),
            cls: (el.className || '').toString().slice(0, 100),
            x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
          });
        });
        return out;
      }
    """)
    for it in items:
        print(it)

    # Find "Already a user?" section anchor and list the sibling sign-in platforms
    print("\n=== Section text + nearby elements ===")
    sect_info = page.evaluate(r"""
      () => {
        function findAncestorWith(el, text) {
          let cur = el;
          while (cur) {
            if ((cur.innerText || '').toLowerCase().includes(text.toLowerCase())) return cur;
            cur = cur.parentElement;
          }
          return null;
        }
        const all = document.querySelectorAll('*');
        let anchor = null;
        for (const el of all) {
          if ((el.innerText || '').trim().toLowerCase().startsWith('already a user')) { anchor = el; break; }
        }
        if (!anchor) return {found: false};
        // walk up to a section that also has sign-in links
        let cont = anchor.parentElement;
        for (let i=0; i<8 && cont; i++) {
          if (cont.querySelectorAll('a, button, img').length > 0) break;
          cont = cont.parentElement;
        }
        const childInfo = [];
        cont.querySelectorAll('a, button, img').forEach(el => {
          const r = el.getBoundingClientRect();
          childInfo.push({
            tag: el.tagName, href: el.getAttribute('href'),
            alt: el.getAttribute('alt'),
            text: (el.innerText || el.getAttribute('alt') || '').slice(0,80).replace(/\s+/g,' '),
            x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
            cls: (el.className || '').toString().slice(0, 80),
          });
        });
        return {found: true, anchorText: (anchor.innerText||'').slice(0,200), childInfo};
      }
    """)
    print(json.dumps(sect_info, indent=2))
    ctx.close()

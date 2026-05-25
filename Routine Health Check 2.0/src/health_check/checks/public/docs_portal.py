"""Health check for https://docs.myscheme.in/ and its versioned API category pages."""
from health_check.paths import ARTIFACTS_DIR
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ART_DIR = str(ARTIFACTS_DIR)
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

BASE = "https://docs.myscheme.in/"
CATEGORIES = [
    ("Accounts API",      "https://docs.myscheme.in/category/accounts-versioned-api"),
    ("Transactions API",  "https://docs.myscheme.in/category/transactions-versioned-api"),
    ("Search API",        "https://docs.myscheme.in/category/search-versioned-api"),
    ("Schemes API",       "https://docs.myscheme.in/category/schemes-versioned-api"),
    ("Forms API",         "https://docs.myscheme.in/category/forms-versioned-api"),
    ("RAG Service API",   "https://docs.myscheme.in/category/rag-service-versioned-api"),
]

NOT_FOUND_SIGNS = ["404", "page not found", "category empty", "no docs found", "this page could not be found"]
METHOD_TAGS = ["GET", "POST", "PUT", "DELETE", "PATCH"]

report = {
    "target": BASE,
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/docs_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
    except Exception:
        pass
    return path

def looks_404(body):
    low = body.lower()
    return any(s in low for s in NOT_FOUND_SIGNS)

import re

def detect_docs_signals(body, page):
    """Return dict of evidence signals indicating the category page rendered content."""
    # HTTP method tag (for leaf API ref pages)
    tag_hit = False
    for m in METHOD_TAGS:
        for token in [f" {m} ", f"\n{m} ", f"{m}\n", f"{m} /", f"{m}/"]:
            if token in body:
                tag_hit = True; break
        if tag_hit: break
    # Code blocks (for leaf pages with snippets)
    code_count = 0
    try:
        code_count = page.locator("pre, code").count()
    except Exception:
        pass
    # Docusaurus card containers (for category index pages)
    card_count = 0
    try:
        card_count = page.locator("a.card, article.col").count()
    except Exception:
        pass
    # 'N items' summary pattern shown under each sub-category card
    items_matches = re.findall(r"(\d+)\s+items?", body)
    # Sidebar menu items
    menu_count = 0
    try:
        menu_count = page.locator(".menu__link").count()
    except Exception:
        pass
    return {
        "method_tag": tag_hit,
        "code_blocks": code_count,
        "card_count": card_count,
        "items_counts": items_matches,
        "menu_links": menu_count,
    }

def check_category(page, name, url):
    t0 = time.perf_counter()
    status_code = None
    final_url = url
    body = ""
    err = None
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if resp is not None:
            status_code = resp.status
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        time.sleep(1.5)
        final_url = page.url
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ms = (time.perf_counter() - t0) * 1000

    base = {
        "name": name, "url": url, "final_url": final_url,
        "http_status": status_code, "duration_ms": round(ms, 1),
        "body_excerpt": body[:240].replace("\n", " | "),
    }
    tag = name.lower().replace(" ", "_")
    if err:
        base.update(verdict="DOWN", detail=err, artifact=snap(page, tag + "_err"))
        return base
    if status_code is not None and status_code >= 400:
        base.update(verdict="DOWN", detail=f"HTTP {status_code}",
                    artifact=snap(page, tag + f"_http{status_code}"))
        return base
    if looks_404(body):
        base.update(verdict="DOWN", detail="Body matches 404/empty-category signature",
                    artifact=snap(page, tag + "_404body"))
        return base

    sig = detect_docs_signals(body, page)

    # Render is healthy if either:
    #  - method/code signals present (leaf-page evidence), OR
    #  - card-based category index renders with sub-categories that report item counts
    leaf_ok = sig["method_tag"] or sig["code_blocks"] > 0
    category_ok = sig["card_count"] >= 1 and (len(sig["items_counts"]) >= 1 or sig["menu_links"] >= 3)

    if leaf_ok or category_ok:
        bits = []
        if sig["method_tag"]: bits.append("HTTP method tag visible")
        if sig["code_blocks"]: bits.append(f"{sig['code_blocks']} code/pre blocks")
        if sig["card_count"]:  bits.append(f"{sig['card_count']} card containers")
        if sig["items_counts"]: bits.append(f"sub-categories report items={sig['items_counts']}")
        if sig["menu_links"]:  bits.append(f"{sig['menu_links']} menu links")
        base.update(verdict="UP", detail="; ".join(bits), signals=sig, artifact=None)
    else:
        base.update(verdict="DEGRADED",
                    detail="Page loaded but no card listings / method tag / code block detected",
                    signals=sig,
                    artifact=snap(page, tag + "_thin"))
    return base

def run():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # ---------- STEP 1 ----------
        t0 = time.perf_counter()
        s1 = {"name": "Landing page", "url": BASE}
        try:
            resp = page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                pass
            time.sleep(1)
            status = resp.status if resp else None
            body = page.evaluate("() => (document.body && document.body.innerText) || ''")
            ms = (time.perf_counter() - t0) * 1000

            # Sidebar / nav presence: Docusaurus & similar typically expose nav/sidebar elements
            nav_count = 0
            try:
                nav_count = page.locator("nav, [role='navigation'], .menu, .theme-doc-sidebar-container, aside").count()
            except Exception:
                pass

            base = {
                "url": BASE, "final_url": page.url,
                "http_status": status, "duration_ms": round(ms, 1),
                "body_excerpt": body[:240].replace("\n", " | "),
                "nav_containers": nav_count,
            }
            if status is not None and status >= 400:
                base.update(verdict="DOWN", detail=f"HTTP {status}", artifact=snap(page, "landing_http_err"))
            elif looks_404(body):
                base.update(verdict="DOWN", detail="Landing body matches 404 signature", artifact=snap(page, "landing_404"))
            elif nav_count == 0 and not body.strip():
                base.update(verdict="DOWN", detail="Empty page + no nav containers", artifact=snap(page, "landing_empty"))
            else:
                base.update(verdict="UP", detail=f"HTTP {status}, {nav_count} nav containers, body present")
            s1.update(base)
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s1.update(verdict="DOWN", duration_ms=round(ms,1), detail=f"{type(e).__name__}: {e}",
                      artifact=snap(page, "landing_exc"))
        report["steps"].append(s1)

        if s1.get("verdict") != "UP":
            report["overall"] = "DOWN (Docs portal unreachable)"
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            ctx.close(); b.close()
            print(json.dumps(report, indent=2))
            return

        # ---------- STEP 2 ----------
        for name, url in CATEGORIES:
            report["steps"].append(check_category(page, name, url))

        verdicts = [s["verdict"] for s in report["steps"]]
        if all(v == "UP" for v in verdicts):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in verdicts):
            report["overall"] = "DEGRADED (one or more categories DOWN)"
        else:
            report["overall"] = "DEGRADED"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close(); b.close()
        print(json.dumps(report, indent=2))

def main():
    run()


if __name__ == "__main__":
    main()

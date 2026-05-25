"""End-to-end interactive validation of the eligibility rules engine
at https://rules.myscheme.in/.

STEP 1: Click 'Check Eligibility' on the first scheme row -> verify routing
STEP 2: Select 'Yes' for each question that renders; loop until no new questions
STEP 3: Submit, wait up to 10s, observe terminal output screen
"""
from health_check.paths import ARTIFACTS_DIR
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ART_DIR = str(ARTIFACTS_DIR)
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

BASE = "https://rules.myscheme.gov.in/"
CHECK_BTN_XPATH = "/html/body/div/div/div/div[2]/table/tbody/tr[1]/td[2]/div/div[2]/div/button"
EXPECTED_PREFIX = "https://rules.myscheme.gov.in/check-eligibility/"

MAX_FORM_ITERATIONS = 50      # safety cap for dynamic loop
PER_STEP_SETTLE_SEC = 3       # wait this long after each Yes for engine to recalc

report = {
    "target": BASE,
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/rules_{tag}.png"
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        pass
    return path

def get_form_state(page):
    return page.evaluate(r"""
      () => {
        // Group radios by name; capture the active label text per group
        const radios = Array.from(document.querySelectorAll('input[type=radio]'));
        const groups = {};
        radios.forEach(r => {
          if (!groups[r.name]) groups[r.name] = {name: r.name, options: [], any_checked: false, question: ''};
          const lbl = (r.closest('label')?.innerText || r.parentElement?.innerText || '').trim();
          groups[r.name].options.push({value: r.value, label: lbl, checked: r.checked});
          if (r.checked) groups[r.name].any_checked = true;
          // Walk upward to find the nearest question text
          if (!groups[r.name].question) {
            let cur = r.parentElement; let depth = 0;
            while (cur && depth < 6) {
              const sibs = Array.from(cur.parentElement?.children || []);
              for (const s of sibs) {
                const t = (s.innerText || '').trim();
                if (t && !/^(yes|no)\b/i.test(t) && t.length < 400) {
                  groups[r.name].question = t.slice(0, 200);
                  break;
                }
              }
              if (groups[r.name].question) break;
              cur = cur.parentElement; depth++;
            }
          }
        });
        const selects = Array.from(document.querySelectorAll('select')).map(s => ({
          name: s.name, value: s.value, options: Array.from(s.options).map(o => o.text)
        }));
        const text_inputs = Array.from(document.querySelectorAll('input:not([type=radio]):not([type=checkbox]):not([type=submit]):not([type=reset]):not([type=hidden])')).map(i => ({
          name: i.name, type: i.type, value: i.value
        }));
        const buttons = Array.from(document.querySelectorAll('button')).map(b => ({
          text: (b.innerText || '').trim(), type: b.type, disabled: b.disabled
        }));
        return {radio_groups: Object.values(groups), selects, text_inputs, buttons};
      }
    """)

def click_first_yes_in_unanswered_group(page, state):
    """Click 'Yes' for the first radio group that has no selection yet.
    Returns the group name clicked, or None if everything already answered."""
    for grp in state["radio_groups"]:
        if grp["any_checked"]:
            continue
        # Prefer value=='Yes'; fall back to any option whose label starts with yes/affirmative.
        affirmative_keywords = ["yes", "y", "true", "haan"]
        target = None
        for opt in grp["options"]:
            if (opt["value"] or "").strip().lower() in affirmative_keywords:
                target = opt; break
        if target is None:
            for opt in grp["options"]:
                lbl = (opt["label"] or "").strip().lower()
                if any(lbl.startswith(k) for k in affirmative_keywords):
                    target = opt; break
        if target is None:
            # Last resort: pick the first option (most schemes' first option is the affirmative)
            target = grp["options"][0] if grp["options"] else None
        if target is None:
            continue
        # Click via JS on the matching input
        clicked = page.evaluate(r"""
          ([name, value]) => {
            const r = document.querySelector(`input[type=radio][name="${name}"][value="${value}"]`);
            if (!r) return false;
            r.click();
            // Also dispatch change event to nudge framework state
            r.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
          }
        """, [grp["name"], target["value"]])
        if clicked:
            return {"group": grp["name"], "question": grp["question"], "value": target["value"]}
    return None

def run():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # ---------- STEP 1 ----------
        s1 = {"name": "Locate Check Eligibility", "url": BASE}
        t0 = time.perf_counter()
        try:
            page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PWTimeout:
                pass
            time.sleep(1)

            # Wait for at least one Check Eligibility button to render
            try:
                page.locator("button:has-text('Check Eligibility')").first.wait_for(
                    state="attached", timeout=20_000)
            except PWTimeout:
                raise RuntimeError("Check Eligibility button never rendered on landing")
            # Prefer the user-supplied xpath; fall back to first text match
            btn = page.locator(f"xpath={CHECK_BTN_XPATH}").first
            try:
                btn.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                btn = page.locator("button:has-text('Check Eligibility')").first
                btn.scroll_into_view_if_needed(timeout=3000)

            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                    btn.click()
            except PWTimeout:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                pass
            time.sleep(1.5)
            final_url = page.url
            ms = (time.perf_counter() - t0) * 1000

            if final_url.startswith(EXPECTED_PREFIX) and final_url != EXPECTED_PREFIX:
                s1.update(verdict="UP", duration_ms=round(ms,1), final_url=final_url,
                          detail=f"Click routed to {final_url}")
            else:
                s1.update(verdict="DOWN", duration_ms=round(ms,1), final_url=final_url,
                          detail=f"Expected URL starting with {EXPECTED_PREFIX} but got {final_url}",
                          artifact=snap(page, "step1_wrong_url"))
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s1.update(verdict="DOWN", duration_ms=round(ms,1),
                      detail=f"{type(e).__name__}: {e}", artifact=snap(page, "step1_exc"))
        report["steps"].append(s1)

        if s1["verdict"] != "UP":
            report["overall"] = "DOWN (Engine Entry Failure)"
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            ctx.close(); b.close()
            print(json.dumps(report, indent=2)); return

        # ---------- STEP 2 ----------
        s2 = {"name": "Form traversal (Select All Yes)"}
        t0 = time.perf_counter()
        steps_taken = []
        try:
            iteration = 0
            stagnation_streak = 0
            last_signature = None
            while iteration < MAX_FORM_ITERATIONS:
                state = get_form_state(page)
                # Compute a signature of unanswered groups; used to detect stagnation
                unanswered = [g["name"] for g in state["radio_groups"] if not g["any_checked"]]
                signature = (tuple(unanswered), len(state["radio_groups"]))

                clicked = click_first_yes_in_unanswered_group(page, state)
                if clicked is None:
                    # No unanswered group. Wait once more to be sure the engine isn't
                    # about to render a new question.
                    time.sleep(PER_STEP_SETTLE_SEC)
                    after = get_form_state(page)
                    if len(after["radio_groups"]) > len(state["radio_groups"]):
                        # New group rendered; loop again
                        iteration += 1
                        continue
                    break
                steps_taken.append(clicked)
                iteration += 1
                time.sleep(PER_STEP_SETTLE_SEC)

                # Detect pathological stagnation (same unanswered set after a click)
                state_after = get_form_state(page)
                unanswered_after = [g["name"] for g in state_after["radio_groups"] if not g["any_checked"]]
                if (tuple(unanswered_after), len(state_after["radio_groups"])) == signature:
                    stagnation_streak += 1
                    if stagnation_streak >= 3:
                        raise RuntimeError(f"Form did not progress after 3 consecutive Yes clicks; last group: {clicked}")
                else:
                    stagnation_streak = 0

            ms = (time.perf_counter() - t0) * 1000
            if iteration >= MAX_FORM_ITERATIONS:
                s2.update(verdict="DOWN", duration_ms=round(ms,1),
                          detail=f"Hit MAX_FORM_ITERATIONS ({MAX_FORM_ITERATIONS}); form may loop indefinitely",
                          steps_taken=len(steps_taken), steps=steps_taken[:20],
                          artifact=snap(page, "step2_loop"))
            else:
                s2.update(verdict="UP", duration_ms=round(ms,1),
                          steps_taken=len(steps_taken), steps=steps_taken,
                          detail=f"Answered {len(steps_taken)} question(s); form stabilized.")
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s2.update(verdict="DOWN", duration_ms=round(ms,1),
                      detail=f"{type(e).__name__}: {e}",
                      steps_taken=len(steps_taken), steps=steps_taken[:20],
                      artifact=snap(page, "step2_exc"))
        report["steps"].append(s2)

        if s2["verdict"] != "UP":
            report["overall"] = "DOWN (Form Traversal Failure)"
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            ctx.close(); b.close()
            print(json.dumps(report, indent=2)); return

        # ---------- STEP 3 ----------
        s3 = {"name": "Submit & observe result"}
        t0 = time.perf_counter()
        try:
            submit = page.locator("button[type='submit']:has-text('Submit')").first
            if submit.count() == 0:
                submit = page.locator("button:has-text('Submit')").first
            if submit.count() == 0:
                raise RuntimeError("Submit button not found")
            url_before = page.url
            try:
                submit.click()
            except Exception as e:
                raise RuntimeError(f"Submit click failed: {e}")

            # Wait up to 10s for transition / result render
            deadline = time.time() + 10
            result_body = ""
            url_after = url_before
            while time.time() < deadline:
                time.sleep(0.5)
                try:
                    url_after = page.url
                    result_body = page.evaluate("() => (document.body && document.body.innerText) || ''")
                except Exception:
                    continue
                # Heuristics: URL changed, OR body contains result-like signals
                if url_after != url_before:
                    break
                low = result_body.lower()
                if any(s in low for s in ["eligible", "not eligible", "result", "scheme(s)", "qualif", "recommend", "summary"]):
                    break

            ms = (time.perf_counter() - t0) * 1000
            low = result_body.lower()
            crash_signals = {
                "We're Sorry! / Something went wrong modal": "something went wrong",
                "Internal Server Error":                     "internal server error",
                "HTTP 500":                                  "error 500",
                "Uncaught exception":                        "uncaught",
                "Stack trace":                               "stack trace",
            }
            crash_label = next((label for label, kw in crash_signals.items() if kw in low), None)
            crashed = crash_label is not None
            generic_404 = "page not found" in low
            art = snap(page, "step3_result")

            if crashed or generic_404:
                detail = ("Engine processing failure: " +
                          (crash_label if crashed else "Page not found"))
                s3.update(verdict="DOWN", duration_ms=round(ms,1),
                          final_url=url_after,
                          detail=detail,
                          body_excerpt=result_body[:600].replace("\n", " | "),
                          artifact=art)
            elif not result_body.strip():
                s3.update(verdict="DEGRADED", duration_ms=round(ms,1),
                          final_url=url_after,
                          detail="Empty body after submit (no result rendered)",
                          artifact=art)
            else:
                s3.update(verdict="UP", duration_ms=round(ms,1),
                          final_url=url_after,
                          detail="Terminal output rendered without crash",
                          body_excerpt=result_body[:600].replace("\n", " | "),
                          artifact=art)
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s3.update(verdict="DOWN", duration_ms=round(ms,1),
                      detail=f"{type(e).__name__}: {e}",
                      artifact=snap(page, "step3_exc"))
        report["steps"].append(s3)

        verdicts = [s["verdict"] for s in report["steps"]]
        if all(v == "UP" for v in verdicts):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in verdicts):
            report["overall"] = "DOWN"
        else:
            report["overall"] = "DEGRADED"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close(); b.close()
        print(json.dumps(report, indent=2))

def main():
    run()


if __name__ == "__main__":
    main()

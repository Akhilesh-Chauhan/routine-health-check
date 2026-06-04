"""The chatbot-widget verdict primitive: one decision function parameterised by
each surface's outcome policy (dev/umang hard-fail; prod myscheme never-fails)."""
from health_check.checks._primitives import chatbot_widget_result
from health_check.reporting.status import Verdict


def test_reply_uses_on_reply():
    r = chatbot_widget_result(cards_ready=True, got_reply=True,
                              frame_url="https://aistore.myscheme.in/x?isEmbed=true",
                              on_blank=Verdict.DOWN, on_no_reply=Verdict.DOWN, on_reply=Verdict.UP)
    assert r["verdict"] == Verdict.UP


def test_blank_uses_on_blank_dev():
    r = chatbot_widget_result(cards_ready=False, got_reply=False,
                              frame_url="chrome-error://chromewebdata/",
                              on_blank=Verdict.DOWN, on_no_reply=Verdict.DOWN, on_reply=Verdict.UP)
    assert r["verdict"] == Verdict.DOWN


def test_blank_uses_on_blank_prod_never_fails():
    r = chatbot_widget_result(cards_ready=False, got_reply=False,
                              frame_url="chrome-error://chromewebdata/",
                              on_blank=Verdict.KNOWN_ISSUE, on_no_reply=Verdict.KNOWN_ISSUE, on_reply=Verdict.PASS)
    assert r["verdict"] == Verdict.KNOWN_ISSUE


def test_cards_no_reply_uses_on_no_reply():
    r = chatbot_widget_result(cards_ready=True, got_reply=False,
                              frame_url="https://aistore.myscheme.in/x?isEmbed=true",
                              on_blank=Verdict.DOWN, on_no_reply=Verdict.KNOWN_ISSUE, on_reply=Verdict.PASS)
    assert r["verdict"] == Verdict.KNOWN_ISSUE


def test_detail_present_for_each_outcome():
    for kw in (dict(cards_ready=False, got_reply=False),
               dict(cards_ready=True, got_reply=False),
               dict(cards_ready=True, got_reply=True)):
        r = chatbot_widget_result(frame_url="x", on_blank=Verdict.DOWN,
                                  on_no_reply=Verdict.DOWN, on_reply=Verdict.UP, **kw)
        assert r["detail"] and isinstance(r["detail"], str)

from health_check.browser.driver import PageHandle, BrowserDriver


class FakePage:
    def __init__(self): self._url = "https://start/"
    def goto(self, url, timeout_ms=30000): self._url = url; return 200
    @property
    def url(self): return self._url
    def text(self): return "Dashboard and users"
    def count(self, selector): return 3
    def is_visible(self, selector): return True
    def click_nav(self, selector, timeout_ms=25000): return None
    def wait_idle(self, timeout_ms=15000): return None
    def wait_for(self, selector, timeout_ms=10000): return True
    def inner_text(self, selector): return "MyScheme"
    def evaluate(self, script): return {"ok": True}
    def screenshot(self, path, full_page=False): return path


def test_fake_page_satisfies_protocol():
    p = FakePage()
    assert isinstance(p, PageHandle)
    assert p.goto("https://x/") == 200
    assert p.url == "https://x/"
    assert "Dashboard" in p.text()
    assert p.count("div.card") == 3
    assert p.is_visible("a.btn") is True
    assert p.click_nav("a.btn") is None
    assert p.wait_idle() is None
    assert p.wait_for("div.card") is True
    assert p.inner_text("div.card") == "MyScheme"
    assert p.evaluate("() => 1") == {"ok": True}
    assert p.screenshot("/tmp/x.png") == "/tmp/x.png"

from health_check.browser.driver import PageHandle, BrowserDriver


class FakePage:
    def __init__(self): self._url = "https://start/"
    def goto(self, url, timeout_ms=30000): self._url = url; return 200
    @property
    def url(self): return self._url
    def text(self): return "Dashboard and users"
    def screenshot(self, path, full_page=False): return path


def test_fake_page_satisfies_protocol():
    p = FakePage()
    assert isinstance(p, PageHandle)
    assert p.goto("https://x/") == 200
    assert p.url == "https://x/"
    assert "Dashboard" in p.text()
    assert p.screenshot("/tmp/x.png") == "/tmp/x.png"

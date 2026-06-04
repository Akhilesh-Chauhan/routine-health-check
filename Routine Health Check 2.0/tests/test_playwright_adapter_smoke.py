import os, pytest
from health_check.browser.driver import PageHandle


@pytest.mark.skipif(not os.environ.get("HC_LIVE_BROWSER"),
                    reason="set HC_LIVE_BROWSER=1 to run the live adapter smoke test")
def test_adapter_page_is_a_pagehandle():
    from health_check.browser.playwright_driver import PlaywrightDriver
    d = PlaywrightDriver()
    page = d.open("prod")
    try:
        assert isinstance(page, PageHandle)
        assert page.goto("https://www.myscheme.gov.in/") in (200, None)
    finally:
        d.close()

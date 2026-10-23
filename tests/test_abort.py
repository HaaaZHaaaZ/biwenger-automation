import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from biwenger_daily import api, Ctx

def test_abort_on_retry_after_gt60(monkeypatch):
    ctx = Ctx()
    ctx.abort = False
    import biwenger_daily as bd
    bd._CTX = ctx
    # mock session
    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "120"}
        text = ""
    class FakeSession:
        def request(self, *a, **k):
            return FakeResp()
    bd._SESSION = FakeSession()
    try:
        api("POST", "https://example.com/x", body={"a":1})
    except Exception:
        pass
    assert ctx.abort is True
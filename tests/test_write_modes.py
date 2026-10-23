import os, sys, unittest, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import biwenger_daily as bd

REAL_API = bd.api

WRITES = [
    ("sell_player", lambda ctx: bd.sell_player(ctx, 1, 100)),
    ("answer_offer", lambda ctx: bd.answer_offer(ctx, 1, "accepted")),
    ("create_purchase_offer", lambda ctx: bd.create_purchase_offer(ctx, 1, 100)),
    ("retract_offer", lambda ctx: bd.retract_offer(ctx, 1)),
    ("set_lineup", lambda ctx: bd.set_lineup(ctx, [1], "4-4-2")),
]

class TestWriteModes(unittest.TestCase):
    def _ctx(self, **kw):
        ctx = bd.Ctx()
        ctx.token = "t"; ctx.league_id = 1; ctx.user_id = 2
        ctx.dry_run = False
        for k,v in kw.items():
            setattr(ctx, k, v)
        return ctx

    def test_abort_no_api(self):
        for name, fn in WRITES:
            ctx = self._ctx(abort=True)
            called = {"n":0}
            def fake_api(*a, **k):
                called["n"] += 1; return None
            bd.api = fake_api
            fn(ctx)
            self.assertEqual(called["n"], 0, name)
            bd.api = REAL_API

    def test_read_only_no_api(self):
        for name, fn in WRITES:
            ctx = self._ctx(read_only=True)
            called = {"n":0}
            def fake_api(*a, **k):
                called["n"] += 1; return None
            bd.api = fake_api
            fn(ctx)
            self.assertEqual(called["n"], 0, name)
            bd.api = REAL_API

    def test_dry_run_no_api(self):
        for name, fn in WRITES:
            ctx = self._ctx(dry_run=True)
            called = {"n":0}
            def fake_api(*a, **k):
                called["n"] += 1; return None
            bd.api = fake_api
            fn(ctx)
            self.assertEqual(called["n"], 0, name)
            bd.api = REAL_API

    def test_timeout_post_creates_state(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        os.remove(path)
        bd.UNKNOWN_STATE_PATH = path
        ctx = self._ctx()
        bd._CTX = ctx
        bd.api = REAL_API
        class FakeSession:
            def request(self, *a, **k):
                raise __import__("requests").RequestException("timeout")
        bd._SESSION = FakeSession()
        bd.save_unknown_state = lambda op: open(path, "w").write("[]")
        try:
            bd.sell_player(ctx, 1, 100)
        except Exception:
            pass
        self.assertTrue(os.path.exists(path))
        os.remove(path)

if __name__ == "__main__":
    unittest.main()
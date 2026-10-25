import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import biwenger_daily as bd

class TestGuarded(unittest.TestCase):
    def test_sell_player_aborted(self):
        ctx = bd.Ctx()
        ctx.abort = True
        ctx.token = "t"
        ctx.league_id = 1
        ctx.user_id = 2
        called = {"n": 0}
        def fake_api(*a, **k):
            called["n"] += 1
            return None
        bd.api = fake_api
        res = bd.sell_player(ctx, 1, 100)
        self.assertEqual(called["n"], 0)
        self.assertEqual(res[1], "aborted")
        # Restore api
        from biwenger.api import api as _real_api
        bd.api = _real_api

if __name__ == "__main__":
    unittest.main()
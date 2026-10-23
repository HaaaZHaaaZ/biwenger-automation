import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import biwenger_daily as bd

def test_sell_player_aborted(monkeypatch):
    ctx = bd.Ctx()
    ctx.abort = True
    ctx.token = "t"
    ctx.league_id = 1
    ctx.user_id = 2
    called = {"n": 0}
    def fake_api(*a, **k):
        called["n"] += 1
        return None
    monkeypatch.setattr(bd, "api", fake_api)
    res = bd.sell_player(ctx, 1, 100)
    assert called["n"] == 0
    assert res[1] == "aborted"
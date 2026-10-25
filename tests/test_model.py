"""Tests for biwenger.model — Ctx dataclass + exceptions + globals."""
import pytest


def test_ctx_defaults():
    from biwenger.model import Ctx
    c = Ctx()
    assert c.user_id == 0
    assert c.league_id == 0
    assert c.balance == 0
    assert c.write_count == 0
    assert c.actions == []
    assert c.squad_ids == []
    assert c.catalog == {}
    assert c.offers == []
    assert c.free_market == []
    assert c.pool == {}
    assert c.opt_ids == []
    assert c.opt_type is None
    assert c.opt_detail is None
    assert c.my_sale_ids == set()
    assert c.pending_ids == set()
    assert c.committed == 0
    assert c.captain_id is None
    assert c.striker_id is None
    assert c.abort is False
    assert c.rate_limited is False
    assert c.dry_run is True  # inherits DRY_RUN from config


def test_ctx_act():
    from biwenger.model import Ctx
    c = Ctx()
    c.act("sell_sub", player_id=1, player_name="Lunin", price=500000)
    assert len(c.actions) == 1
    assert c.actions[0]["type"] == "sell_sub"
    assert c.actions[0]["player_id"] == 1


def test_ctx_can_write():
    from biwenger.model import Ctx
    c = Ctx()
    assert c.can_write() is True
    c.write_count = 100
    assert c.can_write() is False


def test_ctx_recompute_calls_scoring():
    from biwenger.model import Ctx
    c = Ctx()
    c.squad_ids = [1]
    c.catalog = {"1": {"name": "Test", "position": 1, "status": "ok",
                        "teamID": 1, "points": 90, "playedHome": 5, "playedAway": 5,
                        "fitness": [1, 1, 1, 1, 1], "price": 1000000}}
    c.diff_map = {1: 40}
    c.games_map = {1: {"rival": "Real", "cond": "casa"}}
    # Should not raise and should populate pool/opt_fields
    c.recompute()
    assert isinstance(c.pool, dict)
    assert isinstance(c.opt_ids, list)


def test_ctx_cushion():
    from biwenger.model import Ctx
    c = Ctx()
    c.squad_ids = [1]
    c.catalog = {"1": {"price": 1000000}}
    # cushion = max(1M * 0.08, 500000) = max(80000, 500000) = 500000
    assert c.cushion() == 500000


def test_exceptions():
    from biwenger.model import RateLimited, AuthError, OldVersion
    assert issubclass(RateLimited, Exception)
    assert issubclass(AuthError, Exception)
    assert issubclass(OldVersion, Exception)


def test_globals_resettable():
    from biwenger.model import _CTX, _SESSION, REQ
    assert _CTX is None
    assert _SESSION is None
    assert isinstance(REQ, dict) and "count" in REQ
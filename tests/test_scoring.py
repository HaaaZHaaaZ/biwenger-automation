"""Tests for biwenger.scoring — pure scoring functions."""
from biwenger.scoring import score_player, estimate_p_start, home_flag, build_smart_lineup


def test_score_injured_returns_zero():
    cp = {"status": "injured", "points": 100, "playedHome": 10, "playedAway": 10,
          "fitness": [1, 1, 0, 1, 1]}
    s, why, ps = score_player(cp, 50)
    assert s == 0.0
    assert "no puntúa" in why


def test_score_ok_returns_positive():
    cp = {"status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
          "fitness": [1, 1, 1, 1, 1]}
    s, why, ps = score_player(cp, 50)
    assert s > 0
    assert isinstance(why, str)
    assert isinstance(ps, float)


def test_score_return_type():
    cp = {"status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
          "fitness": [1] * 5}
    result = score_player(cp, 50)
    assert len(result) == 3  # (score, why, p_start)


def test_home_bonus():
    cp = {"status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
          "fitness": [1] * 5}
    s_home, _, _ = score_player(cp, 50, is_home=True)
    s_away, _, _ = score_player(cp, 50, is_home=False)
    assert s_home > s_away  # ~5% diferencia


def test_no_home_no_modification():
    cp = {"status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
          "fitness": [1] * 5}
    s, _, _ = score_player(cp, 50, is_home=None)
    # Without is_home, score should not get 1.05/0.95 multiplier
    s_home, _, _ = score_player(cp, 50, is_home=True)
    assert s < s_home


def test_estimate_p_start_full_fitness():
    cp = {"fitness": [1, 1, 1, 1, 1]}
    ps = estimate_p_start(cp, games=10)
    assert ps == 1.0


def test_estimate_p_start_no_fitness():
    cp = {}
    ps = estimate_p_start(cp, games=0)
    assert ps == 0.6  # no games = 0.6
    ps2 = estimate_p_start(cp, games=5)
    assert ps2 == 0.7


def test_home_flag():
    assert home_flag({1: {"cond": "casa"}}, 1) is True
    assert home_flag({1: {"cond": "fuera"}}, 1) is False
    assert home_flag({}, 1) is None
    assert home_flag({2: {"cond": "casa"}}, 1) is None


def test_build_smart_lineup_requires_gk():
    catalog = {
        "1": {"name": "GK1", "position": 1, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "2": {"name": "DEF1", "position": 2, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "3": {"name": "DEF2", "position": 2, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "4": {"name": "DEF3", "position": 2, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "5": {"name": "DEF4", "position": 2, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "6": {"name": "MID1", "position": 3, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "7": {"name": "MID2", "position": 3, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "8": {"name": "MID3", "position": 3, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "9": {"name": "MID4", "position": 3, "teamID": 1,
              "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
              "fitness": [1] * 5, "price": 500000},
        "10": {"name": "FWD1", "position": 4, "teamID": 1,
               "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
               "fitness": [1] * 5, "price": 500000},
        "11": {"name": "FWD2", "position": 4, "teamID": 1,
               "status": "ok", "points": 90, "playedHome": 5, "playedAway": 5,
               "fitness": [1] * 5, "price": 500000},
    }
    diff_map, games_map = {1: 40}, {1: {"rival": "R", "cond": "casa"}}
    ids, formation, detail, pool = build_smart_lineup(
        list(catalog.keys()), catalog, diff_map, games_map)
    assert ids is not None
    assert formation == "4-4-2"  # only formation that fits with 1 GK + 4 DEF + 4 MID + 2 FWD
    assert detail["total"] > 0
    assert len(pool) == 11
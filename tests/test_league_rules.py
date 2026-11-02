"""Reglas reales de la liga y errores de estrategia corregidos en v14.2.0."""
import time

import pytest

from biwenger import stages
from biwenger.model import Ctx
from biwenger.scoring import (build_smart_lineup, parse_round_fixtures, player_value, score_player)


def _p(pos, pts=30, name=None, team=1, alt=None, status="ok", price=1_000_000, fit=None):
    return {"name": name or f"p{pos}", "position": pos, "teamID": team, "status": status,
            "points": pts, "playedHome": 5, "playedAway": 5, "price": price,
            "fitness": fit or [3, 3, 3, 3, 3], "altPositions": alt}


def _squad():
    cat = {"1": _p(1, 20, "GK"), "16": _p(1, 5, "GK2")}
    for i in range(2, 7):
        cat[str(i)] = _p(2, 30 + i, f"D{i}")
    for i in range(7, 12):
        cat[str(i)] = _p(3, 30 + i, f"M{i}")
    cat["17"] = _p(3, 12, "M17")
    for i in range(12, 16):
        cat[str(i)] = _p(4, 20 + i, f"F{i}")
    return cat


def _ctx(cat, squad=None, multipos=False):
    c = Ctx()
    c.user_id, c.balance = 2, 50_000_000
    c.catalog = cat
    c.squad_ids = [int(k) for k in cat] if squad is None else squad
    c.lineup_info = {"type": "3-5-2"}
    c.multipos = multipos
    c.team_max = 16
    c.recompute()
    c.lineup_ids = list(c.opt_ids)
    return c


def test_ajustes_de_liga_desactivan_capitan_y_ariete(monkeypatch):
    monkeypatch.setattr("biwenger.model.CAPTAIN_KEY", "captain")
    monkeypatch.setattr("biwenger.model.STRIKER_KEY", "striker")
    c = Ctx()
    c.apply_league_settings({"scoreID": 3, "settings": {
        "lineupCaptain": False, "lineupStriker": False, "lineupMultiPos": True,
        "teamMaxSize": 18, "marketMaxUserSales": 5, "bidsOverMV": False}})
    assert (c.captain_enabled, c.striker_enabled) == (False, False)
    assert c.multipos and c.team_max == 18 and c.max_user_sales == 5 and c.bids_over_mv is False


def test_sin_capitan_no_se_reenvia_una_alineacion_identica(monkeypatch):
    calls = []
    monkeypatch.setattr(stages, "set_lineup", lambda *a: calls.append(a) or (True, {}))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    c = _ctx(_squad())
    c.captain_enabled = c.striker_enabled = False
    c.lineup_info = {"type": c.opt_type}
    stages.stage_lineup(c)
    assert calls == []


def test_multiposicion_aprovecha_al_delantero_como_medio():
    cat = {"1": _p(1)}
    for i in range(2, 6):
        cat[str(i)] = _p(2, 30)
    for i in range(6, 8):
        cat[str(i)] = _p(3, 5)
    cat["13"] = _p(3, 5)                       # medios malos: sin multiposición, 4-3-3 obligado
    for i in range(8, 13):
        cat[str(i)] = _p(4, 60, alt=[3])       # 5 delanteros muy buenos con alternativa MID
    squad = [int(k) for k in cat]
    sin = build_smart_lineup(squad, cat, {}, {}, multipos=False)
    con = build_smart_lineup(squad, cat, {}, {}, multipos=True)
    assert con[2]["total"] > sin[2]["total"]
    assert len(con[2]["fwd"]) + len(con[2]["mid"]) + len(con[2]["def"]) == 10
    assert any(e["slot"] == 3 and e["position"] == 4 for e in con[2]["mid"])
    # orden de la API: GK + huecos DEF + huecos MID + huecos FWD
    expected = [con[2]["gk"][0]["id"]] + [e["id"] for k in ("def", "mid", "fwd") for e in con[2][k]]
    assert con[0] == expected


def test_multiposicion_rechazada_reintenta_en_posicion_real(monkeypatch):
    cat = {"1": _p(1)}
    for i in range(2, 6):
        cat[str(i)] = _p(2, 30)
    for i in range(6, 8):
        cat[str(i)] = _p(3, 5)
    cat["13"] = _p(3, 5)
    for i in range(8, 13):
        cat[str(i)] = _p(4, 60, alt=[3])
    responses = [(False, "http_400: invalid position"), (True, {})]
    sent = []
    monkeypatch.setattr(stages, "set_lineup", lambda ctx, ids, t, c, s: sent.append((ids, t)) or responses.pop(0))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    c = _ctx(cat, multipos=True)
    c.lineup_ids = []
    c.captain_enabled = c.striker_enabled = False
    stages.stage_lineup(c)
    assert len(sent) == 2 and c.multipos is False
    assert all(e["slot"] == e["position"] for k in ("def", "mid", "fwd") for e in c.opt_detail[k])


def test_jornada_en_curso_apunta_a_la_siguiente_y_cubre_todos_los_equipos():
    def game(i):
        return {"date": 1794000000 + i, "home": {"id": 100 + i, "name": f"H{i}", "difficulty": {"rating": 30}},
                "away": {"id": 200 + i, "name": f"A{i}", "difficulty": {"rating": 70}}}
    data = {"status": "active", "games": [{"home": {"id": 999}, "away": {"id": 998}, "date": 1}],
            "next": {"name": "J12", "games": [game(i) for i in range(10)]}}
    diff, games, name, kick, complete = parse_round_fixtures(data)
    assert name == "J12" and complete and len(games) == 20 and 999 not in games
    assert diff[100] == 30 and games[200]["cond"] == "fuera" and 100 in kick


def test_equipo_sin_partido_en_jornada_completa_no_puntua():
    cat = _squad()
    s, why, _ = score_player(cat["2"], 50, None, None, has_match=False)
    assert s == 0 and "sin partido" in why


def test_duda_baja_la_jornada_pero_no_el_valor_de_fondo():
    ok, duda = _p(3, 60), _p(3, 60, status="doubt")
    assert score_player(duda, 50)[0] < score_player(ok, 50)[0]
    assert player_value(duda) == player_value(ok)


def test_suplente_en_duda_con_buen_valor_no_se_vende(monkeypatch):
    sells = []
    monkeypatch.setattr(stages, "sell_player", lambda *a: sells.append(a) or (True, "ok", 1))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    cat = _squad()
    bench = 11
    cat[str(bench)]["status"] = "doubt"
    c = _ctx(cat)
    assert bench not in c.opt_ids, "la duda lo saca del once"
    assert c.pool[bench]["score"] < c.pool[bench]["value"]
    c.free_market = []
    stages.stage_sell_bench(c)
    assert all(a[1] != bench for a in sells)


def test_plantilla_llena_con_fichaje_pone_a_la_venta_al_peor_suplente(monkeypatch):
    sells = []
    monkeypatch.setattr(stages, "sell_player",
                        lambda ctx, pid, price: sells.append(pid) or (True, "ok", price))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    cat = _squad()
    cat["99"] = _p(4, 90, "Crack", price=2_000_000)
    c = _ctx(cat, squad=[int(k) for k in cat if k != "99"])
    assert len(c.squad_ids) >= 16
    c.free_market = [{"id": 99, "name": "Crack", "position": 4, "price": 2_000_000,
                      "status": "ok", "score": 8.0, "p_start": 1.0, "team_id": 1}]
    stages.stage_buy(c)
    assert len(sells) == 1 and sells[0] not in c.opt_ids
    assert c.pool[sells[0]]["position"] != 1, "conserva el portero de reserva"


def test_recien_comprado_no_se_intenta_vender(monkeypatch):
    c = _ctx(_squad())
    c.owner_info = {5: {"date": time.time() - 100}, 6: {"date": time.time() - 90_000}}
    assert stages._held_too_recently(c, 5) is True
    assert stages._held_too_recently(c, 6) is False


def test_acepta_la_mejor_oferta_no_la_primera(monkeypatch):
    answers = []
    monkeypatch.setattr(stages, "answer_offer", lambda ctx, oid, st: answers.append((oid, st)) or (True, "ok"))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    c = _ctx(_squad())
    pid = next(i for i in c.squad_ids if i not in c.opt_ids and c.pool[i]["position"] != 1)
    offer = lambda oid, amt: {"id": oid, "status": "waiting", "amount": amt, "type": "purchase",
                              "to": {"id": 2}, "from": {"id": 7}, "requestedPlayers": [pid]}
    c.offers = [offer(1, 1_300_000), offer(2, 2_000_000)]
    stages.stage_received_offers(c)
    assert answers[0] == (2, "accepted")


def test_saldo_negativo_acepta_oferta_por_suplente(monkeypatch):
    answers = []
    monkeypatch.setattr(stages, "answer_offer", lambda ctx, oid, st: answers.append((oid, st)) or (True, "ok"))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    c = _ctx(_squad())
    c.balance = -100
    pid = next(i for i in c.squad_ids if i not in c.opt_ids and c.pool[i]["position"] != 1)
    c.offers = [{"id": 5, "status": "waiting", "amount": 950_000, "type": "purchase",
                 "to": {"id": 2}, "from": {"id": 7}, "requestedPlayers": [pid]}]
    stages.stage_received_offers(c)
    assert answers == [(5, "accepted")]


def test_se_reserva_una_escritura_para_la_alineacion(monkeypatch):
    monkeypatch.setattr("biwenger.model.MAX_WRITES", 3)
    c = Ctx()
    c.write_count = 2
    assert c.can_write() is True and c.can_write(stages.LINEUP_RESERVE) is False


def test_resolver_estado_incierto_reanuda_escrituras(bw, make_ctx):
    import json
    import os
    with open(bw.UNKNOWN_STATE_PATH, "w") as f:
        json.dump([{"type": "unknown", "method": "POST"}], f)
    assert bw.resolve_unknown_state(make_ctx()) == 1
    assert not os.path.exists(bw.UNKNOWN_STATE_PATH)


def test_no_se_vende_el_unico_portero_de_reserva(monkeypatch):
    sells = []
    monkeypatch.setattr(stages, "sell_player", lambda *a: sells.append(a[1]) or (True, "ok", 1))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    cat = _squad()
    c = _ctx(cat)
    reserve = next(i for i in c.squad_ids if i not in c.opt_ids and c.pool[i]["position"] == 1)
    assert c.pool[reserve]["value"] < 2.0
    c.free_market = []
    stages.stage_sell_bench(c)
    assert reserve not in sells


def test_mismo_once_en_otro_orden_no_gasta_escritura(monkeypatch):
    calls = []
    monkeypatch.setattr(stages, "set_lineup", lambda *a: calls.append(a) or (True, {}))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    c = _ctx(_squad())
    c.captain_enabled = c.striker_enabled = False
    c.lineup_info = {"type": c.opt_type}
    nd = int(c.opt_type.split("-")[0])
    ids = list(c.opt_ids)
    ids[1:1 + nd] = reversed(ids[1:1 + nd])
    c.lineup_ids = ids
    stages.stage_lineup(c)
    assert calls == []


def test_oferta_por_buen_suplente_en_duda_no_se_acepta_al_90(monkeypatch):
    answers = []
    monkeypatch.setattr(stages, "answer_offer", lambda ctx, oid, st: answers.append((oid, st)) or (True, "ok"))
    monkeypatch.setattr(stages, "log_action", lambda *a, **k: None)
    cat = _squad()
    cat["11"]["status"] = "doubt"
    c = _ctx(cat)
    c.my_sale_ids = {11}
    c.offers = [{"id": 8, "status": "waiting", "amount": 950_000, "type": "purchase",
                 "to": {"id": 2}, "from": None, "requestedPlayers": [11]}]
    stages.stage_received_offers(c)
    assert answers == [(8, "rejected")]

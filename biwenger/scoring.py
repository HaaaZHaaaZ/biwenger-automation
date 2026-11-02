"""Biwenger scoring — funciones puras de puntuación y alineación.

Sin dependencias de API ni de `biwenger_daily`. Todas las funciones
toman datos plano (dicts) y devuelven resultados plano.
"""
import biwenger.config

# Peso de cada uno de los últimos 5 partidos: el último cuenta más.
_RECENCY = [1, 1.2, 1.5, 2, 3]


# ── Helpers numéricos ────────────────────────────────────────────────────────

def _numeric(f):
    return isinstance(f, (int, float)) and not isinstance(f, bool)


def estimate_p_start(cp, games):
    """Probabilidad aproximada de jugar (0.2–1.0), ponderando lo reciente.

    En `fitness`, un número = jugó, None = no jugó estando disponible y un texto
    (injured/doubt/sanctioned) = baja. Las bajas no cuentan contra su titularidad:
    quien vuelve de lesión ya está penalizado por el estado.
    """
    last = (cp.get("fitness") or [])[-5:]
    if not last:
        return 0.6 if games == 0 else 0.7
    played = available = 0.0
    for f, w in zip(last, _RECENCY[-len(last):]):
        if isinstance(f, str):
            continue
        available += w
        played += w if _numeric(f) else 0
    if available == 0:
        return 0.6
    return round(0.2 + 0.8 * played / available, 3)


def home_flag(games_map, team_id):
    cond = (games_map.get(team_id) or {}).get("cond")
    return True if cond == "casa" else False if cond == "fuera" else None


# ── score_player ─────────────────────────────────────────────────────────────

def _base_points(cp, games):
    """Puntos esperados por partido jugado, en su posición real y sin contexto de jornada."""
    pos = cp.get("position", 0)
    prior = biwenger.config.POS_PRIOR.get(pos, 3.0)
    if games == 0:
        last = cp.get("pointsLastSeason") or 0
        return (last / 38.0) if last else prior * 0.5
    season_avg = (cp.get("points") or 0) / games
    fit = [f for f in (cp.get("fitness") or []) if _numeric(f)][-5:]
    weights = _RECENCY[-len(fit):] if fit else []
    recent = (sum(f * w for f, w in zip(fit, weights)) / sum(weights)) if fit else season_avg
    w = biwenger.config.RECENT_WEIGHT
    k = biwenger.config.PRIOR_GAMES
    blended = (1 - w) * season_avg + w * recent
    return (games * blended + k * prior) / (games + k)


def player_value(cp):
    """Valor de fondo del jugador, sin estado ni rival de esta jornada.
    Para decidir ventas: una duda puntual no debe malvender a un buen jugador."""
    if not cp:
        return 0.0
    games = (cp.get("playedHome") or 0) + (cp.get("playedAway") or 0)
    p = estimate_p_start(cp, games)
    return round(max(_base_points(cp, games), 0.0) * p ** biwenger.config.P_START_POWER, 3)


def _home_factor(cp, is_home, games):
    """Reparto casa/fuera real del jugador (regularizado); ±5% si hay poca muestra."""
    default = 1.05 if is_home else 0.95
    side_games = cp.get("playedHome" if is_home else "playedAway") or 0
    if side_games < 3 or not games:
        return default
    avg = (cp.get("points") or 0) / games
    if avg <= 0:
        return default
    side_points = cp.get("pointsHome" if is_home else "pointsAway")
    if side_points is None:
        return default
    side_avg = side_points / side_games
    k = biwenger.config.PRIOR_GAMES
    factor = (side_games * (side_avg / avg) + k * default) / (side_games + k)
    # Con pocos partidos por lado la división es ruidosa: nunca más de ±15%.
    factor = min(max(factor, 0.85), 1.15)
    # Mantiene la ventaja de jugar en casa frente a jugar fuera en el mismo jugador.
    return max(factor, 1.0) if is_home else min(factor, 1.0)


def score_player(cp, diff_rating, p_start=None, is_home=None, has_match=True):
    """
    Puntos esperados para la PRÓXIMA jornada, en el sistema de la liga.
    score = base × local × rival × estado × p_start^1.5.
    Devuelve (score, explicación, p_start).
    """
    if not cp:
        return 0.0, "sin datos en catálogo", 0.0
    status = (cp.get("status") or "ok").lower()
    mult = biwenger.config.STATUS_MULT.get(status, 0.7)
    games = (cp.get("playedHome") or 0) + (cp.get("playedAway") or 0)
    if p_start is None:
        p_start = estimate_p_start(cp, games)
    if mult == 0.0:
        return 0.0, f"status={status} (no puntúa)", p_start
    if not has_match:
        return 0.0, f"{status} sin partido esta jornada", p_start

    base = max(_base_points(cp, games), 0.0)
    pos = cp.get("position", 0)
    # rating 0-100: MENOR = rival más flojo = mejor para nosotros
    easy = 0.5 if diff_rating is None else (100.0 - float(diff_rating)) / 100.0
    sens = biwenger.config.FIXTURE_SENSITIVITY.get(pos, 0.15)
    fixture = 1.0 + sens * (easy - 0.5) * 2.0

    score = base * fixture * mult * p_start ** biwenger.config.P_START_POWER
    loc = ""
    if is_home is not None:
        score *= _home_factor(cp, is_home, games)
        loc = f" local={'casa' if is_home else 'fuera'}"
    why = (f"{status} base={base:.2f} rival_facilidad={easy:.2f} "
           f"p_start={p_start:.2f}{loc}")
    return round(score, 3), why, p_start


# ── get_fixture_info ─────────────────────────────────────────────────────────

def parse_ts(v):
    """Interpreta una fecha (epoch s/ms o ISO) como datetime local sin zona."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v > 1e11:
                v = v / 1000.0
            from datetime import datetime
            return datetime.fromtimestamp(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return parse_ts(int(s))
            from datetime import datetime
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
    except (ValueError, OSError, OverflowError):
        return None
    return None


def get_fixture_info(lineup_players):
    """
    Dificultad y condición del PRÓXIMO partido por equipo.
    Devuelve (diff_map, games_map, round_name, kickoffs).
    """
    from datetime import datetime, timedelta
    diff_map, games_map, kickoffs = {}, {}, {}
    round_name = None
    seen = set()
    now = datetime.now()
    for p in lineup_players:
        team = (p or {}).get("team")
        if not team:
            continue
        tid = team.get("id")
        if tid in seen:
            continue
        seen.add(tid)
        games = [g for g in (team.get("nextGames") or []) if isinstance(g, dict)]
        if not games:
            continue
        dated = [(parse_ts(g.get("date")), g) for g in games]
        if all(d is not None for d, _ in dated):
            dated.sort(key=lambda x: x[0])
            upcoming = [x for x in dated if x[0] >= now - timedelta(hours=3)]
            dated = upcoming or dated
        gdate, g = dated[0]
        if round_name is None:
            round_name = (g.get("round") or {}).get("name")
        h, a = g.get("home") or {}, g.get("away") or {}
        hid, aid = h.get("id"), a.get("id")
        dh = (h.get("difficulty") or {}).get("rating")
        da = (a.get("difficulty") or {}).get("rating")
        if hid is not None and dh is not None and hid not in diff_map:
            diff_map[hid] = dh
            games_map[hid] = {"rival": a.get("name") or str(aid), "cond": "casa", "round": round_name}
        if aid is not None and da is not None and aid not in diff_map:
            diff_map[aid] = da
            games_map[aid] = {"rival": h.get("name") or str(hid), "cond": "fuera", "round": round_name}
        if gdate:
            for t in (hid, aid):
                if t is not None:
                    kickoffs.setdefault(t, gdate)
    return diff_map, games_map, round_name, kickoffs


def parse_round_fixtures(round_data):
    """Rival, condición y hora de los 20 equipos para la jornada que vamos a alinear.

    Con la jornada en curso la alineación ya no cambia (lineupRoundChanges=0), así que
    el objetivo es la siguiente. Antes solo se conocían los equipos de los titulares,
    y además se mezclaban partidos de dos jornadas si la actual no había terminado.
    Devuelve (diff_map, games_map, round_name, kickoffs, completa).
    """
    data = round_data or {}
    target = data if data.get("status") == "pending" else (data.get("next") or {})
    games = [g for g in (target.get("games") or []) if isinstance(g, dict)]
    diff_map, games_map, kickoffs = {}, {}, {}
    name = target.get("name")
    for g in games:
        h, a = g.get("home") or {}, g.get("away") or {}
        date = parse_ts(g.get("date"))
        for team, rival, cond in ((h, a, "casa"), (a, h, "fuera")):
            tid = team.get("id")
            if tid is None:
                continue
            rating = (team.get("difficulty") or {}).get("rating")
            if rating is not None:
                diff_map[tid] = rating
            games_map[tid] = {"rival": rival.get("name") or str(rival.get("id")),
                              "cond": cond, "round": name}
            if date:
                kickoffs[tid] = date
    # Con partidos aplazados no se puede afirmar que un equipo ausente no juegue.
    return diff_map, games_map, name, kickoffs, len(games) >= 10


# ── build_smart_lineup ───────────────────────────────────────────────────────

def _slot_score(e, slot):
    """Puntos esperados de un jugador alineado en `slot` (2=DEF, 3=MID, 4=FWD)."""
    if slot == e["position"]:
        return e["score"]
    cfg = biwenger.config
    delta = cfg.ALT_POS_DELTA.get((e["position"], slot), cfg.ALT_POS_DELTA_DEFAULT)
    return max(e["score"] + delta * e["p_start"], 0.0) if e["score"] > 0 else 0.0


def _assign_slots(players, nd, nm, nf, multipos):
    """Reparto óptimo en DEF/MID/FWD. Plantilla pequeña: basta programación dinámica."""
    best = {(0, 0, 0): (0.0, ())}
    for e in players:
        slots = [e["position"]]
        if multipos:
            slots += [s for s in e["altPositions"] if s in (2, 3, 4) and s != e["position"]]
        next_best = dict(best)      # opción: el jugador se queda fuera
        for (d, m, f), (total, chosen) in best.items():
            for slot in slots:
                state = (d + (slot == 2), m + (slot == 3), f + (slot == 4))
                if state[0] > nd or state[1] > nm or state[2] > nf:
                    continue
                cand = total + _slot_score(e, slot)
                if state not in next_best or cand > next_best[state][0]:
                    next_best[state] = (cand, chosen + ((e, slot),))
        best = next_best
    return best.get((nd, nm, nf))


def build_smart_lineup(squad_ids, catalog, diff_map, games_map, multipos=False, all_fixtures=False):
    """
    Puntúa a TODO el squad y elige la mejor formación.
    Devuelve (ids, formación, detalle, pool). ids = [GK] + DEF + MID + FWD por hueco.
    multipos: usa altPositions si la liga lo permite (lineupMultiPos).
    all_fixtures: games_map cubre la jornada entera; quien no aparece no juega y vale 0.
    """
    pool = {}
    for pid in squad_ids:
        cp = catalog.get(str(pid))
        if not cp:
            continue
        tid = cp.get("teamID")
        has_match = (not all_fixtures) or tid in games_map
        s, why, ps = score_player(cp, diff_map.get(tid), None, home_flag(games_map, tid), has_match)
        pool[pid] = {
            "id": pid, "name": cp.get("name", f"id={pid}"),
            "position": cp.get("position", 0),
            "altPositions": cp.get("altPositions") or [],
            "team_id": tid, "score": s, "why": why,
            "status": cp.get("status"), "p_start": ps,
            "price": cp.get("price", 0) or 0,
            "value": player_value(cp), "has_match": has_match,
        }
    gks = sorted((e for e in pool.values() if e["position"] == 1),
                 key=lambda x: x["score"], reverse=True)
    if not gks:
        return None, None, None, pool
    outfield = sorted((e for e in pool.values() if e["position"] in (2, 3, 4)),
                      key=lambda x: (-x["score"], x["id"]))

    best = None
    for name, nd, nm, nf in biwenger.config.FORMATIONS:
        result = _assign_slots(outfield, nd, nm, nf, multipos)
        if result is None:
            continue
        lines = {2: [], 3: [], 4: []}
        for e, slot in result[1]:
            lines[slot].append({**e, "slot": slot, "slot_score": round(_slot_score(e, slot), 3)})
        for line in lines.values():
            line.sort(key=lambda x: x["slot_score"], reverse=True)
        gk = {**gks[0], "slot": 1, "slot_score": gks[0]["score"]}
        total = gk["slot_score"] + sum(e["slot_score"] for line in lines.values() for e in line)
        cand = {
            "formation": name,
            "ids": [gk["id"]] + [e["id"] for s in (2, 3, 4) for e in lines[s]],
            "total": round(total, 3),
            "gk": [gk], "def": lines[2], "mid": lines[3], "fwd": lines[4],
        }
        if best is None or cand["total"] > best["total"]:
            best = cand
    if best is None:
        return None, None, None, pool
    return best["ids"], best["formation"], best, pool


# ── choose_captain_and_striker ──────────────────────────────────────────────

def choose_captain_and_striker(detail):
    """Capitán = mayor puntuación esperada con titularidad casi segura. Ariete = mejor delantero."""
    if not detail:
        return None, None
    starters = detail["gk"] + detail["def"] + detail["mid"] + detail["fwd"]
    ok = [e for e in starters if (e.get("status") or "ok").lower() == "ok" and e["score"] > 0]
    captain_max_val = getattr(biwenger.config, "CAPTAIN_MAX_VALUE", 0)
    if captain_max_val > 0:
        ok = [e for e in ok if e.get("price", 0) <= captain_max_val]
    safe = [e for e in ok if e["p_start"] >= 0.85] or ok
    cap = max(safe, key=lambda e: e["score"]) if safe else None
    fwds = sorted([e for e in safe if e.get("position") == 4], key=lambda e: e["score"], reverse=True)
    striker = fwds[0] if fwds else None
    if striker and cap and striker["id"] == cap["id"] and len(fwds) > 1 \
            and fwds[1]["score"] >= 0.9 * striker["score"]:
        striker = fwds[1]   # diversifica el riesgo si hay alternativa casi igual de buena
    return (cap["id"] if cap else None), (striker["id"] if striker else None)


# ── build_free_market (requiere ctx catalog/diff_map/games_map) ─────────────

def build_free_market(ctx, free_sales):
    """Jugadores del mercado libre con posición, estado y score ya calculados."""
    result = []
    for s in free_sales:
        pid = (s.get("player") or {}).get("id")
        cp = ctx.catalog.get(str(pid)) if pid else None
        if not cp:
            continue
        tid = cp.get("teamID")
        has_match = (not getattr(ctx, "fixtures_complete", False)) or tid in ctx.games_map
        sc, why, ps = score_player(cp, ctx.diff_map.get(tid), None, home_flag(ctx.games_map, tid), has_match)
        result.append({
            "id": pid, "name": cp.get("name", f"id={pid}"),
            "position": cp.get("position", 0),
            "price": s.get("price") or cp.get("price") or 0,
            "status": (cp.get("status") or "ok").lower(),
            "score": sc, "why": why, "p_start": ps, "team_id": tid,
        })
    return result


# ── offer_player_ids ─────────────────────────────────────────────────────────

def offer_player_ids(o):
    ids = []
    for rp in (o.get("requestedPlayers") or []):
        if isinstance(rp, dict) and rp.get("id"):
            ids.append(rp["id"])
        elif isinstance(rp, int):
            ids.append(rp)
    return ids


# ── lineup_is_complete ───────────────────────────────────────────────────────

def lineup_is_complete(ctx):
    """Salvaguardia: 11 jugadores con 1 GK, ≥3 DEF, ≥3 MID, ≥1 FWD (por hueco, no por posición real)."""
    if len(ctx.opt_ids) < 11:
        return False, f"solo {len(ctx.opt_ids)} jugadores"
    need = {1: 1, 2: 3, 3: 3, 4: 1}
    detail = ctx.opt_detail or {}
    if all(k in detail for k in ("gk", "def", "mid", "fwd")):
        count = {1: len(detail["gk"]), 2: len(detail["def"]), 3: len(detail["mid"]), 4: len(detail["fwd"])}
    else:
        count = {}
        for pid in ctx.opt_ids:
            e = ctx.pool.get(pid)
            if e:
                count[e["position"]] = count.get(e["position"], 0) + 1
    missing = [f"{biwenger.config.POS_NAMES[p]}={count.get(p, 0)}" for p, n in need.items() if count.get(p, 0) < n]
    return (not missing), ", ".join(missing)

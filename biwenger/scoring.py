"""Biwenger scoring — funciones puras de puntuación y alineación.

Sin dependencias de API ni de `biwenger_daily`. Todas las funciones
toman datos plano (dicts) y devuelven resultados plano.
"""
import random
from datetime import datetime, timedelta

from biwenger.config import STATUS_MULT, FORMATIONS, POS_NAMES, CAPTAIN_MAX_VALUE, MIN_P_START_BUY


# ── Helpers numéricos ────────────────────────────────────────────────────────

def _numeric(f):
    return isinstance(f, (int, float)) and not isinstance(f, bool)


def estimate_p_start(cp, games):
    """Probabilidad aproximada de ser titular (0.2–1.0)."""
    last = (cp.get("fitness") or [])[-5:]
    if not last:
        return 0.6 if games == 0 else 0.7
    played = sum(1 for f in last if _numeric(f))
    return round(0.2 + 0.8 * played / len(last), 3)


def home_flag(games_map, team_id):
    cond = (games_map.get(team_id) or {}).get("cond")
    return True if cond == "casa" else False if cond == "fuera" else None


# ── score_player ─────────────────────────────────────────────────────────────

def score_player(cp, diff_rating, p_start=None, is_home=None):
    """
    Puntúa a un jugador (~0-6) para el PRÓXIMO partido.
    Devuelve (score, explicación, p_start).
    """
    if not cp:
        return 0.0, "sin datos en catálogo", 0.0
    status = (cp.get("status") or "ok").lower()
    mult = STATUS_MULT.get(status, 0.7)
    games = (cp.get("playedHome") or 0) + (cp.get("playedAway") or 0)
    if p_start is None:
        p_start = estimate_p_start(cp, games)
    if mult == 0.0:
        return 0.0, f"status={status} (no puntúa)", p_start

    pts = cp.get("points") or 0
    season_avg = pts / games if games else 0.0
    if games == 0:
        last = cp.get("pointsLastSeason") or 0
        season_avg = (last / 30.0 * 0.8) if last else 0.0

    fit = [f for f in (cp.get("fitness") or []) if _numeric(f)][-5:]
    fit_avg = sum(fit) / len(fit) if fit else 0.0

    # rating 0-100: MENOR = rival más flojo = mejor para nosotros
    easy = 0.5 if diff_rating is None else (100.0 - float(diff_rating)) / 100.0

    base = 0.35 * season_avg + 0.35 * fit_avg + 3.0 * 0.30 * easy
    score = base * mult * p_start
    loc = ""
    if is_home is not None:
        score *= 1.05 if is_home else 0.95
        loc = f" local={'casa' if is_home else 'fuera'}"
    why = (f"{status} pts/partido={season_avg:.2f} forma={fit_avg:.2f} "
           f"rival_facilidad={easy:.2f} p_start={p_start:.2f}{loc}")
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
            return datetime.fromtimestamp(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return parse_ts(int(s))
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


# ── build_smart_lineup ───────────────────────────────────────────────────────

def build_smart_lineup(squad_ids, catalog, diff_map, games_map):
    """
    Puntúa a TODO el squad y elige la mejor formación.
    Devuelve (ids, formación, detalle, pool). ids = [GK] + DEF + MID + FWD.
    """
    pool = {}
    for pid in squad_ids:
        cp = catalog.get(str(pid))
        if not cp:
            continue
        tid = cp.get("teamID")
        s, why, ps = score_player(cp, diff_map.get(tid), None, home_flag(games_map, tid))
        pool[pid] = {
            "id": pid, "name": cp.get("name", f"id={pid}"),
            "position": cp.get("position", 0),
            "altPositions": cp.get("altPositions") or [],
            "team_id": tid, "score": s, "why": why,
            "status": cp.get("status"), "p_start": ps,
            "price": cp.get("price", 0) or 0,
        }
    by_pos = {1: [], 2: [], 3: [], 4: []}
    for e in pool.values():
        if e["position"] in by_pos:
            by_pos[e["position"]].append(e)
    for k in by_pos:
        by_pos[k].sort(key=lambda x: x["score"], reverse=True)
    if not by_pos[1]:
        return None, None, None, pool

    best = None
    for name, nd, nm, nf in FORMATIONS:
        if len(by_pos[2]) < nd or len(by_pos[3]) < nm or len(by_pos[4]) < nf:
            continue
        gk = by_pos[1][0]
        dfs, mds, fws = by_pos[2][:nd], by_pos[3][:nm], by_pos[4][:nf]
        total = gk["score"] + sum(e["score"] for e in dfs + mds + fws)
        cand = {
            "formation": name,
            "ids": [gk["id"]] + [e["id"] for e in dfs + mds + fws],
            "total": round(total, 3),
            "gk": [gk], "def": dfs, "mid": mds, "fwd": fws,
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
    if CAPTAIN_MAX_VALUE > 0:
        ok = [e for e in ok if e.get("price", 0) <= CAPTAIN_MAX_VALUE]
    safe = [e for e in ok if e["p_start"] >= 0.85] or ok
    cap = max(safe, key=lambda e: e["score"]) if safe else None
    fwds = sorted([e for e in safe if e["position"] == 4], key=lambda e: e["score"], reverse=True)
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
        sc, why, ps = score_player(cp, ctx.diff_map.get(tid), None, home_flag(ctx.games_map, tid))
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
    """Salvaguardia: 11 jugadores con 1 GK, ≥3 DEF, ≥3 MID, ≥1 FWD."""
    if len(ctx.opt_ids) < 11:
        return False, f"solo {len(ctx.opt_ids)} jugadores"
    need = {1: 1, 2: 3, 3: 3, 4: 1}
    count = {}
    for pid in ctx.opt_ids:
        e = ctx.pool.get(pid)
        if e:
            count[e["position"]] = count.get(e["position"], 0) + 1
    missing = [f"{POS_NAMES[p]}={count.get(p, 0)}" for p, n in need.items() if count.get(p, 0) < n]
    return (not missing), ", ".join(missing)
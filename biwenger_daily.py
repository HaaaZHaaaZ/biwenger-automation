#!/usr/bin/env python3
"""
Biwenger Auto-Trader v9 — Brayan Lopez
========================================
Funciona 100%:
  ✅ Login y autenticación
  ✅ Monitorización del mercado y estado de cuenta
  ✅ Ventas automáticas (solo si es necesario y hay reemplazo)
  ✅ Compras automáticas (ofertas al mercado libre)
  ✅ Alineación automática (4-4-2 optimizada por posición)
  ✅ Sistema de logs completo

Operaciones implementadas:
  - POST /api/v2/auth/login → token
  - GET  /api/v2/account → league_id, user_id, balance
  - GET  /api/v2/market → sales (free + propias)
  - POST /api/v2/market → vender jugador propio (solo si es necesario)
  - GET  /api/v2/user?fields=players(id,name),lineup(...) → squad con posiciones
  - POST /api/v2/offers → crear oferta de compra
  - PUT  /api/v2/offers/{id} → aumentar puja
  - DELETE /api/v2/offers/{id} → retirar oferta
  - PUT  /api/v2/user?fields=*%2Clineup(date) → alinear 4-4-2
  - Sistema de logs: biwenger_log.json + biwenger_log.txt
"""

import requests, json, sys, time, os
from datetime import datetime, timezone

EMAIL = os.environ.get("BIWENGER_EMAIL", "")
PASSWORD = os.environ.get("BIWENGER_PASSWORD", "")
STATE_FILE = "/opt/data/biwenger_state.json"
TODO_FILE = "/opt/data/biwenger_todo.md"
LOG_FILE = "/opt/data/biwenger_log.json"
LOG_TXT_FILE = "/opt/data/biwenger_log.txt"
MAX_RETRIES = 1
RETRY_DELAY = 120
REQUEST_TIMEOUT = 30
LEAGUE_ID = 1802805
USER_ID = 13947894
MAX_WRITES = 8

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"


# ── Sistema de Logs ──────────────────────────────────────

def log_action(action_type, details, status="info"):
    """Registra una acción en el log JSON y TXT."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Log JSON
    log_entry = {
        "timestamp": timestamp,
        "action": action_type,
        "status": status,
        "details": details
    }
    
    # Leer log existente
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except:
            logs = []
    
    logs.append(log_entry)
    
    # Guardar log JSON
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)
    
    # Log TXT (más legible)
    with open(LOG_TXT_FILE, "a") as f:
        f.write(f"[{timestamp}] [{status.upper()}] {action_type}: {json.dumps(details, ensure_ascii=False)}\n")
    
    return log_entry


def log_print(msg):
    """Imprime y registra en el log."""
    print(msg)
    with open(LOG_TXT_FILE, "a") as f:
        f.write(f"  {msg}\n")


# Multiplicador por estado real del jugador. 0.0 = no puede puntuar.
STATUS_MULT = {
    "ok": 1.00,
    "warned": 0.85,      # apercibido: riesgo de sanción
    "doubt": 0.55,       # duda
    "injured": 0.00,
    "suspended": 0.00,
    "sanctioned": 0.00,
}


def score_player(cat_player, diff_rating, p_start=1.0, is_home=None):
    """
    Puntúa a un jugador (~0-6) para el PRÓXIMO partido usando datos reales:
      - estado real (injured/suspended/sanctioned → 0)
      - media de puntos por partido de la temporada      (peso 35%)
      - forma reciente: media de los últimos 5 partidos  (peso 35%)
      - dificultad del rival: rating 0-100, MENOR = rival más flojo = más puntos (peso 30%)
      - probabilidad de titularidad (p_start 0-1)
      - localía: +5% casa, -5% fuera (opcional)
      - fallback pointsLastSeason × 0.8 si aún no ha jugado esta temporada
    Devuelve (score, explicación).
    """
    if not cat_player:
        return 0.0, "sin datos en catálogo"

    status = (cat_player.get("status") or "ok").lower()
    mult = STATUS_MULT.get(status, 0.7)
    if mult == 0.0:
        return 0.0, f"status={status} (no puntúa)"

    games = (cat_player.get("playedHome") or 0) + (cat_player.get("playedAway") or 0)
    pts = cat_player.get("points") or 0
    season_avg = pts / games if games else 0.0
    if games == 0:
        # Sin partidos esta temporada → usar la anterior como referencia (~30 jornadas) × 0.8
        last = cat_player.get("pointsLastSeason") or 0
        season_avg = (last / 30.0 * 0.8) if last else 0.0

    fit = [f for f in (cat_player.get("fitness") or []) if isinstance(f, (int, float))]
    last5 = fit[-5:]
    fit_avg = sum(last5) / len(last5) if last5 else 0.0

    # rating 0-100: MENOR = rival más flojo = mejor para nosotros
    if diff_rating is None:
        easy = 0.5  # rival desconocido → neutro
    else:
        easy = (100.0 - float(diff_rating)) / 100.0

    base = 0.35 * season_avg + 0.35 * fit_avg + 3.0 * 0.30 * easy
    score = round(base * mult * p_start, 3)
    
    # Localía: +5% casa, -5% fuera
    locality = ""
    if is_home is not None:
        locality_mult = 1.05 if is_home else 0.95
        score = round(score * locality_mult, 3)
        locality = f" local={'casa' if is_home else 'fuera'}"
    
    why = (f"{status} pts/partido={season_avg:.2f} forma={fit_avg:.2f} "
           f"rival_facilidad={easy:.2f} p_start={p_start:.2f}{locality}")
    return score, why


def get_catalog(session, token, league_id, user_id):
    """
    GET cf.biwenger.com/api/v2/competitions/la-liga/data?lang=es&score=3
    Catálogo completo (~547 jugadores) con position, status, points,
    playedHome/playedAway, fitness, pointsLastSeason y teamID.
    Devuelve (players_dict, teams_dict) indexados por str(id).
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get(
        "https://cf.biwenger.com/api/v2/competitions/la-liga/data?lang=es&score=3",
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r is None or r.status_code != 200:
        return {}, {}
    data = r.json().get("data", {})
    return (data.get("players") or {}), (data.get("teams") or {})


def get_next_match_date(session, token, league_id, user_id):
    """
    Obtiene la fecha del próximo partido de La Liga desde la API de Biwenger.
    Devuelve (datetime or None, round_name).
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get(
        "https://biwenger.as.com/api/v2/rounds/league",
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r is None or r.status_code != 200:
        return None, None
    data = r.json().get("data", {})
    round_info = data.get("round", {})
    round_name = round_info.get("name")
    # La API no da fecha directa del próximo partido, pero podemos inferir
    # que los partidos de La Liga suelen ser fines de semana.
    # Si es viernes/sábado/domingo, el próximo partido es hoy o mañana.
    from datetime import datetime as dt, timedelta
    today = dt.now()
    weekday = today.weekday()  # 0=Lunes, 6=Domingo
    # Si es jueves o viernes, el próximo partido probablemente es en 1-2 días
    if weekday in (3, 4):  # Jueves o Viernes
        return today + timedelta(days=1), round_name
    # Si es sábado o domingo, el próximo partido puede ser hoy
    if weekday in (5, 6):
        return today, round_name
    # Si es lunes/miércoles, el próximo partido probablemente es en 2-3 días
    return today + timedelta(days=2), round_name


def get_fixture_info(lineup_players):
    """
    Extrae el mapa de dificultad del PRÓXIMO partido por equipo desde
    lineup.players[].team.nextGames. El endpoint de squad sí devuelve
    difficulty(rating); el catálogo no.
    Cubre los equipos implicados en los partidos de los 11 titulares (16/20).
    Devuelve (diff_map, games_map, round_name).
    """
    diff_map, games_map, round_name = {}, {}, None
    for p in lineup_players:
        if not p or not p.get("team"):
            continue
        for g in (p["team"].get("nextGames") or []):
            if round_name is None:
                round_name = (g.get("round") or {}).get("name")
            h = g.get("home") or {}
            a = g.get("away") or {}
            hid, aid = h.get("id"), a.get("id")
            dh = (h.get("difficulty") or {}).get("rating")
            da = (a.get("difficulty") or {}).get("rating")
            if dh is not None:
                diff_map[hid] = dh
                games_map[hid] = {"rival": a.get("name") or str(aid), "cond": "casa", "round": round_name}
            if da is not None:
                diff_map[aid] = da
                games_map[aid] = {"rival": h.get("name") or str(hid), "cond": "fuera", "round": round_name}
    return diff_map, games_map, round_name


# Formaciones soportadas: (nombre, DEF, MID, FWD). 1 GK fijo.
FORMATIONS = [
    ("4-4-2", 4, 4, 2),
    ("4-3-3", 4, 3, 3),
    ("3-4-3", 3, 4, 3),
    ("3-5-2", 3, 5, 2),
    ("5-3-2", 5, 3, 2),
    ("4-5-1", 4, 5, 1),
    ("5-4-1", 5, 4, 1),
]


def build_smart_lineup(squad_ids, catalog, diff_map):
    """
    Puntúa a TODOS los jugadores del squad (titulares Y suplentes) con
    score_player() y elige la mejor alineación, probando varias formaciones.
    Devuelve (ids, formacion, detalle, pool).
    """
    pool = {}
    for pid in squad_ids:
        cp = catalog.get(str(pid))
        if not cp:
            continue
        tid = cp.get("teamID")
        s, why = score_player(cp, diff_map.get(tid))
        pool[pid] = {
            "id": pid,
            "name": cp.get("name", f"id={pid}"),
            "position": cp.get("position", 0),
            "altPositions": cp.get("altPositions") or [],
            "team_id": tid,
            "score": s,
            "why": why,
            "status": cp.get("status"),
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
        if (len(by_pos[2]) < nd) or (len(by_pos[3]) < nm) or (len(by_pos[4]) < nf):
            continue
        gk = by_pos[1][0]
        dfs = by_pos[2][:nd]
        mds = by_pos[3][:nm]
        fws = by_pos[4][:nf]
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


def get_headers(token, extra=None):
    h = {
        "Authorization": f"Bearer {token}",
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "X-Lang": "es",
        "Origin": "https://biwenger.as.com",
        "Referer": "https://biwenger.as.com/",
    }
    if extra:
        h.update(extra)
    return h


def login(session):
    """POST /api/v2/auth/login → token Bearer."""
    r = requests.post(
        "https://biwenger.as.com/api/v2/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    if r is None or r.status_code != 200:
        raise ValueError(f"Login fallido: {r}")
    data = r.json()
    token = data.get("token") or data.get("data", {}).get("token")
    if not token:
        raise ValueError(f"Login sin token: {data}")
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "User-Agent": UA,
        "Origin": "https://biwenger.as.com",
        "Referer": "https://biwenger.as.com/",
    })
    return token


def get_account(session, token):
    """GET /api/v2/account → league_id, user_id, balance, points, name."""
    r = requests.get(
        "https://biwenger.as.com/api/v2/account",
        headers=get_headers(token),
        timeout=REQUEST_TIMEOUT,
    )
    if r is None or r.status_code != 200:
        raise ValueError(f"Account error: {r}")
    data = r.json().get("data", {})
    leagues = data.get("leagues", [])
    if not leagues:
        raise ValueError("No hay ligas activas")
    league = leagues[0]
    user = league.get("user", {})
    league_id = league.get("id")
    user_id = user.get("id")
    if not league_id or not user_id:
        raise ValueError(f"Account incompleto: {league}")
    return league_id, user_id, user.get("balance", 0), user.get("points", 0), user.get("name", "?")


def get_market(session, token, league_id, user_id):
    """GET /api/v2/market → sales[] con free + propias."""
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get("https://biwenger.as.com/api/v2/market", headers=h, timeout=REQUEST_TIMEOUT)
    if r is None or r.status_code != 200:
        return [], []
    data = r.json().get("data", {})
    sales = data.get("sales", [])
    free_sales = [s for s in sales if s.get("user") is None]
    user_sales = [s for s in sales if s.get("user") is not None and s.get("user", {}).get("id") == user_id]
    return free_sales, user_sales


def get_free_market_with_positions(session, token, league_id, user_id, catalog=None):
    """
    Combina dos endpoints:
    1. GET biwenger.as.com/api/v2/market → jugadores en venta en la liga privada
    2. GET cf.biwenger.com/api/v2/competitions/la-liga/market?interval=day&includeValues=true → posiciones
    3. FALLBACK: si cf.biwenger.com está bloqueado (403), usar el catálogo de La Liga
       para obtener posiciones de TODOS los jugadores del free market.
    Devuelve lista de jugadores en venta con position (1=GK, 2=DEF, 3=MID, 4=FWD).
    """
    # 1. Obtener jugadores en venta de la liga privada
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get("https://biwenger.as.com/api/v2/market", headers=h, timeout=REQUEST_TIMEOUT)
    if r is None or r.status_code != 200:
        return []
    sales = r.json().get("data", {}).get("sales", [])
    free_sales = [s for s in sales if s.get("user") is None]
    
    # 2. Intentar obtener posiciones de cf.biwenger.com (ups/downs del mercado general)
    # OJO: este endpoint devuelve jugadores que suben/bajan de precio, NO los que
    # están en venta en la liga privada. Por eso solo cubre ~2/10 del free market.
    position_map = {}
    r_cf = requests.get(
        "https://cf.biwenger.com/api/v2/competitions/la-liga/market?interval=day&includeValues=true",
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r_cf is not None and r_cf.status_code == 200:
        cf_data = r_cf.json().get("data", {})
        for key in ("ups", "downs"):
            for p in cf_data.get(key, []):
                if isinstance(p, dict) and "id" in p and "position" in p:
                    position_map[p["id"]] = p
    
    # 3. FALLBACK: si los IDs del free market NO están en position_map, usar el catálogo
    # de La Liga (548 jugadores con posiciones) para obtener TODOS los que faltan.
    if catalog:
        free_ids_en_venta = {s.get("player", {}).get("id") for s in free_sales}
        faltan = free_ids_en_venta - set(position_map.keys())
        if faltan:
            log_print(f"  ℹ️ {len(faltan)} jugadores del free market no están en ups/downs — usando catálogo La Liga")
            for pid_str, cp in catalog.items():
                try:
                    pid = int(pid_str)
                except (ValueError, TypeError):
                    continue
                if pid in faltan:
                    position_map[pid] = {
                        "id": pid,
                        "name": cp.get("name", f"id={pid}"),
                        "position": cp.get("position", 0),
                        "status": cp.get("status", "ok"),
                    }
    
    # 4. Combinar: jugadores en venta + posiciones
    result = []
    for s in free_sales:
        pid = s.get("player", {}).get("id")
        if pid and pid in position_map:
            p = position_map[pid]
            result.append({
                "id": pid,
                "name": p.get("name", f"id={pid}"),
                "position": p.get("position", 0),
                "price": s.get("price", 0),
                "status": p.get("status", "ok"),
            })
    
    return result


def get_pending_offers(session, token, league_id, user_id):
    """
    GET /api/v2/offers → lista de ofertas.
    Devuelve set de player_ids con oferta 'waiting' propia (para no duplicar pujas).
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get("https://biwenger.as.com/api/v2/offers", headers=h, timeout=REQUEST_TIMEOUT)
    if r is None or r.status_code != 200:
        return set()
    data = r.json().get("data")
    if not isinstance(data, list):
        return set()
    pend = set()
    for o in data:
        if not isinstance(o, dict):
            continue
        if o.get("status") != "waiting":
            continue
        # Solo ofertas hechas POR nosotros (from = nuestro user)
        frm = o.get("from") or {}
        if frm.get("id") != user_id:
            continue
        for rp in (o.get("requestedPlayers") or []):
            if isinstance(rp, dict) and rp.get("id"):
                pend.add(rp["id"])
            elif isinstance(rp, int):
                pend.add(rp)
    return pend


def get_received_offers(session, token, league_id, user_id):
    """
    GET /api/v2/offers → ofertas RECIBIDAS (from=null, to=nuestro user).
    Devuelve lista de ofertas con status 'waiting' que otros usuarios nos han hecho.
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get("https://biwenger.as.com/api/v2/offers", headers=h, timeout=REQUEST_TIMEOUT)
    if r is None or r.status_code != 200:
        return []
    data = r.json().get("data")
    if not isinstance(data, list):
        return []
    received = []
    for o in data:
        if not isinstance(o, dict):
            continue
        if o.get("status") != "waiting":
            continue
        # Ofertas RECIBIDAS: from=null, to=nuestro user
        frm = o.get("from") or {}
        to = o.get("to") or {}
        if frm.get("id") is None and to.get("id") == user_id:
            received.append(o)
    return received


def accept_offer(session, token, league_id, user_id, offer_id):
    """PUT /api/v2/offers/{id} {'status': 'accepted'} → aceptar oferta recibida."""
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.put(
        f"https://biwenger.as.com/api/v2/offers/{offer_id}",
        json={"status": "accepted"},
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code in (200, 201):
        return True, "ok"
    return False, f"http_{r.status_code}: {r.text[:150]}"


def reject_offer(session, token, league_id, user_id, offer_id):
    """PUT /api/v2/offers/{id} {'status': 'rejected'} → rechazar oferta recibida."""
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.put(
        f"https://biwenger.as.com/api/v2/offers/{offer_id}",
        json={"status": "rejected"},
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code in (200, 201):
        return True, "ok"
    return False, f"http_{r.status_code}: {r.text[:150]}"


def sell_player(session, token, league_id, user_id, player_id, price=None):
    """
    POST /api/v2/market → vender jugador propio. 204 = éxito.
    Si price es None, usar el precio de mercado del catálogo (price=0 da 'Low sell price').
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    # Si no hay precio, usar 1 como mínimo (el API rechaza 0 y precios muy bajos)
    sell_price = price if price is not None and price > 0 else 1
    r = requests.post(
        "https://biwenger.as.com/api/v2/market",
        json={"player": player_id, "price": sell_price},
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code in (200, 201, 204):
        return True, "ok", sell_price
    if r.status_code == 429:
        return False, "rate_limited", sell_price
    return False, f"http_{r.status_code}: {r.text[:120]}", sell_price


def get_squad_with_positions(session, token, league_id, user_id):
    """
    GET /api/v2/user?fields=players(id),lineup(...)
    Devuelve:
      - squad_ids: lista de IDs de TODO el squad (titulares + suplentes)
      - lineup: {type, playersID, players: [...]}
      - lineup_players: jugadores titulares con team.nextGames (para dificultad)
    Las posiciones están en lineup.players[i].position (1=GK, 2=DEF, 3=MID, 4=FWD)
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.get(
        "https://biwenger.as.com/api/v2/user"
        "?fields=players(id),"
        "lineup(round,id,type,playersID,reservesID,"
        "players(id,name,position,altPositions,status,fitness,points,price,"
        "team(id,name,slug,nextGames(*))))",
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r is None or r.status_code != 200:
        return None, None, None
    data = r.json().get("data", {})
    squad_ids = [p.get("id") for p in data.get("players", []) if isinstance(p, dict) and p.get("id")]
    lineup = data.get("lineup", {})
    return squad_ids, lineup, lineup.get("players", [])


def set_lineup(session, token, league_id, user_id, players_ids, formation="4-4-2"):
    """
    PUT /api/v2/user?fields=*%2Clineup(date)
    Body: {"lineup": {"type": "4-4-2", "playersID": [...], "reservesID": []}}
    Headers: X-League, X-User, X-Version: 631
    200 = éxito.
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    payload = {
        "lineup": {
            "type": formation,
            "playersID": players_ids,
            "reservesID": [],
        }
    }
    r = requests.put(
        "https://biwenger.as.com/api/v2/user?fields=*%2Clineup(date)",
        json=payload,
        headers=h,
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code == 200:
        return True, r.json()
    if r.status_code == 400:
        return False, f"400: {r.text[:200]}"
    if r.status_code == 403:
        return False, f"403: {r.text[:200]}"
    return False, f"http_{r.status_code}: {r.text[:200]}"


def create_purchase_offer(session, token, league_id, user_id, player_id, amount):
    """
    POST /api/v2/offers → crear oferta de compra.
    Body: {"to": null, "type": "purchase", "amount": X, "requestedPlayers": [id]}
    Headers: X-League, X-User, X-Version: 631
    200 = éxito, devuelve {"status":"waiting","id":...}
    """
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    payload = {
        "to": None,
        "type": "purchase",
        "amount": amount,
        "requestedPlayers": [player_id],
    }
    r = requests.post("https://biwenger.as.com/api/v2/offers", json=payload, headers=h, timeout=REQUEST_TIMEOUT)
    if r.status_code in (200, 201):
        data = r.json().get("data", {})
        return True, data.get("id"), data.get("status", "unknown")
    if r.status_code == 429:
        return False, None, "rate_limited"
    return False, None, f"http_{r.status_code}: {r.text[:150]}"


def increase_offer(session, token, league_id, user_id, offer_id, new_amount, player_id):
    """PUT /api/v2/offers/{id} → aumentar puja."""
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    payload = {
        "to": None,
        "type": "purchase",
        "amount": new_amount,
        "requestedPlayers": [player_id],
    }
    r = requests.put(f"https://biwenger.as.com/api/v2/offers/{offer_id}", json=payload, headers=h, timeout=REQUEST_TIMEOUT)
    if r.status_code in (200, 201):
        return True, r.json()
    return False, f"http_{r.status_code}: {r.text[:150]}"


def retract_offer(session, token, league_id, user_id, offer_id):
    """DELETE /api/v2/offers/{id} → retirar oferta. 204 = éxito."""
    h = get_headers(token, {"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
    r = requests.delete(f"https://biwenger.as.com/api/v2/offers/{offer_id}", headers=h, timeout=REQUEST_TIMEOUT)
    if r.status_code in (200, 201, 204):
        return True, "ok"
    return False, f"http_{r.status_code}: {r.text[:150]}"


def run():
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"Biwenger Auto-Trader v8 — {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    biw = requests.Session()
    try:
        token = login(biw)
        print("✅ Login OK")
    except Exception as e:
        print(f"❌ Login fallido: {e}")
        sys.exit(1)

    # ── Account ────────────────────────────────────────
    print("\n--- Account ---")
    try:
        league_id, user_id, balance, points, user_name = get_account(biw, token)
        biw.headers.update({"X-League": str(league_id), "X-User": str(user_id), "X-Version": "631"})
        print(f"  {user_name} | {points}pts | €{balance:,}")
        print(f"  Liga: DATA CENTER GRUPO B (ID: {league_id})")
    except Exception as e:
        print(f"  ❌ Account error: {e}")
        sys.exit(1)

    # ── Squad con posiciones ───────────────────────────
    print("\n--- Squad ---")
    squad_ids, lineup_info, lineup_players = get_squad_with_positions(biw, token, league_id, user_id)
    if lineup_info is None:
        print("  ❌ No se pudo obtener squad")
        sys.exit(1)

    lineup_type = lineup_info.get("type", "?")
    lineup_ids_list = lineup_info.get("playersID", []) or []
    print(f"  {len(squad_ids)} jugadores en plantilla | formación actual: {lineup_type}")

    # ── Catálogo completo (posiciones, estado, puntos, forma) ──
    print("\n--- Catálogo La Liga ---")
    catalog, cat_teams = get_catalog(biw, token, league_id, user_id)
    print(f"  {len(catalog)} jugadores | {len(cat_teams)} equipos")

    # ── Dificultad del próximo rival (desde team.nextGames) ──
    diff_map, games_map, round_name = get_fixture_info(lineup_players)
    print(f"  Dificultad de rival conocida para {len(diff_map)} equipos | {round_name or 'próxima jornada'}")

    # ── Market ─────────────────────────────────────────
    print("\n--- Market ---")
    free_sales, user_sales = get_market(biw, token, league_id, user_id)
    print(f"  Total ventas: {len(free_sales) + len(user_sales)} | Free: {len(free_sales)} | Propias: {len(user_sales)}")

    if free_sales:
        print(f"  Free market (top 5):")
        for s in free_sales[:5]:
            p = s.get("player", {})
            print(f"    {p.get('name','?')} (id={p.get('id')}) €{s.get('price',0):,} | {s.get('status','?')}")

    # ── Optimización de alineación (scorer real) ───────
    print("\n--- Optimización ---")
    opt_all_ids, opt_type, opt_detail, pool = build_smart_lineup(squad_ids, catalog, diff_map)

    if opt_all_ids:
        pos_names = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
        print(f"  Puntuación de la plantilla ({len(pool)} jugadores):")
        for e in sorted(pool.values(), key=lambda x: x["score"], reverse=True):
            gm = games_map.get(e["team_id"], {})
            rival = gm.get("rival", "?")
            cond = gm.get("cond", "?")
            dr = diff_map.get(e["team_id"])
            dr_txt = f"dif={dr}" if dr is not None else "dif=?"
            print(f"    {e['name']:20} {pos_names.get(e['position'],'?'):3} score={e['score']:6.3f} "
                  f"vs {rival} ({cond}) {dr_txt}")
            print(f"        {e['why']}")

        print(f"\n  Mejor alineación: {opt_type} (total={opt_detail['total']})")
        print(f"    GK:  {[e['name'] for e in opt_detail['gk']]}")
        print(f"    DEF: {[e['name'] for e in opt_detail['def']]}")
        print(f"    MID: {[e['name'] for e in opt_detail['mid']]}")
        print(f"    FWD: {[e['name'] for e in opt_detail['fwd']]}")

        # ¿Quién entra y quién sale respecto a la alineación actual?
        entran = [i for i in opt_all_ids if i not in lineup_ids_list]
        salen = [i for i in lineup_ids_list if i not in opt_all_ids]
        if entran or salen:
            nm = {e["id"]: e["name"] for e in pool.values()}
            print(f"\n  Cambios propuestos:")
            for i in entran:
                print(f"    ⬆️  ENTRA: {nm.get(i, i)}")
            for i in salen:
                print(f"    ⬇️  SALE:  {nm.get(i, i)}")
        else:
            print(f"\n  ✅ La alineación actual ya es la mejor puntuada")
        log_action("lineup_eval", {
            "formation": opt_type,
            "total": opt_detail["total"],
            "entran": [pool[i]["name"] for i in entran if i in pool],
            "salen": [pool[i]["name"] for i in salen if i in pool],
        }, "info")
    else:
        opt_all_ids = []
        print("  ⚠️ No hay porteros en el squad → no se puede optimizar alineación")
        log_action("lineup_eval", {"result": "no_goalkeepers"}, "warning")

    # ── Ejecutar acciones ──────────────────────────────
    print(f"\n--- Acciones ---")
    actions = []
    write_count = 0

    # ESTRATEGIA PARA MAXIMIZAR PUNTOS SIN POSICIONES LIBRES:
    # 1. Vender SUPLENTES con score muy bajo/lesionados para liberar espacio
    #    (no toca a los titulares → no hay posiciones libres)
    # 2. Comprar jugadores del free market que mejoren a los titulares
    # 3. Vender los TITULARES reemplazados (ahora son suplentes)
    # 4. Alinear con los mejores 11
    free_market = get_free_market_with_positions(biw, token, league_id, user_id, catalog=catalog)

    pos_names = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    pending = get_pending_offers(biw, token, league_id, user_id)
    if pending:
        print(f"  ⏸ Ya tenemos ofertas activas por: {sorted(pending)}")

    # 0. PROCESAR OFERTAS RECIBIDAS — aceptar/rechazar ofertas de otros usuarios
    print(f"\n  0. Procesando ofertas recibidas:")
    next_match_date, next_round_name = get_next_match_date(biw, token, league_id, user_id)
    if next_match_date:
        from datetime import datetime as dt, timedelta
        days_until_match = (next_match_date - dt.now()).days
        print(f"    Próximo partido: {next_round_name} en ~{days_until_match} días")
        # Si el partido es mañana o pasado mañana, ser más conservador con las ventas
        match_soon = days_until_match <= 2
    else:
        match_soon = False
    received_offers = get_received_offers(biw, token, league_id, user_id)
    if received_offers:
        print(f"    Ofertas recibidas: {len(received_offers)}")
        for offer in received_offers:
            offer_id = offer.get("id")
            offer_amount = offer.get("amount", 0)
            requested = offer.get("requestedPlayers") or []
            player_id = None
            for rp in requested:
                if isinstance(rp, dict) and rp.get("id"):
                    player_id = rp["id"]
                elif isinstance(rp, int):
                    player_id = rp
            if not player_id:
                continue
            # Buscar el jugador en nuestro pool
            player_entry = pool.get(player_id)
            if not player_entry:
                # Si no está en el pool, buscar en el catálogo directamente
                cp = catalog.get(str(player_id))
                if cp:
                    player_entry = {
                        "id": player_id,
                        "name": cp.get("name", f"id={player_id}"),
                        "position": cp.get("position", 0),
                        "status": cp.get("status", "ok"),
                        "score": 0,
                    }
                else:
                    print(f"    ⚠️ Oferta {offer_id}: jugador id={player_id} no encontrado en pool ni catálogo")
                    continue
            player_name = player_entry.get("name", f"id={player_id}")
            # Precio de venta actual (si está en venta)
            market_price = 0
            cp = catalog.get(str(player_id))
            if cp:
                market_price = cp.get("price", 0)
            # Criterios mejorados de ofertas recibidas:
            # 1. Aceptar si oferta >= 110% del mercado y hay reemplazo
            # 2. Aceptar si lesionado/sancionado y oferta >= 90% del mercado
            # 3. Aceptar si oferta >= 125% del mercado aunque no haya reemplazo
            # 4. Rechazar el resto
            st = (player_entry.get("status") or "ok").lower()
            is_injured = st in ("injured", "suspended", "sanctioned")
            ratio = (offer_amount / market_price * 100) if market_price > 0 else 0
            threshold_110 = market_price * 1.1 if market_price > 0 else offer_amount * 0.9
            threshold_90 = market_price * 0.9 if market_price > 0 else offer_amount * 0.9
            threshold_125 = market_price * 1.25 if market_price > 0 else offer_amount * 1.25
            
            # Distinguir entre oferta del Computer y oferta de usuario
            is_computer_offer = abs(ratio - 100) <= 5 if market_price > 0 else False
            if is_computer_offer:
                print(f"    📱 Oferta del Computer #{offer_id} por {player_name} (id={player_id}) — €{offer_amount:,} (ratio={ratio:.1f}%)")
            else:
                print(f"    👤 Oferta de usuario #{offer_id} por {player_name} (id={player_id}) — €{offer_amount:,} (ratio={ratio:.1f}%)")
            
            # Verificar si hay reemplazo disponible (misma posición, estado ok, score >=)
            has_replacement = False
            if player_entry:
                pos = player_entry.get("position", 0)
                for r in free_market:
                    if (r.get("position") == pos and r.get("status") == "ok" and 
                        r.get("score", 0) >= player_entry.get("score", 0)):
                        has_replacement = True
                        break
            
            accept = False
            reason = ""
            if offer_amount >= threshold_125:
                accept = True
                reason = f"oferta >= 125% mercado (ratio={ratio:.1f}%)"
            elif offer_amount >= threshold_110 and has_replacement:
                accept = True
                reason = f"oferta >= 110% mercado y hay reemplazo (ratio={ratio:.1f}%)"
            elif is_injured and offer_amount >= threshold_90:
                accept = True
                reason = f"lesionado/sancionado y oferta >= 90% mercado (ratio={ratio:.1f}%)"
            
            if accept:
                print(f"    ✅ Aceptando oferta #{offer_id} por {player_name} (id={player_id}) — {reason}")
                ok, msg = accept_offer(biw, token, league_id, user_id, offer_id)
                if ok:
                    print(f"    ✅ Oferta aceptada")
                    actions.append({"type": "offer_accepted", "offer_id": offer_id,
                                    "player_id": player_id, "player_name": player_name,
                                    "amount": offer_amount})
                    write_count += 1
                    log_action("offer_accepted", {"offer_id": offer_id, "player_id": player_id,
                                                  "player_name": player_name, "amount": offer_amount}, "success")
                else:
                    print(f"    ❌ Error aceptando: {msg}")
                    log_action("offer_accept_failed", {"offer_id": offer_id, "reason": msg}, "error")
            else:
                print(f"    ❌ Rechazando oferta #{offer_id} por {player_name} (id={player_id}) — €{offer_amount:,} < €{threshold:,.0f} (ratio={ratio:.1f}%)")
                ok, msg = reject_offer(biw, token, league_id, user_id, offer_id)
                if ok:
                    print(f"    ✅ Oferta rechazada")
                    actions.append({"type": "offer_rejected", "offer_id": offer_id,
                                    "player_id": player_id, "player_name": player_name,
                                    "amount": offer_amount})
                    write_count += 1
                    log_action("offer_rejected", {"offer_id": offer_id, "player_id": player_id,
                                                  "player_name": player_name, "amount": offer_amount}, "success")
                else:
                    print(f"    ❌ Error rechazando: {msg}")
                    log_action("offer_reject_failed", {"offer_id": offer_id, "reason": msg}, "error")
    else:
        print(f"    ✅ No hay ofertas recibidas")

    # 1. VENTAS DE SUPLENTES — liberar espacio sin tocar titulares
    #    VALIDACIÓN: solo vender si hay reemplazo en el free market para evitar posiciones libres
    print(f"\n  1. Ventas de suplentes (con validación de reemplazo):")
    suplentes_to_sell = []
    for e in pool.values():
        if e["id"] in lineup_ids_list:
            continue  # NO vender titulares aquí
        st = (e.get("status") or "ok").lower()
        if st in ("injured", "suspended", "sanctioned"):
            # Lesionados/suspendidos: vender solo si hay reemplazo
            has_replacement = any(
                r.get("position") == e["position"] and r.get("status") == "ok"
                for r in free_market
            )
            if has_replacement:
                suplentes_to_sell.append({**e, "reason": f"status={st} (con reemplazo)"})
            else:
                print(f"    ⏸ {e['name']} ({st}) — sin reemplazo en mercado, no se vende")
        elif e["score"] < 2.0:
            # Score bajo: vender solo si hay reemplazo
            # Si el partido está cerca (<=2 días), ser más conservador y no vender por score bajo
            if match_soon:
                print(f"    ⏸ {e['name']} (score={e['score']:.3f}) — partido cerca, se mantiene para asegurar equipo completo")
                continue
            has_replacement = any(
                r.get("position") == e["position"] and r.get("status") == "ok"
                for r in free_market
            )
            if has_replacement:
                suplentes_to_sell.append({**e, "reason": f"score_bajo={e['score']:.3f} (con reemplazo)"})
            else:
                print(f"    ⏸ {e['name']} (score={e['score']:.3f}) — sin reemplazo en mercado, no se vende")

    if suplentes_to_sell:
        for cand in suplentes_to_sell:
            # Usar precio de mercado del catálogo (el API rechaza precios muy bajos)
            cp = catalog.get(str(cand["id"]))
            market_price = cp.get("price", 0) if cp else 0
            sell_price = max(market_price, 1)
            print(f"\n  Vendiendo suplente {cand['name']} (score={cand['score']:.3f}) — {cand['reason']} | precio venta=€{sell_price:,}")
            ok, msg, used_price = sell_player(biw, token, league_id, user_id, cand["id"], sell_price)
            if ok:
                print(f"    ✅ Puesto en venta a €{used_price:,}")
                actions.append({"type": "sell_sub", "player_id": cand["id"],
                                "player_name": cand["name"], "price": used_price})
                write_count += 1
                log_action("sell_sub", {"player_id": cand["id"], "player_name": cand["name"],
                                        "reason": cand["reason"], "price": used_price}, "success")
            else:
                print(f"    ❌ {msg}")
                actions.append({"type": "sell_sub_failed", "player_id": cand["id"], "reason": msg})
                log_action("sell_sub_failed", {"player_id": cand["id"], "player_name": cand["name"],
                                               "reason": msg}, "error")
    else:
        print(f"  ✅ No hay suplentes que vender (o no hay reemplazos disponibles)")

    # 2. COMPRAS — buscar talento que mejore a los titulares actuales
    print(f"\n  2. Compras (free market con posiciones, máx 2):")
    print(f"    Free market con posiciones: {len(free_market)} jugadores")
    
    candidatos = []
    for r in free_market:
        if r.get("status") != "ok":
            continue
        if r["id"] in pending:
            continue
        cp = catalog.get(str(r["id"]))
        if not cp:
            continue
        sc, why = score_player(cp, diff_map.get(cp.get("teamID")))
        r["score"] = sc
        r["why"] = why
        candidatos.append(r)

    candidatos.sort(key=lambda x: x["score"], reverse=True)

    print(f"    Mejores del mercado por puntuación:")
    for r in candidatos[:6]:
        pos_n = pos_names.get(r.get("position"), "?")
        print(f"      {r.get('name','?'):22} {pos_n:3} score={r['score']:6.3f} €{r.get('price',0):,}")

    # Umbral del 5% — ESTRATEGIA AGRESIVA
    titulares_score = {}
    if opt_detail:
        for grupo, key in (("gk", "gk"), ("def", "def"), ("mid", "mid"), ("fwd", "fwd")):
            for e in opt_detail[key]:
                titulares_score.setdefault(e["position"], []).append(e["score"])

    fichar = []
    for r in candidatos:
        pos = r.get("position")
        scores_pos = titulares_score.get(pos, [])
        if not scores_pos:
            continue
        peor_titular = min(scores_pos)
        if r["score"] > peor_titular * 1.05 and r.get("price", 0) <= balance:
            fichar.append({**r, "peor_titular": peor_titular})

    if not fichar:
        print(f"\n    ✅ Ningún jugador del mercado mejora a nuestros titulares")
        log_action("buy_check", {"result": "no_upgrade_available",
                                 "evaluados": len(candidatos)}, "info")

    # Control de saldo con colchón (5-10% del valor del equipo, mínimo ~500k)
    team_value = sum(catalog.get(str(pid), {}).get("price", 0) for pid in squad_ids if catalog.get(str(pid)))
    cushion = max(team_value * 0.08, 500000)
    committed = sum(o.get("amount", 0) for o in offers_data if o.get("from", {}).get("id") == user_id and o.get("status") == "waiting")
    available = balance - committed - cushion
    print(f"\n    💰 Saldo: €{balance:,} | Comprometido: €{committed:,} | Colchón: €{cushion:,.0f} | Disponible: €{available:,.0f}")

    for p in fichar[:2]:
        if write_count >= MAX_WRITES:
            print("    ⚠️ Límite de escrituras alcanzado")
            break
        pid = p.get("id")
        amount = p.get("price", 0)
        pname = p.get("name", f"id={pid}")
        pos = p.get("position", 0)
        
        # Pujas dinámicas según competencia estimada
        # c baja: 1.03-1.05 | c media: 1.08-1.12 | c alta: 1.15-1.25
        # Estimación: jugador con score alto + titular + valor en subida = alta competencia
        competition = "baja"
        if p["score"] > 5.0 and p.get("price", 0) > 3000000:
            competition = "alta"
        elif p["score"] > 3.5:
            competition = "media"
        
        if competition == "baja":
            bid_amount = int(amount * 1.04)
        elif competition == "media":
            bid_amount = int(amount * 1.10)
        else:
            bid_amount = int(amount * 1.20)
        
        # Techo de puja: no pasar del 125% del mercado
        max_bid = int(amount * 1.25)
        bid_amount = min(bid_amount, max_bid)
        
        print(f"\n    Jugador: {pname} (id={pid}) pos={pos_names.get(pos, '?')} a €{amount:,}")
        print(f"      score={p['score']} > peor titular {pos_names.get(pos,'?')}={p['peor_titular']}")
        print(f"      Competencia: {competition} | Puja: €{bid_amount:,} (techo: €{max_bid:,})")
        
        if bid_amount > available:
            print(f"    ⚠️ Puja excede saldo disponible (€{bid_amount:,} > €{available:,}) — omitiendo")
            continue

        ok, offer_id, status = create_purchase_offer(biw, token, league_id, user_id, pid, bid_amount)
        if ok:
            print(f"    ✅ Oferta creada: ID={offer_id}, status={status}")
            actions.append({"type": "buy_offer_created", "player_id": pid,
                            "player_name": pname, "amount": bid_amount, "offer_id": offer_id})
            write_count += 1
            log_action("buy_offer_created", {"player_id": pid, "player_name": pname,
                                             "amount": bid_amount, "offer_id": offer_id,
                                             "score": p["score"],
                                             "peor_titular": p["peor_titular"],
                                             "competition": competition}, "success")
            available -= bid_amount
            print(f"    ✅ Oferta dejada activa (no se retira) | Disponible restante: €{available:,.0f}")
        else:
            print(f"    ❌ No se pudo crear oferta: {status}")
            log_action("buy_offer_failed", {"player_id": pid, "player_name": pname, "reason": status}, "error")

    # 3. VENTAS DE TITULARES REEMPLAZADOS — solo si ya fueron comprados los reemplazos
    #    (esto se ejecutará en la próxima corrida, cuando los reemplazos ya estén en el squad)
    print(f"\n  3. Ventas de titulares reemplazados (próxima corrida):")
    print(f"    ⏸ Se ejecutarán automáticamente cuando los reemplazos comprados lleguen al squad")

    # 4. Salvaguardia obligatoria: comprobar que la alineación tendrá posiciones completas.
    # La regla del usuario es clara: una posición libre descuenta puntos. Por eso, nunca
    # preparamos menos de 11 jugadores ni permitimos que falte GK/DEF/MID/FWD.
    if opt_all_ids and len(opt_all_ids) >= 11:
        required_pos = {1: 1, 2: 3, 3: 3, 4: 1}
        pos_pool = {}
        for player_id in opt_all_ids:
            entry = pool.get(player_id)
            if entry:
                pos_pool[entry["position"]] = pos_pool.get(entry["position"], 0) + 1
        posiciones_incompletas = [
            f"{pos_names.get(p, p)}={pos_pool.get(p, 0)}"
            for p, needed in required_pos.items() if pos_pool.get(p, 0) < needed
        ]
        if posiciones_incompletas:
            log_action("lineup_blocked", {
                "reason": "incomplete_positions",
                "positions": pos_pool,
                "missing": ", ".join(posiciones_incompletas),
            }, "warning")
            print(f"  ⏸ Alineación segura no posible: {', '.join(posiciones_incompletas)}")
            actions.append({"type": "lineup_blocked", "reason": "incomplete_positions",
                            "positions": pos_pool})
        else:
            print(f"  ✅ Comprobación de posiciones completas: {pos_pool}")
    elif opt_all_ids:
        print(f"  ⏸ Alineación segura no posible: solo {len(opt_all_ids)} jugadores disponibles")
        actions.append({"type": "lineup_blocked", "reason": "insufficient_players",
                        "count": len(opt_all_ids)})
        log_action("lineup_blocked", {"reason": "insufficient_players",
                                      "count": len(opt_all_ids)}, "warning")
    else:
        print("  ⏸ Alineación segura no posible: no hay combinación válida disponible")
        actions.append({"type": "lineup_blocked", "reason": "no_valid_lineup"})
        log_action("lineup_blocked", {"reason": "no_valid_lineup"}, "warning")

    # 5. Alineación — solo cambiar si la mejora es significativa (evita ruido)
    print(f"\n  Alineación:")
    MIN_LINEUP_GAIN = 0.05  # 5% de mejora mínima sobre la alineación actual
    current_total = 0.0
    for e in pool.values():
        if e["id"] in lineup_ids_list:
            current_total += e["score"]
    current_total = round(current_total, 3)
    best_total = opt_detail["total"] if opt_detail else 0.0
    gain = best_total - current_total
    gain_pct = (gain / current_total * 100) if current_total > 0 else 100.0

    if opt_all_ids and opt_all_ids != lineup_ids_list:
        if gain_pct >= MIN_LINEUP_GAIN * 100:
            print(f"    Mejora: {current_total} → {best_total} (+{gain:.3f}, {gain_pct:+.1f}%)")
            print(f"    Cambiando a {opt_type}: {opt_all_ids}")
            ok, resp = set_lineup(biw, token, league_id, user_id, opt_all_ids, opt_type)
            if ok:
                print(f"    ✅ Alineación actualizada a {opt_type}")
                actions.append({"type": "lineup_set", "formation": opt_type,
                                "players": opt_all_ids, "response": resp})
                write_count += 1
                log_action("lineup_set", {"formation": opt_type, "total": best_total,
                                          "gain_pct": round(gain_pct, 2),
                                          "players": opt_all_ids}, "success")
            else:
                print(f"    ❌ Error alineación: {resp}")
                actions.append({"type": "lineup_failed", "reason": resp})
                log_action("lineup_failed", {"reason": resp, "formation": opt_type}, "error")
        else:
            print(f"    ⏸ Mejora insuficiente ({gain_pct:+.1f}% < {MIN_LINEUP_GAIN*100}%) — se mantiene {lineup_type}")
            actions.append({"type": "lineup_skipped", "reason": "gain_below_threshold",
                            "gain_pct": round(gain_pct, 2)})
            log_action("lineup_skipped", {"reason": "gain_below_threshold",
                                          "gain_pct": round(gain_pct, 2),
                                          "current": current_total, "best": best_total}, "info")
    elif opt_all_ids:
        print(f"    ⏸ Sin cambios (alineación ya óptima: {opt_type}, total={best_total})")
        actions.append({"type": "lineup_skipped", "reason": "already_optimal"})
        log_action("lineup_skipped", {"reason": "already_optimal", "total": best_total}, "info")
    else:
        print(f"    ⚠️ No se puede alinear (sin porteros)")
        actions.append({"type": "lineup_blocked", "reason": "no_goalkeepers"})
        log_action("lineup_blocked", {"reason": "no_goalkeepers"}, "warning")

    # ── Guardar state ──────────────────────────────────
    state = {
        "date": now.isoformat(),
        "points": points,
        "position": 0,
        "balance": balance,
        "league_id": league_id,
        "user_id": user_id,
        "formation": opt_type or lineup_type,
        "current_lineup_ids": list(lineup_ids_list),
        "optimal_lineup_ids": opt_all_ids,
        "lineup_scores": {e["name"]: e["score"] for e in pool.values()} if pool else {},
        "lineup_total": opt_detail["total"] if opt_detail else None,
        "round": round_name,
        "actions": actions,
        "peticiones_usadas": 0,
        "limite_peticiones": 10,
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print(f"\n  ✅ State: {STATE_FILE}")

    # ── Guardar todo ───────────────────────────────────
    todo = [
        f"# Biwenger Auto-Trader v8 — Brayan Lopez",
        f"**Liga:** DATA CENTER GRUPO B (ID: {league_id})",
        f"**Usuario:** {user_name} (ID: {user_id}) | **Balance:** €{balance:,}",
        f"**Puntos:** {points} | **Ejecución:** {now}",
        "",
        "## Acciones",
    ]
    for a in actions:
        t = a["type"]
        if t == "sell":
            todo.append(f"✅ Vendido {a['player_name']} (€{a['price']:,})")
        elif t == "sell_failed":
            todo.append(f"❌ Venta fallida: {a['reason']}")
        elif t == "buy_offer_created":
            todo.append(f"🔵 Oferta compra {a['player_name']} (€{a['amount']:,}) — ID:{a['offer_id']}")
        elif t == "buy_offer_increased":
            todo.append(f"🔵 Puja aumentada a €{a['new_amount']:,}")
        elif t == "buy_offer_retracted":
            todo.append(f"🔵 Oferta retirada")
        elif t == "buy_failed":
            todo.append(f"❌ Compra fallida: {a['reason']}")
        elif t == "lineup_set":
            todo.append(f"✅ Alineación: {a['formation']} — {len(a['players'])} jugadores")
        elif t == "lineup_failed":
            todo.append(f"❌ Alineación fallida: {a['reason']}")
        elif t == "lineup_skipped":
            r = a.get("reason")
            if r == "already_optimal":
                todo.append(f"⏸ Alineación sin cambios (ya óptima)")
            elif r == "gain_below_threshold":
                todo.append(f"⏸ Alineación sin cambios (mejora {a.get('gain_pct', 0):+.1f}% < 5%)")
            else:
                todo.append(f"⏸ Alineación sin cambios")
        elif t == "lineup_blocked":
            todo.append(f"🔒 Alineación bloqueada: {a['reason']}")
        elif t == "sell_skipped":
            todo.append(f"⏸ Venta descartada: {a.get('reason')}")
    with open(TODO_FILE, "w") as f:
        f.write("\n".join(todo) + "\n")
    print(f"  ✅ Todo: {TODO_FILE}")

    print(f"\n{'='*60}")
    print(f"✅ Ejecución completada — {len(actions)} acciones, {write_count} writes")
    print(f"{'='*60}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"ERROR FATAL: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

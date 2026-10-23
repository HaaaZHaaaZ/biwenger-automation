#!/usr/bin/env python3
"""
Biwenger Auto-Trader v12
========================
Cambios respecto a v11 (ver CHANGELOG al final del fichero):
  - Corregidos los fallos que cortaban la ejecución (threshold / offers_data).
  - p_start y localía se usan de verdad en el scorer.
  - Dificultad del rival: solo el PRÓXIMO partido de cada equipo.
  - "Partido cerca" calculado con fechas reales (con respaldo conservador).
  - Ofertas recibidas: se simula la plantilla resultante antes de aceptar.
  - La alineación se bloquea de verdad si faltan posiciones.
  - Capitán / ariete preparados (activar con variables de entorno).
  - Toda la configuración por variables de entorno o fichero .env.
  - Modo --dry-run (no escribe nada) y --probe (descubre campos de la API).

Uso:
  python3 biwenger_daily.py              # ejecución normal
  python3 biwenger_daily.py --dry-run    # simula, sin escrituras
  python3 biwenger_daily.py --probe      # vuelca los campos de lineup (capitán/ariete)

Códigos de salida: 0 ok · 1 error · 3 token/credenciales · 5 X-Version obsoleta · 6 rate limit
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

import requests

VERSION = "13.3"
REQ = {"count": 0}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ──────────────────────────────────────────────────────────
# Configuración (variables de entorno / .env)
# ──────────────────────────────────────────────────────────

def _load_dotenv(path):
    """Carga un .env sencillo (KEY=VALUE). No pisa variables ya definidas."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(BASE_DIR, ".env"))


def env_str(name, default=""):
    return (os.environ.get(name) or default).strip()


def env_int(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "si", "sí", "on")


# Credenciales
EMAIL = env_str("BIWENGER_EMAIL")
PASSWORD = env_str("BIWENGER_PASSWORD")
TOKEN = env_str("BIWENGER_TOKEN")          # opcional: si existe, no se hace login
LEAGUE_ID = env_int("BIWENGER_LEAGUE_ID", 0)   # 0 = automático
USER_ID = env_int("BIWENGER_USER_ID", 0)       # 0 = automático

# API
APP_VERSION = env_str("BIWENGER_VERSION", "631")   # cabecera X-Version
UA = env_str(
    "BIWENGER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
)
REQUEST_TIMEOUT = env_int("BIWENGER_REQUEST_TIMEOUT", 30)
WAIT_BUDGET_SECONDS = env_int("BIWENGER_WAIT_BUDGET_SECONDS", 90)
MAX_RETRIES = env_int("BIWENGER_MAX_RETRIES", 1)
RETRY_DELAY = env_int("BIWENGER_RETRY_DELAY", 30)
REQUEST_DELAY = env_float("BIWENGER_REQUEST_DELAY", 0.8)       # pausa media entre peticiones
START_JITTER_MAX = env_int("BIWENGER_START_JITTER_MAX", 0)     # segundos aleatorios al empezar
RATE_LIMIT_WAIT_HOURS = env_float("BIWENGER_RATE_LIMIT_WAIT_HOURS", 4)

# Ficheros
DATA_DIR = env_str("BIWENGER_DATA_DIR", "/opt/data")
LOCKFILE_PATH = os.getenv("BIWENGER_LOCKFILE_PATH", os.path.join(DATA_DIR, "biwenger.lock"))
UNKNOWN_STATE_PATH = os.getenv("BIWENGER_UNKNOWN_STATE_PATH", os.path.join(DATA_DIR, "unknown_state.json"))
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.access(DATA_DIR, os.W_OK):
        raise OSError("sin permiso de escritura")
except OSError:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "biwenger_state.json")
TODO_FILE = os.path.join(DATA_DIR, "biwenger_todo.md")
LOG_FILE = os.path.join(DATA_DIR, "biwenger_log.json")
LOG_TXT_FILE = os.path.join(DATA_DIR, "biwenger_log.txt")
PROBE_FILE = os.path.join(DATA_DIR, "biwenger_probe.json")
RATE_FILE = os.path.join(DATA_DIR, "biwenger_ratelimit.json")
MAX_LOG_ENTRIES = env_int("BIWENGER_MAX_LOG_ENTRIES", 1500)

# Límites de actividad
MAX_WRITES = env_int("BIWENGER_MAX_WRITES", 8)
MAX_BUYS = env_int("BIWENGER_MAX_BUYS", 2)
MAX_SELLS = env_int("BIWENGER_MAX_SELLS", 4)
MIN_SQUAD = env_int("BIWENGER_MIN_SQUAD", 12)      # nunca bajar de esta plantilla por ventas
MAX_SQUAD = env_int("BIWENGER_MAX_SQUAD", 0)       # 0 = sin comprobar tope de plantilla
# Opción B: con la alineación ya cerrada y el partido cerca, SÍ se puede vender
# suplentes de score bajo. La restricción de 48h solo aplica si la alineación
# no está completa (riesgo real de quedarse con menos de 11).
SELL_BENCH_WHEN_LINEUP_READY = env_bool("BIWENGER_SELL_BENCH_LINEUP_READY", True)
DRY_RUN = env_bool("BIWENGER_DRY_RUN", True)

# Alineación / scorer
MIN_LINEUP_GAIN = env_float("BIWENGER_MIN_LINEUP_GAIN", 0.05)
SELL_SCORE_MIN = env_float("BIWENGER_SELL_SCORE_MIN", 2.0)
MATCH_SOON_HOURS = env_float("BIWENGER_MATCH_SOON_HOURS", 48)
MIN_P_START_BUY = env_float("BIWENGER_MIN_P_START_BUY", 0.7)
CAPTAIN_KEY = env_str("BIWENGER_CAPTAIN_KEY")      # p. ej. "captain" (vacío = desactivado)
STRIKER_KEY = env_str("BIWENGER_STRIKER_KEY")      # p. ej. "striker" (vacío = desactivado)
CAPTAIN_MAX_VALUE = env_int("BIWENGER_CAPTAIN_MAX_VALUE", 0)  # 0 = sin tope de valor

# Compras / pujas
BUY_MARGIN = env_float("BIWENGER_BUY_MARGIN", 0.05)
CUSHION_PCT = env_float("BIWENGER_CUSHION_PCT", 0.08)
CUSHION_MIN = env_int("BIWENGER_CUSHION_MIN", 500000)
BID_LOW = env_float("BIWENGER_BID_LOW", 1.04)
BID_MID = env_float("BIWENGER_BID_MID", 1.10)
BID_HIGH = env_float("BIWENGER_BID_HIGH", 1.20)
MAX_BID_PCT = env_float("BIWENGER_MAX_BID_PCT", 1.25)
BID_PLUS_ONE = env_bool("BIWENGER_BID_PLUS_ONE", True)  # +1 € para evitar empates exactos

# Ofertas recibidas
ACCEPT_NORMAL = env_float("BIWENGER_ACCEPT_NORMAL", 1.10)
ACCEPT_HIGH = env_float("BIWENGER_ACCEPT_HIGH", 1.25)
ACCEPT_INJURED = env_float("BIWENGER_ACCEPT_INJURED", 0.90)
MAX_DROP_PCT = env_float("BIWENGER_MAX_DROP_PCT", 0.08)
# Desbloqueo de cupo: con la liga a 16 (jugadores + ofertas abiertas) una venta
# solo libera hueco si COMPLETA la venta. Si las ofertas de la máquina se
# rechazan, la cuenta queda bloqueada (16/16) y no puede comprar nunca.
ACCEPT_MACHINE_MIN = env_float("BIWENGER_ACCEPT_MACHINE_MIN", 0.92)
MAX_TEAM_SIZE = env_int("BIWENGER_MAX_TEAM_SIZE", 16)

BAD_STATUS = {"injured", "suspended", "sanctioned"}
POS_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# Multiplicador por estado real del jugador. 0.0 = no puede puntuar.
STATUS_MULT = {
    "ok": 1.00,
    "warned": 0.85,   # apercibido: riesgo de sanción
    "doubt": 0.55,    # duda
    "injured": 0.00,
    "suspended": 0.00,
    "sanctioned": 0.00,
}

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


# ──────────────────────────────────────────────────────────
# Logs
# ──────────────────────────────────────────────────────────

def log_action(action_type, details, status="info"):
    """Registra una acción en el log JSON (rotado) y en el TXT. Escritura atómica + lock."""
    import fcntl
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"timestamp": timestamp, "action": action_type, "status": status, "details": details}
    try:
        if os.path.dirname(LOG_FILE):
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                logs = json.load(f)
            except (OSError, ValueError):
                logs = []
            logs.append(entry)
            logs = logs[-MAX_LOG_ENTRIES:]
            tmp = LOG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as tf:
                json.dump(logs, tf, indent=2, ensure_ascii=False)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp, LOG_FILE)
            fcntl.flock(f, fcntl.LOCK_UN)
        if os.path.exists(LOG_TXT_FILE) and os.path.getsize(LOG_TXT_FILE) > 2_000_000:
            os.replace(LOG_TXT_FILE, LOG_TXT_FILE + ".1")
        with open(LOG_TXT_FILE, "a", encoding="utf-8") as f:
            f.write("[" + timestamp + "] [" + status.upper() + "] " + action_type + ": " +
                    json.dumps(details, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
    return entry

def get_headers(token=None, league_id=None, user_id=None):
    h = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "X-Lang": "es",
        "X-Version": APP_VERSION,
        "Origin": "https://biwenger.as.com",
        "Referer": "https://biwenger.as.com/",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    if league_id:
        h["X-League"] = str(league_id)
    if user_id:
        h["X-User"] = str(user_id)
    return h


import json as _json

def save_unknown_state(op):
    try:
        data = []
        if os.path.exists(UNKNOWN_STATE_PATH):
            with open(UNKNOWN_STATE_PATH) as f:
                data = _json.load(f)
        data.append(op)
        with open(UNKNOWN_STATE_PATH, "w") as f:
            _json.dump(data, f)
    except Exception as e:
        log_action("unknown_state_save_error", {"error": str(e)}, "error")

def load_unknown_state():
    try:
        if os.path.exists(UNKNOWN_STATE_PATH):
            with open(UNKNOWN_STATE_PATH) as f:
                return _json.load(f)
    except Exception:
        return []
    return []

def resolve_unknown_state(ctx):
    ops = load_unknown_state()
    if not ops:
        return
    for op in ops:
        log_action("unknown_state_pending", op, "warning")
    # no repetir automáticamente; dejar pendiente para revisión manual
    with open(UNKNOWN_STATE_PATH, "w") as f:
        _json.dump(ops, f)




def set_ctx(ctx):
    global _CTX
    _CTX = ctx

# Presupuesto global de espera por ejecución
_WAITED = 0
_WAIT_BUDGET = WAIT_BUDGET_SECONDS


def set_wait_budget(budget):
    global _WAIT_BUDGET, _WAITED
    _WAIT_BUDGET = budget
    _WAITED = 0


def set_session(s):
    global _SESSION
    _SESSION = s



def _summarize_body(body):
    if body is None:
        return None
    try:
        import json
        s = json.dumps(body)
        return s[:200]
    except Exception:
        return str(body)[:200]

def api(method, url, token=None, league_id=None, user_id=None, body=None):
    """Petición con reintento por red, pausa entre llamadas y errores tipados.
    Usa la Session compartida si existe (creada en run()); si no, requests directo.
    - GET: reintenta ante errores de red con backoff corto (2s/4s/8s, tope 60s).
    - POST/PUT/DELETE: NO reintenta tras timeout/error de lectura (evita duplicar ofertas/ventas);
      solo reintenta ante 429 respetando Retry-After (acotado a 60s).
    - Presupuesto global de espera: si se agota, aborta limpio."""
    global _WAITED
    headers = get_headers(token, league_id, user_id)
    session = _SESSION
    is_write = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
    max_retries = MAX_RETRIES if method.upper() == "GET" else 0
    backoff = [2, 4, 8]
    for attempt in range(max_retries + 1):
        REQ["count"] += 1
        try:
            if session is not None:
                r = session.request(method, url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
            else:
                r = requests.request(method, url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            if is_write:
                save_unknown_state({"type": "unknown", "method": method, "url": url, "payload": _summarize_body(body), "timestamp": datetime.now().isoformat()})
                if _CTX is not None:
                    _CTX.abort = True
            if (not is_write) and attempt < max_retries:
                sleep = backoff[min(attempt, len(backoff) - 1)]
                if _WAITED + sleep > _WAIT_BUDGET:
                    log_action("wait_budget_exhausted", {"waited": _WAITED, "budget": _WAIT_BUDGET}, "warning")
                    if _CTX is not None:
                        _CTX.abort = True
                    return None
                time.sleep(sleep)
                _WAITED += sleep
                continue
            log_action("network_error", {"method": method, "url": url, "error": str(e)}, "error")
            return None
        if REQUEST_DELAY > 0:
            time.sleep(random.uniform(0.7, 1.3) * REQUEST_DELAY)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            try:
                wait = int(retry_after) if retry_after else RATE_LIMIT_WAIT_HOURS * 3600
            except (TypeError, ValueError):
                wait = int(RATE_LIMIT_WAIT_HOURS * 3600)
            if wait > 60:
                log_action("retry_after_too_long", {"wait": wait, "url": url}, "warning")
                if _CTX is not None:
                    _CTX.abort = True
                return None
            wait = min(wait, 60)
            if attempt < (MAX_RETRIES if is_write else max_retries):
                if _WAITED + wait > _WAIT_BUDGET:
                    log_action("wait_budget_exhausted", {"waited": _WAITED, "budget": _WAIT_BUDGET}, "warning")
                    return None
                time.sleep(wait)
                _WAITED += wait
                continue
            raise RateLimited(url)
        if r.status_code == 401:
            raise AuthError(url)
        if r.status_code == 400 and "old version" in (r.text or "").lower():
            raise OldVersion(url)
        return r
    return None

_api_write = api


def rate_limit_active():
    try:
        with open(RATE_FILE, "r", encoding="utf-8") as f:
            until = datetime.fromisoformat(json.load(f)["until"])
        if datetime.now() < until:
            return until
    except (OSError, ValueError, KeyError):
        pass
    return None


def set_rate_limit():
    until = datetime.now() + timedelta(hours=RATE_LIMIT_WAIT_HOURS)
    try:
        with open(RATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"until": until.isoformat()}, f)
    except OSError:
        pass
    return until


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


# ──────────────────────────────────────────────────────────
# Lecturas de la API
# ──────────────────────────────────────────────────────────

def login():
    """POST /api/v2/auth/login → token Bearer."""
    if not EMAIL or not PASSWORD:
        raise ValueError("Faltan BIWENGER_EMAIL / BIWENGER_PASSWORD (o BIWENGER_TOKEN)")
    r = _api_write("POST", "https://biwenger.as.com/api/v2/auth/login",
            body={"email": EMAIL, "password": PASSWORD})
    if r is None or r.status_code != 200:
        raise ValueError(f"Login fallido: {None if r is None else r.status_code}")
    data = r.json()
    token = data.get("token") or (data.get("data") or {}).get("token")
    if not token:
        raise ValueError("Login sin token")
    return token


def get_account(token):
    """GET /api/v2/account → league_id, user_id, balance, points, name."""
    r = api("GET", "https://biwenger.as.com/api/v2/account", token)
    if r is None or r.status_code != 200:
        raise ValueError(f"Account error: {None if r is None else r.status_code}")
    data = r.json().get("data", {})
    leagues = data.get("leagues", [])
    if not leagues:
        raise ValueError("No hay ligas activas")
    league = leagues[0]
    if LEAGUE_ID:
        league = next((lg for lg in leagues if lg.get("id") == LEAGUE_ID), leagues[0])
    user = league.get("user", {})
    league_id = league.get("id")
    user_id = USER_ID or user.get("id")
    if not league_id or not user_id:
        raise ValueError(f"Account incompleto: {league}")
    return league_id, user_id, user.get("balance", 0), user.get("points", 0), user.get("name", "?")


SQUAD_FIELDS = (
    "players(id),"
    "lineup(round,id,type,playersID,reservesID,"
    "players(id,name,position,altPositions,status,fitness,points,price,"
    "team(id,name,slug,nextGames(*))))"
)


def get_squad(ctx):
    """Plantilla completa + alineación actual + titulares con team.nextGames."""
    r = api("GET", "https://biwenger.as.com/api/v2/user?fields=" + SQUAD_FIELDS,
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return None, None, None
    data = r.json().get("data", {})
    squad_ids = [p.get("id") for p in data.get("players", []) if isinstance(p, dict) and p.get("id")]
    lineup = data.get("lineup") or {}
    return squad_ids, lineup, lineup.get("players") or []


def get_catalog(ctx):
    """Catálogo de La Liga: posición, estado, puntos, forma, precio, equipo."""
    r = api("GET", "https://cf.biwenger.com/api/v2/competitions/la-liga/data?lang=es&score=3",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return {}, {}
    data = r.json().get("data", {})
    return (data.get("players") or {}), (data.get("teams") or {})


def get_round_name(ctx):
    r = api("GET", "https://biwenger.as.com/api/v2/rounds/league", ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return None
    return ((r.json().get("data") or {}).get("round") or {}).get("name")


def get_market(ctx):
    """GET /api/v2/market → (ventas libres, ventas propias)."""
    r = api("GET", "https://biwenger.as.com/api/v2/market", ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return [], []
    sales = (r.json().get("data") or {}).get("sales", [])
    free_sales = [s for s in sales if s.get("user") is None]
    own_sales = [s for s in sales if (s.get("user") or {}).get("id") == ctx.user_id]
    return free_sales, own_sales


def get_offers(ctx):
    """GET /api/v2/offers?status=waiting → SOLO ofertas pendientes (una llamada por ejecución)."""
    r = api("GET", "https://biwenger.as.com/api/v2/offers?status=waiting", ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return []
    data = r.json().get("data")
    return [o for o in data if isinstance(o, dict)] if isinstance(data, list) else []


def offer_player_ids(o):
    ids = []
    for rp in (o.get("requestedPlayers") or []):
        if isinstance(rp, dict) and rp.get("id"):
            ids.append(rp["id"])
        elif isinstance(rp, int):
            ids.append(rp)
    return ids


def guarded_write(ctx, kind, fn, *args, **kwargs):
    """Punto único de control para toda escritura."""
    if getattr(ctx, "abort", False):
        log_action("write_aborted", {"kind": kind, "reason": "abort"}, "warning")
        return False, "aborted"
    if getattr(ctx, "read_only", False):
        log_action("read_only_skip", {"kind": kind}, "info")
        return False, "read_only"
    if getattr(ctx, "dry_run", False):
        log_action("dry_run_skip", {"kind": kind}, "info")
        return False, "dry_run"
    if getattr(ctx, "write_count", 0) >= MAX_WRITES:
        log_action("write_limit", {"kind": kind, "limit": MAX_WRITES}, "warning")
        return False, "write_limit"
    ctx.write_count += 1
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log_action("write_error", {"kind": kind, "error": str(e)}, "error")
        return False, "error"

# ──────────────────────────────────────────────────────────
# Escrituras (todas respetan --dry-run)
# ──────────────────────────────────────────────────────────

def sell_player(ctx, player_id, price):
    """POST /api/v2/market → poner en venta. 204 = éxito."""
    if not price or price <= 0:
        log_action("sell_skipped", {"player_id": player_id, "reason": "no_market_price"}, "warning")
        print(f"     ⚠️ No se vende id={player_id}: sin precio de mercado fiable")
        return False, "no_market_price", 0
    sell_price = price
    gw = guarded_write(ctx, "sell", lambda: api("POST", "https://biwenger.as.com/api/v2/market", ctx.token, ctx.league_id, ctx.user_id,
            {"player": player_id, "price": sell_price}))
    if isinstance(gw, tuple):
        return gw[0], gw[1], sell_price
    r = gw
    if r is None:
        return False, "network_error", sell_price
    if r.status_code in (200, 201, 204):
        return True, "ok", sell_price
    return False, f"http_{r.status_code}: {r.text[:120]}", sell_price


def answer_offer(ctx, offer_id, status):
    """PUT /api/v2/offers/{id} con status accepted/rejected."""
    gw = guarded_write(ctx, "answer_offer", lambda: api("PUT", f"https://biwenger.as.com/api/v2/offers/{offer_id}", ctx.token, ctx.league_id,
            ctx.user_id, {"status": status}))
    if isinstance(gw, tuple):
        return gw
    r = gw
    if r is None:
        return False, "network_error"
    if r.status_code in (200, 201):
        return True, "ok"
    return False, f"http_{r.status_code}: {r.text[:150]}"


def create_purchase_offer(ctx, player_id, amount):
    """POST /api/v2/offers → oferta de compra al mercado libre."""
    gw = guarded_write(ctx, "create_purchase_offer", lambda: api("POST", "https://biwenger.as.com/api/v2/offers", ctx.token, ctx.league_id, ctx.user_id,
            {"to": None, "type": "purchase", "amount": amount, "requestedPlayers": [player_id]}))
    if isinstance(gw, tuple):
        return gw[0], None, gw[1]
    r = gw
    if r is None:
        return False, None, "network_error"
    if r.status_code in (200, 201):
        data = r.json().get("data", {})
        return True, data.get("id"), data.get("status", "unknown")
    return False, None, f"http_{r.status_code}: {r.text[:150]}"


def retract_offer(ctx, offer_id):
    """DELETE /api/v2/offers/{id} → retirar oferta propia. 204 = éxito."""
    gw = guarded_write(ctx, "retract_offer", lambda: api("DELETE", f"https://biwenger.as.com/api/v2/offers/{offer_id}", ctx.token,
            ctx.league_id, ctx.user_id))
    if isinstance(gw, tuple):
        return gw
    r = gw
    if r is None:
        return False, "network_error"
    if r.status_code in (200, 201, 204):
        return True, "ok"
    return False, f"http_{r.status_code}: {r.text[:150]}"


def set_lineup(ctx, players_ids, formation, captain_id=None, striker_id=None):
    """PUT /api/v2/user?fields=*%2Clineup(date) con la alineación (y capitán/ariete si están configurados)."""
    lineup = {"type": formation, "playersID": players_ids, "reservesID": []}
    if CAPTAIN_KEY and captain_id:
        lineup[CAPTAIN_KEY] = captain_id
    if STRIKER_KEY and striker_id:
        lineup[STRIKER_KEY] = striker_id
    gw = guarded_write(ctx, "set_lineup", lambda: api("PUT", "https://biwenger.as.com/api/v2/user?fields=*%2Clineup(date)", ctx.token,
            ctx.league_id, ctx.user_id, {"lineup": lineup}))
    if isinstance(gw, tuple):
        return gw[0], gw[1]
    r = gw
    if r is None:
        return False, "network_error"
    if r.status_code == 200:
        return True, r.json()
    return False, f"http_{r.status_code}: {r.text[:200]}"


# ──────────────────────────────────────────────────────────
# Scorer y alineación
# ──────────────────────────────────────────────────────────

def _numeric(f):
    return isinstance(f, (int, float)) and not isinstance(f, bool)


def estimate_p_start(cp, games):
    """
    Probabilidad aproximada de ser titular, a partir de cuántas de las últimas 5 jornadas
    consta puntuación numérica en `fitness` (0 de 5 → 0.2 · 5 de 5 → 1.0).
    Sin datos: 0.6 si aún no ha jugado, 0.7 en caso contrario. Es una heurística.
    """
    last = (cp.get("fitness") or [])[-5:]
    if not last:
        return 0.6 if games == 0 else 0.7
    played = sum(1 for f in last if _numeric(f))
    return round(0.2 + 0.8 * played / len(last), 3)


def home_flag(games_map, team_id):
    cond = (games_map.get(team_id) or {}).get("cond")
    return True if cond == "casa" else False if cond == "fuera" else None


def score_player(cp, diff_rating, p_start=None, is_home=None):
    """
    Puntúa a un jugador (~0-6) para el PRÓXIMO partido:
      0.35·media temporada + 0.35·forma (últimos 5) + 0.90·facilidad del rival,
      × multiplicador de estado × p_start × localía (+5 % casa / −5 % fuera).
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


def get_fixture_info(lineup_players):
    """
    Dificultad y condición del PRÓXIMO partido por equipo (solo el primero de nextGames,
    en orden cronológico si hay fechas). Devuelve (diff_map, games_map, round_name, kickoffs).
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
            "id": pid, "name": cp.get("name", f"id={pid}"), "position": cp.get("position", 0),
            "altPositions": cp.get("altPositions") or [], "team_id": tid, "score": s, "why": why,
            "status": cp.get("status"), "p_start": ps, "price": cp.get("price", 0) or 0,
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
        cand = {"formation": name, "ids": [gk["id"]] + [e["id"] for e in dfs + mds + fws],
                "total": round(total, 3), "gk": [gk], "def": dfs, "mid": mds, "fwd": fws}
        if best is None or cand["total"] > best["total"]:
            best = cand
    if best is None:
        return None, None, None, pool
    return best["ids"], best["formation"], best, pool


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


# ──────────────────────────────────────────────────────────
# Contexto de la ejecución
# ──────────────────────────────────────────────────────────

class Ctx:
    def __init__(self):
        self.token = None
        self.league_id = 0
        self.user_id = 0
        self.balance = 0
        self.points = 0
        self.user_name = "?"
        self.squad_ids = []
        self.lineup_info = {}
        self.lineup_ids = []
        self.catalog = {}
        self.diff_map = {}
        self.games_map = {}
        self.round_name = None
        self.match_soon = True
        self.hours_to_kickoff = None
        self.next_kickoff = None
        self.offers = []
        self.free_market = []
        self.my_sale_ids = set()
        self.pending_ids = set()
        self.committed = 0
        self.pool = {}
        self.opt_ids = []
        self.opt_type = None
        self.opt_detail = None
        self.actions = []
        self.write_count = 0
        self.session = None
        self.rate_limited = False
        self.read_only = False
        self.dry_run = DRY_RUN
        self.wait_budget = WAIT_BUDGET_SECONDS
        self.waited = 0
        self.abort = False
        self.captain_id = None
        self.striker_id = None

    def can_write(self):
        return self.write_count < MAX_WRITES

    def act(self, kind, **details):
        self.actions.append({"type": kind, **details})

    def recompute(self):
        ids, ftype, detail, pool = build_smart_lineup(
            self.squad_ids, self.catalog, self.diff_map, self.games_map)
        self.opt_ids, self.opt_type, self.opt_detail, self.pool = ids or [], ftype, detail, pool

    def cushion(self):
        team_value = sum((self.catalog.get(str(pid)) or {}).get("price", 0) or 0 for pid in self.squad_ids)
        return max(team_value * CUSHION_PCT, CUSHION_MIN)


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
            "id": pid, "name": cp.get("name", f"id={pid}"), "position": cp.get("position", 0),
            "price": s.get("price") or cp.get("price") or 0,
            "status": (cp.get("status") or "ok").lower(),
            "score": sc, "why": why, "p_start": ps, "team_id": tid,
        })
    return result


# ──────────────────────────────────────────────────────────
# Etapas
# ──────────────────────────────────────────────────────────

def stage_cleanup_offers(ctx):
    if getattr(ctx, "abort", False):
        return
    """Retira ofertas propias de jugadores no disponibles y las que sobrepasan el saldo."""
    own = [o for o in ctx.offers
           if o.get("status") == "waiting" and (o.get("from") or {}).get("id") == ctx.user_id]
    ctx.pending_ids = {pid for o in own for pid in offer_player_ids(o)}
    scores = {r["id"]: r["score"] for r in ctx.free_market}
    keep = []
    for o in own:
        pids = offer_player_ids(o)
        pid = pids[0] if pids else None
        cp = ctx.catalog.get(str(pid)) if pid else None
        st = ((cp or {}).get("status") or "ok").lower()
        if st in BAD_STATUS and ctx.can_write():
            ok, msg = retract_offer(ctx, o.get("id"))
            print(f"  ↩️ Retiro oferta #{o.get('id')} por {(cp or {}).get('name', pid)} ({st}): {msg}")
            if ok:
                ctx.write_count += 1
                ctx.pending_ids.discard(pid)
                ctx.act("offer_retracted", offer_id=o.get("id"), player_id=pid, reason=st)
                log_action("offer_retracted", {"offer_id": o.get("id"), "player_id": pid, "reason": st}, "success")
                continue
        keep.append(o)

    committed = sum(o.get("amount", 0) or 0 for o in keep)
    limit = ctx.balance - ctx.cushion()
    if committed > limit:
        keep.sort(key=lambda o: scores.get((offer_player_ids(o) or [0])[0], 0))
        while keep and committed > limit and ctx.can_write():
            o = keep[0]
            ok, msg = retract_offer(ctx, o.get("id"))
            if not ok:
                break
            keep.pop(0)
            committed -= o.get("amount", 0) or 0
            ctx.write_count += 1
            for pid in offer_player_ids(o):
                ctx.pending_ids.discard(pid)
            print(f"  ↩️ Retiro oferta #{o.get('id')}: comprometido por encima del saldo disponible")
            ctx.act("offer_retracted", offer_id=o.get("id"), reason="over_committed")
            log_action("offer_retracted", {"offer_id": o.get("id"), "reason": "over_committed"}, "success")
    ctx.committed = committed


def stage_received_offers(ctx):
    if getattr(ctx, "abort", False):
        return
    """Acepta/rechaza ofertas recibidas simulando antes la plantilla resultante."""
    print("\n  0. Ofertas recibidas:")
    received = [o for o in ctx.offers
                if o.get("status") == "waiting"
                and (o.get("to") or {}).get("id") == ctx.user_id
                and (o.get("from") or {}).get("id") != ctx.user_id]
    if not received:
        print("     ✅ No hay ofertas recibidas")
        return
    sold = set()
    for o in received:
        if not ctx.can_write():
            print("     ⚠️ Límite de escrituras alcanzado")
            break
        oid, amount = o.get("id"), o.get("amount", 0) or 0
        pids = offer_player_ids(o)
        otype = (o.get("type") or "purchase").lower()
        if len(pids) != 1 or otype != "purchase" or o.get("offeredPlayers"):
            log_action("offer_skipped_complex", {"offer_id": oid, "type": otype, "players": pids}, "info")
            print(f"     ⏸ Oferta #{oid} compleja (tipo={otype}, jugadores={len(pids)}) — no se toca")
            continue
        pid = pids[0]
        if pid in sold:
            continue
        cp = ctx.catalog.get(str(pid))
        if not cp:
            print(f"     ⚠️ Oferta #{oid}: jugador id={pid} no está en el catálogo")
            continue
        name = cp.get("name", f"id={pid}")
        market_price = cp.get("price", 0) or 0
        if market_price <= 0:
            print(f"     ⚠️ Oferta #{oid} por {name}: sin precio de mercado, no se evalúa")
            continue
        ratio = amount / market_price
        st = (cp.get("status") or "ok").lower()
        injured = st in BAD_STATUS
        who = "📱 Computer" if abs(ratio - 1) <= 0.05 and (o.get("from") or {}).get("id") is None else "👤 Usuario"
        print(f"     {who} #{oid} por {name} — €{amount:,} (ratio={ratio*100:.1f}%)")

        # Simulación: plantilla sin ese jugador
        after = [i for i in ctx.squad_ids if i != pid]
        ids_a, _, detail_a, _ = build_smart_lineup(after, ctx.catalog, ctx.diff_map, ctx.games_map)
        valid_after = ids_a is not None and len(ids_a) == 11
        total_b = ctx.opt_detail["total"] if ctx.opt_detail else 0.0
        total_a = detail_a["total"] if detail_a else 0.0
        drop = (total_b - total_a) / total_b if total_b > 0 else 0.0
        entry = ctx.pool.get(pid) or {"score": 0, "position": cp.get("position", 0)}
        replacement_market = any(
            r["position"] == entry["position"] and r["status"] == "ok"
            and r["score"] >= entry["score"] and r["p_start"] >= MIN_P_START_BUY
            for r in ctx.free_market)
        has_replacement = (valid_after and drop <= MAX_DROP_PCT) or (valid_after and replacement_market)

        accept, reason = False, ""
        if not valid_after:
            reason = "dejaría posiciones sin cubrir"
        elif ratio >= ACCEPT_HIGH:
            accept, reason = True, f"oferta ≥ {ACCEPT_HIGH*100:.0f}% del mercado"
        elif ratio >= ACCEPT_NORMAL and has_replacement:
            accept, reason = True, f"oferta ≥ {ACCEPT_NORMAL*100:.0f}% y hay reemplazo (caída {drop*100:.1f}%)"
        elif injured and ratio >= ACCEPT_INJURED:
            accept, reason = True, f"{st} y oferta ≥ {ACCEPT_INJURED*100:.0f}%"
        elif (ratio >= ACCEPT_MACHINE_MIN and pid in ctx.my_sale_ids
              and pid not in ctx.opt_ids and entry.get("score", 99) < SELL_SCORE_MIN):
            # Desbloqueo de cupo: jugador de banquillo ya puesto en venta y de valor
            # bajo. Completar la venta libera un hueco de plantilla y da caja.
            accept, reason = True, (f"desbloqueo de cupo: en venta, score {entry.get('score', 0):.2f} "
                                    f"y oferta ≥ {ACCEPT_MACHINE_MIN*100:.0f}% del mercado")
        else:
            applicable = ACCEPT_INJURED if injured else (ACCEPT_NORMAL if has_replacement else ACCEPT_MACHINE_MIN)
            reason = (f"ratio {ratio*100:.1f}% insuficiente (mínimo aplicable {applicable*100:.0f}%) "
                      f"o sin reemplazo")

        if accept:
            ok, msg = answer_offer(ctx, oid, "accepted")
            if ok:
                print(f"       ✅ Aceptada — {reason}")
                ctx.write_count += 1
                ctx.act("offer_accepted", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_accepted", {"offer_id": oid, "player_id": pid, "player_name": name,
                                              "amount": amount, "reason": reason}, "success")
                sold.add(pid)
                ctx.squad_ids = after
                ctx.my_sale_ids.discard(pid)
                ctx.balance += amount
                ctx.recompute()
            else:
                print(f"       ❌ Error aceptando: {msg}")
                log_action("offer_accept_failed", {"offer_id": oid, "reason": msg}, "error")
        else:
            ok, msg = answer_offer(ctx, oid, "rejected")
            if ok:
                print(f"       ❌ Rechazada — {reason}")
                ctx.write_count += 1
                ctx.act("offer_rejected", offer_id=oid, player_id=pid, player_name=name, amount=amount)
                log_action("offer_rejected", {"offer_id": oid, "player_id": pid, "player_name": name,
                                              "amount": amount, "reason": reason}, "success")
            else:
                print(f"       ❌ Error rechazando: {msg}")
                log_action("offer_reject_failed", {"offer_id": oid, "reason": msg}, "error")


def stage_sell_bench(ctx):
    if getattr(ctx, "abort", False):
        return
    """Vende suplentes lesionados o de score bajo solo si hay mejor reemplazo en el mercado."""
    print("\n  1. Ventas de suplentes:")
    starters = set(ctx.opt_ids)
    sold = 0
    for e in sorted(ctx.pool.values(), key=lambda x: x["score"]):
        if e["id"] in starters or e["id"] in ctx.my_sale_ids:
            continue
        if sold >= MAX_SELLS or not ctx.can_write():
            break
        if len(ctx.squad_ids) - sold <= MIN_SQUAD:
            print(f"     ⏸ Plantilla mínima ({MIN_SQUAD}) — no se vende más")
            break
        st = (e.get("status") or "ok").lower()
        bad, low = st in BAD_STATUS, e["score"] < SELL_SCORE_MIN
        if not (bad or low):
            continue
        if low and not bad and ctx.match_soon:
            # Opción B: si la alineación ya está cerrada (11 titulares listos),
            # los suplentes no aportan puntos y no hay riesgo de quedarse corto.
            lineup_ready = len(ctx.opt_ids) >= 11
            if lineup_ready and SELL_BENCH_WHEN_LINEUP_READY:
                print(f"     🔓 {e['name']} (score={e['score']:.3f}) — alineación cerrada, se vende")
            else:
                print(f"     ⏸ {e['name']} (score={e['score']:.3f}) — partido cerca y alineación "
                      f"sin cerrar ({len(ctx.opt_ids)}/11), se mantiene")
                continue
        has_repl = any(r["position"] == e["position"] and r["status"] == "ok"
                       and r["score"] > e["score"] and r["p_start"] >= MIN_P_START_BUY
                       for r in ctx.free_market)
        if not has_repl:
            print(f"     ⏸ {e['name']} ({st}, score={e['score']:.3f}) — sin mejor reemplazo en el mercado")
            continue
        price = ctx.catalog.get(str(e["id"]), {}).get("price", 0)
        reason = f"status={st}" if bad else f"score_bajo={e['score']:.3f}"
        ok, msg, used = sell_player(ctx, e["id"], max(price, 1))
        if ok:
            print(f"     ✅ {e['name']} en venta a €{used:,} ({reason})")
            ctx.write_count += 1
            sold += 1
            ctx.my_sale_ids.add(e["id"])
            ctx.act("sell_sub", player_id=e["id"], player_name=e["name"], price=used)
            log_action("sell_sub", {"player_id": e["id"], "player_name": e["name"],
                                    "reason": reason, "price": used}, "success")
        else:
            print(f"     ❌ {e['name']}: {msg}")
            ctx.act("sell_sub_failed", player_id=e["id"], reason=msg)
            log_action("sell_sub_failed", {"player_id": e["id"], "player_name": e["name"], "reason": msg}, "error")
    if sold == 0:
        print("     ✅ Nada que vender ahora")


def stage_buy(ctx):
    if getattr(ctx, "abort", False):
        return
    """Pujas dinámicas por jugadores del mercado libre que mejoren a los titulares."""
    print("\n  2. Compras:")
    if ctx.balance < 0:
        print("     🚨 Saldo negativo: no se compra (el saldo negativo resta puntos)")
        log_action("balance_negative", {"balance": ctx.balance}, "warning")
        return
    if MAX_SQUAD and len(ctx.squad_ids) >= MAX_SQUAD:
        print(f"     ⏸ Plantilla completa ({MAX_SQUAD})")
        return
    # El cupo de la liga cuenta jugadores + ofertas abiertas. Si ya está al máximo
    # la API responde 403 "Maximum team size reached": es mejor no gastar la
    # petición y explicar por qué no se puja.
    own_open = {pid for o in ctx.offers
                if o.get("status") == "waiting" and (o.get("from") or {}).get("id") == ctx.user_id
                for pid in offer_player_ids(o)}
    occupied = len(ctx.squad_ids) + len(own_open)
    if occupied >= MAX_TEAM_SIZE:
        on_sale = len(ctx.my_sale_ids)
        print(f"     ⏸ Cupo de liga completo ({occupied}/{MAX_TEAM_SIZE}): "
              f"{len(ctx.squad_ids)} jugadores ({len(ctx.squad_ids)-on_sale} libres + "
              f"{on_sale} en venta) + {len(own_open)} ofertas abiertas")
        print(f"        Solo se libera cupo al COMPLETAR una venta: se aceptan las ofertas")
        print(f"        de la máquina (≥{ACCEPT_MACHINE_MIN*100:.0f}%) sobre suplentes en venta.")
        log_action("buy_check", {"result": "team_full", "occupied": occupied,
                                 "max": MAX_TEAM_SIZE, "on_sale": on_sale}, "info")
        return

    worst = {}
    if ctx.opt_detail:
        for key in ("gk", "def", "mid", "fwd"):
            for e in ctx.opt_detail[key]:
                worst[e["position"]] = min(worst.get(e["position"], 99), e["score"])

    cands = [r for r in ctx.free_market if r["status"] == "ok" and r["id"] not in ctx.pending_ids
             and r["id"] not in ctx.squad_ids and r["p_start"] >= MIN_P_START_BUY]
    cands.sort(key=lambda r: r["score"], reverse=True)
    print(f"     Mercado libre evaluado: {len(ctx.free_market)} · candidatos: {len(cands)}")
    for r in cands[:5]:
        print(f"       {r['name']:22} {POS_NAMES.get(r['position'], '?'):3} score={r['score']:6.3f} €{r['price']:,}")

    upgrades = []
    for r in cands:
        w = worst.get(r["position"])
        if w is None:
            continue
        if r["score"] > w * (1 + BUY_MARGIN) and r["price"] <= ctx.balance:
            upgrades.append({**r, "peor_titular": w, "gain": r["score"] - w})
    upgrades.sort(key=lambda r: r["gain"], reverse=True)
    if not upgrades:
        print("     ✅ Ningún jugador del mercado mejora a los titulares")
        log_action("buy_check", {"result": "no_upgrade_available", "evaluados": len(cands)}, "info")
        return

    available = ctx.balance - ctx.committed - ctx.cushion()
    print(f"     💰 Saldo €{ctx.balance:,} · comprometido €{ctx.committed:,} · "
          f"colchón €{ctx.cushion():,.0f} · disponible €{available:,.0f}")

    bought, bought_pos = 0, set()
    for p in upgrades:
        if bought >= MAX_BUYS or not ctx.can_write():
            break
        if p["position"] in bought_pos:
            continue
        pid, price = p["id"], p["price"]
        trend = (ctx.catalog.get(str(pid)) or {}).get("priceIncrement") or 0
        if p["score"] > 5.0 and price > 3_000_000:
            competition = "alta"
        elif p["score"] > 3.5 or (trend > 0 and p["score"] > 3.0):
            competition = "media"
        else:
            competition = "baja"
        mult = {"baja": BID_LOW, "media": BID_MID, "alta": BID_HIGH}[competition]
        max_bid = int(price * MAX_BID_PCT)
        bid = min(int(price * mult), max_bid)
        if BID_PLUS_ONE:
            bid = min(bid + 1, max_bid + 1)
        print(f"     → {p['name']} ({POS_NAMES.get(p['position'], '?')}) mercado €{price:,} · "
              f"score {p['score']} vs peor titular {p['peor_titular']:.3f} · "
              f"competencia {competition} · puja €{bid:,}")
        if bid > available:
            print(f"       ⚠️ Excede el saldo disponible — se omite")
            continue
        ok, offer_id, status = create_purchase_offer(ctx, pid, bid)
        if ok:
            print(f"       ✅ Oferta creada ID={offer_id} ({status})")
            ctx.write_count += 1
            bought += 1
            bought_pos.add(p["position"])
            available -= bid
            ctx.committed += bid
            ctx.pending_ids.add(pid)
            ctx.offers.append({"id": offer_id, "type": "purchase", "status": "waiting",
                                "amount": bid, "from": {"id": ctx.user_id},
                                "requestedPlayers": [{"id": pid}]})
            ctx.act("buy_offer_created", player_id=pid, player_name=p["name"], amount=bid, offer_id=offer_id)
            log_action("buy_offer_created", {"player_id": pid, "player_name": p["name"], "amount": bid,
                                             "offer_id": offer_id, "score": p["score"],
                                             "peor_titular": p["peor_titular"], "competition": competition},
                       "success")
        else:
            print(f"       ❌ {status}")
            ctx.act("buy_failed", player_id=pid, reason=status)
            log_action("buy_offer_failed", {"player_id": pid, "player_name": p["name"], "reason": status}, "error")


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


def stage_lineup(ctx):
    if getattr(ctx, "abort", False):
        return
    print("\n  3. Alineación:")
    ok_lineup, why = lineup_is_complete(ctx)
    if not ok_lineup:
        print(f"     🔒 Alineación bloqueada: {why}")
        ctx.act("lineup_blocked", reason=why)
        log_action("lineup_blocked", {"reason": why}, "warning")
        return

    if CAPTAIN_KEY or STRIKER_KEY:
        ctx.captain_id, ctx.striker_id = choose_captain_and_striker(ctx.opt_detail)
        nm = lambda i: (ctx.pool.get(i) or {}).get("name", i)
        print(f"     Capitán: {nm(ctx.captain_id)} · Ariete: {nm(ctx.striker_id)}")

    current_total = round(sum(e["score"] for e in ctx.pool.values() if e["id"] in ctx.lineup_ids), 3)
    best_total = ctx.opt_detail["total"]
    gain = best_total - current_total
    gain_pct = (gain / current_total * 100) if current_total > 0 else 100.0
    unavailable = [i for i in ctx.lineup_ids
                   if i not in ctx.pool or (ctx.pool[i]["status"] or "ok").lower() in BAD_STATUS]
    same = ctx.opt_ids == ctx.lineup_ids
    extras = bool(CAPTAIN_KEY or STRIKER_KEY)

    if not same and (gain_pct >= MIN_LINEUP_GAIN * 100 or unavailable):
        why_set = "titular no disponible" if unavailable and gain_pct < MIN_LINEUP_GAIN * 100 else f"{gain_pct:+.1f}%"
        print(f"     Mejora {current_total} → {best_total} ({why_set}). Cambiando a {ctx.opt_type}")
    elif extras and ctx.captain_id:
        print("     Alineación igual de buena; se reenvía para fijar capitán/ariete")
    else:
        reason = "already_optimal" if same else "gain_below_threshold"
        print(f"     ⏸ Sin cambios ({reason}, {gain_pct:+.1f}%)")
        ctx.act("lineup_skipped", reason=reason, gain_pct=round(gain_pct, 2))
        log_action("lineup_skipped", {"reason": reason, "gain_pct": round(gain_pct, 2),
                                      "current": current_total, "best": best_total}, "info")
        return

    if not ctx.can_write():
        print("     ⚠️ Límite de escrituras alcanzado — la alineación NO se cambió")
        log_action("lineup_not_set_write_limit", {"writes": ctx.write_count}, "warning")
        return
    ok, resp = set_lineup(ctx, ctx.opt_ids, ctx.opt_type, ctx.captain_id, ctx.striker_id)
    if ok:
        out_ids = [i for i in ctx.lineup_ids if i not in ctx.opt_ids]
        in_ids = [i for i in ctx.opt_ids if i not in ctx.lineup_ids]
        out_names = [ctx.pool.get(i, {}).get("name", str(i)) for i in out_ids]
        in_names = [ctx.pool.get(i, {}).get("name", str(i)) for i in in_ids]
        diff_txt = ""
        if out_names or in_names:
            diff_txt = " | Salen: " + ", ".join(out_names) if out_names else ""
            if in_names:
                diff_txt += " | Entran: " + ", ".join(in_names)
        print(f"     ✅ Alineación actualizada a {ctx.opt_type}{diff_txt}")
        ctx.write_count += 1
        ctx.act("lineup_set", formation=ctx.opt_type, players=ctx.opt_ids,
                captain=ctx.captain_id, striker=ctx.striker_id,
                out=out_names, entr=in_names)
        log_action("lineup_set", {"formation": ctx.opt_type, "total": best_total, "gain_pct": round(gain_pct, 2),
                                  "players": ctx.opt_ids, "captain": ctx.captain_id,
                                  "striker": ctx.striker_id, "out": out_names, "in": in_names}, "success")
    else:
        print(f"     ❌ Error alineación: {resp}")
        ctx.act("lineup_failed", reason=str(resp))
        log_action("lineup_failed", {"reason": str(resp), "formation": ctx.opt_type}, "error")


# ──────────────────────────────────────────────────────────
# Probe, state y todo
# ──────────────────────────────────────────────────────────

def probe(ctx):
    """Vuelca los campos reales de lineup para descubrir cómo guarda Biwenger capitán/ariete."""
    r = api("GET", "https://biwenger.as.com/api/v2/user?fields=*,lineup(*)",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        print(f"❌ Probe falló: {None if r is None else r.status_code}")
        return
    data = r.json().get("data", {})
    lineup = data.get("lineup") or {}
    with open(PROBE_FILE, "w", encoding="utf-8") as f:
        json.dump({"user_keys": sorted(data.keys()), "lineup": lineup}, f, indent=2, ensure_ascii=False)
    print(f"Claves de user:   {sorted(data.keys())}")
    print(f"Claves de lineup: {sorted(lineup.keys())}")
    print(f"Volcado completo en {PROBE_FILE}")
    print("Busca ahí el campo del capitán/ariete y ponlo en BIWENGER_CAPTAIN_KEY / BIWENGER_STRIKER_KEY.")


def save_outputs(ctx, now):
    state = {
        "date": now.isoformat(),
        "dry_run": DRY_RUN,
        "points": ctx.points,
        "balance": ctx.balance,
        "league_id": ctx.league_id,
        "user_id": ctx.user_id,
        "formation": ctx.opt_type,
        "current_lineup_ids": list(ctx.lineup_ids),
        "optimal_lineup_ids": ctx.opt_ids,
        "lineup_scores": {e["name"]: e["score"] for e in ctx.pool.values()},
        "lineup_total": ctx.opt_detail["total"] if ctx.opt_detail else None,
        "captain": ctx.captain_id,
        "striker": ctx.striker_id,
        "round": ctx.round_name,
        "next_kickoff": ctx.next_kickoff.isoformat() if ctx.next_kickoff else None,
        "hours_to_kickoff": ctx.hours_to_kickoff,
        "match_soon": ctx.match_soon,
        "rate_limited": ctx.rate_limited,
        "peticiones_usadas": REQ["count"],
        "writes": ctx.write_count,
        "actions": ctx.actions,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)

    todo = [
        "# Biwenger Auto-Trader v12",
        f"**Liga:** {ctx.league_id} · **Usuario:** {ctx.user_name} (ID {ctx.user_id}) · **Saldo:** €{ctx.balance:,}",
        f"**Puntos:** {ctx.points} · **Ejecución:** {now:%Y-%m-%d %H:%M}" + (" · DRY-RUN" if DRY_RUN else ""),
        "", "## Acciones",
    ]
    labels = {
        "offer_accepted": "✅ Oferta aceptada: {player_name} (€{amount:,})",
        "offer_rejected": "❌ Oferta rechazada: {player_name} (€{amount:,})",
        "offer_retracted": "↩️ Oferta propia retirada #{offer_id}",
        "sell_sub": "✅ En venta: {player_name} (€{price:,})",
        "buy_offer_created": "🔵 Puja por {player_name}: €{amount:,}",
        "lineup_set": "✅ Alineación: {formation}",
        "lineup_blocked": "🔒 Alineación bloqueada: {reason}",
        "lineup_skipped": "⏸ Alineación sin cambios ({reason})",
    }
    for a in ctx.actions:
        tpl = labels.get(a["type"])
        try:
            msg = tpl.format(**a) if tpl else f"• {a['type']}: {a}"
            if a["type"] == "lineup_set":
                out = a.get("out") or []
                entr = a.get("entr") or []
                if out or entr:
                    parts = []
                    if out:
                        parts.append("Salen: " + ", ".join(out))
                    if entr:
                        parts.append("Entran: " + ", ".join(entr))
                    msg += " (" + " | ".join(parts) + ")"
            todo.append(msg)
        except (KeyError, ValueError):
            todo.append(f"• {a['type']}")
    if not ctx.actions:
        todo.append("(sin acciones)")
    with open(TODO_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(todo) + "\n")


# ──────────────────────────────────────────────────────────
# Ejecución
# ──────────────────────────────────────────────────────────

def acquire_instance_lock():
    import fcntl, os
    fd = os.open(LOCKFILE_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    return fd


def run(probe_only=False, live=False):
    lock_fd = acquire_instance_lock()
    if lock_fd is None:
        import sys
        print("Otra instancia en ejecución, saliendo", file=sys.stderr)
        sys.exit(0)
    global DRY_RUN
    if live:
        DRY_RUN = False
    now = datetime.now()
    print(f"\n{'=' * 60}\nBiwenger Auto-Trader v{VERSION} — {now:%Y-%m-%d %H:%M}"
          + (" [DRY-RUN]" if DRY_RUN else "") + f"\n{'=' * 60}")

    until = rate_limit_active()
    if until:
        print(f"⏸ Rate limit activo hasta {until:%Y-%m-%d %H:%M}. No se hace nada.")
        return 6
    if START_JITTER_MAX > 0:
        time.sleep(random.uniform(0, START_JITTER_MAX))

    ctx = Ctx()
    ctx.dry_run = DRY_RUN
    if os.path.exists(UNKNOWN_STATE_PATH):
        ctx.read_only = True
        print("MODO LECTURA: unknown_state presente, no se escribirá")
    print("Modo:", "LIVE" if not DRY_RUN else "DRY-RUN")
    ctx.session = requests.Session()
    set_session(ctx.session)
    set_wait_budget(ctx.wait_budget)
    set_ctx(ctx)
    try:
        ctx.token = TOKEN or login()
        print("✅ Autenticado")
        (ctx.league_id, ctx.user_id, ctx.balance, ctx.points, ctx.user_name) = get_account(ctx.token)
        print(f"\n--- Account ---\n  {ctx.user_name} | {ctx.points} pts | €{ctx.balance:,} | liga {ctx.league_id}")

        if probe_only:
            probe(ctx)
            return 0

        # Datos
        squad_ids, lineup_info, lineup_players = get_squad(ctx)
        if lineup_info is None:
            print("❌ No se pudo obtener la plantilla")
            return 1
        ctx.squad_ids, ctx.lineup_info = squad_ids, lineup_info
        ctx.lineup_ids = lineup_info.get("playersID") or []
        print(f"  Plantilla: {len(ctx.squad_ids)} jugadores · formación actual {lineup_info.get('type', '?')}")

        ctx.catalog, cat_teams = get_catalog(ctx)
        print(f"  Catálogo: {len(ctx.catalog)} jugadores · {len(cat_teams)} equipos")
        if not ctx.catalog:
            print("❌ Sin catálogo: no se actúa")
            log_action("no_catalog", {}, "error")
            return 1

        ctx.diff_map, ctx.games_map, ctx.round_name, kickoffs = get_fixture_info(lineup_players)
        ctx.round_name = ctx.round_name or get_round_name(ctx)
        future = [d for d in kickoffs.values() if d >= now - timedelta(hours=3)]
        if future:
            ctx.next_kickoff = min(future)
            ctx.hours_to_kickoff = round((ctx.next_kickoff - now).total_seconds() / 3600, 1)
            ctx.match_soon = ctx.hours_to_kickoff <= MATCH_SOON_HOURS
            print(f"  Próximo partido: {ctx.next_kickoff:%a %d/%m %H:%M} (en {ctx.hours_to_kickoff} h) "
                  f"· {ctx.round_name or ''}")
        else:
            ctx.match_soon = True  # sin fechas: conservador
            print("  ⚠️ Sin fechas de partidos: se asume partido cercano (no se vende por score bajo)")
            log_action("no_kickoff_dates", {}, "warning")
        print(f"  Dificultad conocida para {len(ctx.diff_map)} equipos")

        ctx.offers = get_offers(ctx)
        free_sales, own_sales = get_market(ctx)
        ctx.my_sale_ids = {(s.get("player") or {}).get("id") for s in own_sales}
        ctx.free_market = build_free_market(ctx, free_sales)
        print(f"  Mercado: {len(free_sales)} libres · {len(own_sales)} propias · "
              f"{len(ctx.offers)} ofertas en total")

        ctx.recompute()
        if not ctx.opt_ids:
            print("⚠️ No hay combinación válida de alineación (¿sin porteros?)")
            log_action("lineup_eval", {"result": "no_valid_lineup"}, "warning")
        else:
            print(f"\n--- Plantilla puntuada ({len(ctx.pool)}) ---")
            for e in sorted(ctx.pool.values(), key=lambda x: x["score"], reverse=True):
                gm = ctx.games_map.get(e["team_id"], {})
                print(f"  {e['name']:20} {POS_NAMES.get(e['position'], '?'):3} score={e['score']:6.3f} "
                      f"vs {gm.get('rival', '?')} ({gm.get('cond', '?')}) · {e['why']}")
            print(f"\n  Mejor alineación: {ctx.opt_type} (total={ctx.opt_detail['total']})")
            log_action("lineup_eval", {"formation": ctx.opt_type, "total": ctx.opt_detail["total"]}, "info")

        # Acciones
        print("\n--- Acciones ---")
        stage_cleanup_offers(ctx)
        stage_received_offers(ctx)
        ctx.recompute()
        stage_sell_bench(ctx)
        stage_buy(ctx)
        stage_lineup(ctx)

    except RateLimited as e:
        ctx.rate_limited = True
        until = set_rate_limit()
        print(f"\n🚫 429 (rate limit) en {e}. Pausa hasta {until:%Y-%m-%d %H:%M}")
        log_action("rate_limited", {"until": until.isoformat()}, "error")
        save_outputs(ctx, now)
        return 6
    except OldVersion:
        print("\n❌ 'Old version': sube BIWENGER_VERSION (DevTools → Network → cabecera x-version)")
        log_action("old_version", {"x_version": APP_VERSION}, "error")
        return 5
    except AuthError:
        print("\n❌ 401: token o credenciales inválidos")
        log_action("auth_error", {}, "error")
        return 3

    save_outputs(ctx, now)
    print(f"\n  ✅ State: {STATE_FILE}\n  ✅ Todo:  {TODO_FILE}")
    print(f"\n{'=' * 60}\n✅ Ejecución completada — {len(ctx.actions)} acciones, "
          f"{ctx.write_count} writes, {REQ['count']} peticiones\n{'=' * 60}")
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        DRY_RUN = True
    if args.live:
        DRY_RUN = False
    try:
        sys.exit(run(probe_only=args.probe, live=args.live))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR FATAL: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


# CHANGELOG v12 → v13
# - FIX: desbloqueo de cupo. La liga cuenta jugadores + ofertas abiertas (16).
#   Con la cuenta a 16/16 toda compra devolvía 403 "Maximum team size reached"
#   (34 veces acumuladas en el log). La causa: las ventas abiertas nunca se
#   completaban porque las ofertas de la máquina (95-102% del mercado) se
#   rechazaban con el umbral del 110%, y sin venta completada el cupo no baja.
# - NUEVO: ACCEPT_MACHINE_MIN (0.92). Una oferta de la máquina sobre un jugador
#   de banquillo YA en venta y con score bajo (<2.0) se acepta para completar
#   la venta y liberar cupo. No aplica a titulares ni a jugadores de valor.
# - MEJORA: stage_buy comprueba el cupo ANTES de pujar y explica el motivo
#   (antes gastaba la petición y devolvía un 403 sin contexto).

# CHANGELOG v11 → v12
# - FIX CRÍTICO: get_offers() usaba GET /api/v2/offers sin filtro → las ofertas waiting
#   no aparecían (la API solo las devuelve con ?status=waiting). El script rechazaba
#   ofertas que nunca vio y las quedaban pendientes en la web.
# - FIX: stage_received_offers ahora recibe SOLO ofertas waiting → procesa todas.
# - MEJORA: log diferenciado entre ofertas vistas y ofertas rechazadas por la API.

# CHANGELOG v10 → v11
# - MEJORA: README completamente renovado con documentación completa.
# - MEJORA: Variables de entorno documentadas en tablas con valores por defecto.
# - MEJORA: Sección de seguridad y estructura del proyecto en README.
# - FIX: Sincronización de script local con repo GitHub.

# CHANGELOG v9 → v10
# - FIX: NameError `threshold` al rechazar ofertas (cortaba la ejecución).
# - FIX: `offers_data` sin definir en el control de saldo → ofertas leídas una sola vez (1 petición menos).
# - FIX: p_start y localía ahora se calculan y se aplican (antes siempre 1.0 / neutro).
# - FIX: la dificultad del rival se leía del ÚLTIMO partido de nextGames; ahora del PRÓXIMO.
# - FIX: "partido cerca" siempre era verdadero; ahora usa fechas reales (respaldo conservador sin fechas).
# - FIX: has_replacement usaba un score inexistente; el mercado libre se puntúa antes de evaluar ofertas.
# - FIX: la alineación se aplicaba aunque faltaran posiciones; ahora se bloquea de verdad.
# - FIX: ofertas recibidas de otros usuarios (from.id ≠ null) se ignoraban; ahora se leen todas las dirigidas a ti.
# - MEJORA: simulación de plantilla antes de aceptar una oferta; retirada de ofertas obsoletas o sobre-comprometidas.
# - MEJORA: X-Version y todos los umbrales por variables de entorno; .env integrado; --dry-run y --probe.
# - MEJORA: manejo central de 429 (pausa de 4 h con fichero), 401 y "Old version".
# - MEJORA: un máximo de 1 compra por posición y ejecución; pujas +1 € contra empates; log con rotación.

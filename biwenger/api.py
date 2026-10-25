"""Biwenger API — HTTP client (api()) and GET endpoints."""
import json as _json
import random
import time

import requests as _requests

from biwenger import config as cfg
from biwenger import model
from biwenger.utils import log_action, get_headers, save_unknown_state


def set_session(s):
    model.set_session(s)


def set_wait_budget(budget):
    model.set_wait_budget(budget)


def _summarize_body(body):
    if body is None:
        return None
    try:
        s = _json.dumps(body)
        return s[:200]
    except Exception:
        return str(body)[:200]


def api(method, url, token=None, league_id=None, user_id=None, body=None):
    """Petición con reintento por red, pausa entre llamadas y errores tipados.
    Usa la Session compartida si existe (creada en run()); si no, requests directo.
    - GET: reintenta ante errores de red con backoff corto (2s/4s/8s, tope 60s).
    - POST/PUT/DELETE: NO reintenta tras timeout/error de lectura (evita duplicar ofertas/ventas);
      solo reintenta ante 429 respetando Retry-After (acotado a 60s).
    - Presupuesto global de espera: si se agota, aborta limpio.
    """
    is_write = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
    max_retries = cfg.MAX_RETRIES if method.upper() == "GET" else 0
    backoff = [2, 4, 8]
    for attempt in range(max_retries + 1):
        model._inc_REQ()
        try:
            session = model._get_SESSION()
            headers = get_headers(token, league_id, user_id)
            if session is not None:
                r = session.request(method, url, headers=headers, json=body, timeout=cfg.REQUEST_TIMEOUT)
            else:
                r = _requests.request(method, url, headers=headers, json=body, timeout=cfg.REQUEST_TIMEOUT)
        except _requests.RequestException as e:
            if is_write and "/auth/login" not in url:
                save_unknown_state({"type": "unknown", "method": method, "url": url,
                                    "payload": _summarize_body(body), "timestamp": __import__("datetime").datetime.now().isoformat()})
            ctx = model._get_CTX()
            if ctx is not None and is_write and "/auth/login" not in url:
                ctx.abort = True
            if (not is_write) and attempt < max_retries:
                sleep = backoff[min(attempt, len(backoff) - 1)]
                waited = model._get_WAITED()
                budget = model._get_WAIT_BUDGET()
                if waited + sleep > budget:
                    log_action("wait_budget_exhausted", {"waited": waited, "budget": budget}, "warning")
                    ctx = model._get_CTX()
                    if ctx is not None:
                        ctx.abort = True
                    return None
                model._add_WAITED(sleep)
                continue
            log_action("network_error", {"method": method, "url": url, "error": str(e)}, "error")
            return None
        if cfg.REQUEST_DELAY > 0:
            time.sleep(random.uniform(0.7, 1.3) * cfg.REQUEST_DELAY)
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            try:
                wait = int(retry_after) if retry_after else int(cfg.RATE_LIMIT_WAIT_HOURS * 3600)
            except (TypeError, ValueError):
                wait = int(cfg.RATE_LIMIT_WAIT_HOURS * 3600)
            if wait > 60:
                log_action("retry_after_too_long", {"wait": wait, "url": url}, "warning")
                ctx = model._get_CTX()
                if ctx is not None:
                    ctx.abort = True
                return None
            wait = min(wait, 60)
            if attempt < (cfg.MAX_RETRIES if is_write else max_retries):
                waited = model._get_WAITED()
                budget = model._get_WAIT_BUDGET()
                if waited + wait > budget:
                    log_action("wait_budget_exhausted", {"waited": waited, "budget": budget}, "warning")
                    return None
                model._add_WAITED(wait)
                continue
            raise model.RateLimited(url)
        if r.status_code == 401:
            raise model.AuthError(url)
        if r.status_code == 400 and "old version" in (r.text or "").lower():
            raise model.OldVersion(url)
        # HTTP 5xx during write → uncertain result, abort and save unknown state
        if is_write and r.status_code >= 500:
            if "/auth/login" not in url:
                save_unknown_state({"type": "unknown", "method": method, "url": url,
                                    "payload": _summarize_body(body), "timestamp": __import__("datetime").datetime.now().isoformat()})
            ctx = model._get_CTX()
            if ctx is not None:
                ctx.abort = True
            log_action("server_error_write", {"method": method, "url": url, "status": r.status_code}, "error")
            return None
        return r
    return None


# ── Alias for AST test (test_ninguna_escritura_fuera_de_guarded_write) ────────
_api_write = api


# ── GET endpoints ────────────────────────────────────────────────────────────

def login():
    """POST /api/v2/auth/login → token Bearer."""
    if not cfg.EMAIL or not cfg.PASSWORD:
        raise ValueError("Faltan BIWENGER_EMAIL / BIWENGER_PASSWORD (o BIWENGER_TOKEN)")
    r = _api_write("POST", "https://biwenger.as.com/api/v2/auth/login",
                   body={"email": cfg.EMAIL, "password": cfg.PASSWORD})
    if r is None or r.status_code != 200:
        raise ValueError(f"Login fallido: {None if r is None else r.status_code}")
    data = r.json()
    token = data.get("token") or (data.get("data") or {}).get("token")
    if not token:
        raise ValueError("Login sin token")
    return token


def get_account(token):
    r = api("GET", "https://biwenger.as.com/api/v2/account", token=token)
    if r is None or r.status_code != 200:
        return None, None, None, None, "?"
    data = r.json().get("data", {})
    leagues = data.get("leagues", [])
    if not leagues:
        return None, None, None, None, "?"
    league = leagues[0]
    user = league.get("user", {})
    league_id = league.get("id")
    user_id = user.get("id")
    balance = user.get("balance", 0)
    points = user.get("points", 0)
    user_name = user.get("name", "?")
    return league_id, user_id, balance, points, user_name


def get_squad(ctx):
    """Plantilla completa + alineación actual + titulares con team.nextGames."""
    r = api("GET", "https://biwenger.as.com/api/v2/user?fields=" + cfg.SQUAD_FIELDS,
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return None, None, None
    data = r.json().get("data", {})
    squad_ids = [p.get("id") for p in data.get("players", []) if isinstance(p, dict) and p.get("id")]
    lineup = data.get("lineup") or {}
    return squad_ids, lineup, lineup.get("players") or []


def get_catalog(ctx):
    """Catálogo de La Liga: posición, estado, puntos, forma, precio, equipo."""
    r = api("GET",
            "https://cf.biwenger.com/api/v2/competitions/la-liga/data?lang=es&score=3",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return {}, {}
    data = r.json().get("data", {})
    return (data.get("players") or {}), (data.get("teams") or {})


def get_round_name(ctx):
    r = api("GET", "https://biwenger.as.com/api/v2/rounds/league",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return None
    return ((r.json().get("data") or {}).get("round") or {}).get("name")


def get_market(ctx):
    """GET /api/v2/market → (ventas libres, ventas propias)."""
    r = api("GET", "https://biwenger.as.com/api/v2/market",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return [], []
    sales = (r.json().get("data") or {}).get("sales", [])
    free_sales = [s for s in sales if s.get("user") is None]
    own_sales = [s for s in sales if (s.get("user") or {}).get("id") == ctx.user_id]
    return free_sales, own_sales


def get_offers(ctx):
    """GET /api/v2/offers?status=waiting → SOLO ofertas pendientes."""
    r = api("GET", "https://biwenger.as.com/api/v2/offers?status=waiting",
            ctx.token, ctx.league_id, ctx.user_id)
    if r is None or r.status_code != 200:
        return []
    data = r.json().get("data")
    return [o for o in data if isinstance(o, dict)] if isinstance(data, list) else []
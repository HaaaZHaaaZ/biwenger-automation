"""Biwenger writes — guarded_write + todas las operaciones de escritura."""
from biwenger import config as cfg
from biwenger import model
from biwenger.utils import log_action
import sys


def _get_api():
    """Obtiene la función api actual desde biwenger_daily (para que los tests puedan parchearla)."""
    m = sys.modules.get("biwenger_daily")
    if m and hasattr(m, "api"):
        return m.api
    # Fallback a la implementación real
    from biwenger.api import api as real_api
    return real_api


def _get_api_write():
    """Obtiene la función _api_write actual desde biwenger_daily."""
    m = sys.modules.get("biwenger_daily")
    if m and hasattr(m, "_api_write"):
        return m._api_write
    from biwenger.api import _api_write as real_api_write
    return real_api_write


def guarded_write(ctx, kind, fn, *args, **kwargs):
    """Punto único de control para toda escritura.
    Comprueba, en orden: ctx.abort, modo dry-run, MAX_WRITES, write_count.
    """
    if getattr(ctx, "abort", False):
        log_action("write_aborted", {"kind": kind, "reason": "abort"}, "warning")
        return False, "aborted"
    if getattr(ctx, "read_only", False):
        log_action("read_only_skip", {"kind": kind}, "info")
        return False, "read_only"
    if getattr(ctx, "dry_run", False):
        log_action("dry_run_skip", {"kind": kind}, "info")
        return False, "dry_run"
    if getattr(ctx, "write_count", 0) >= cfg.MAX_WRITES:
        log_action("write_limit", {"kind": kind, "limit": cfg.MAX_WRITES}, "warning")
        return False, "write_limit"
    ctx.write_count += 1
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log_action("write_error", {"kind": kind, "error": str(e)}, "error")
        return False, "error"


def sell_player(ctx, player_id, price):
    """POST /api/v2/market → poner en venta. 204 = éxito."""
    if not price or price <= 0:
        log_action("sell_skipped", {"player_id": player_id, "reason": "no_market_price"}, "warning")
        print(f"     ⚠️ No se vende id={player_id}: sin precio de mercado fiable")
        return False, "no_market_price", 0
    sell_price = price
    api = _get_api()
    gw = guarded_write(ctx, "sell", lambda: api("POST",
            "https://biwenger.as.com/api/v2/market", ctx.token, ctx.league_id, ctx.user_id,
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
    api = _get_api()
    gw = guarded_write(ctx, "answer_offer", lambda: api("PUT",
            f"https://biwenger.as.com/api/v2/offers/{offer_id}", ctx.token, ctx.league_id,
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
    api = _get_api()
    gw = guarded_write(ctx, "create_purchase_offer", lambda: api("POST",
            "https://biwenger.as.com/api/v2/offers", ctx.token, ctx.league_id, ctx.user_id,
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
    api = _get_api()
    gw = guarded_write(ctx, "retract_offer", lambda: api("DELETE",
            f"https://biwenger.as.com/api/v2/offers/{offer_id}", ctx.token,
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
    if cfg.CAPTAIN_KEY and captain_id:
        lineup[cfg.CAPTAIN_KEY] = captain_id
    if cfg.STRIKER_KEY and striker_id:
        lineup[cfg.STRIKER_KEY] = striker_id
    api = _get_api()
    gw = guarded_write(ctx, "set_lineup", lambda: api("PUT",
            "https://biwenger.as.com/api/v2/user?fields=*%2Clineup(date)", ctx.token,
            ctx.league_id, ctx.user_id, {"lineup": lineup}))
    if isinstance(gw, tuple):
        return gw[0], gw[1]
    r = gw
    if r is None:
        return False, "network_error"
    if r.status_code == 200:
        return True, r.json()
    return False, f"http_{r.status_code}: {r.text[:200]}"
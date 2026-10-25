"""Biwenger model — Ctx class, exceptions, and module-level globals access."""
import sys
from biwenger.config import DRY_RUN, MAX_WRITES, CUSHION_PCT, CUSHION_MIN


def _bd():
    """Accede al módulo biwenger_daily en tiempo de ejecución (evita import circular).
    Los tests parchean biwenger_daily._CTX, biwenger_daily._SESSION, etc.
    Cuando se ejecuta como script, el módulo se llama __main__.
    """
    m = sys.modules.get("biwenger_daily")
    if m is None:
        m = sys.modules.get("__main__")
    return m


# Module __getattr__ to delegate globals to biwenger_daily (for test compatibility)
def __getattr__(name):
    if name in ("_CTX", "_SESSION", "REQ", "_WAITED", "_WAIT_BUDGET"):
        bd = _bd()
        if bd and hasattr(bd, name):
            return getattr(bd, name)
    raise AttributeError(f"module 'biwenger.model' has no attribute {name!r}")


# ── Excepciones ──────────────────────────────────────────────────────────────

class RateLimited(Exception):
    """HTTP 429."""


class AuthError(Exception):
    """HTTP 401."""


class OldVersion(Exception):
    """HTTP 400 'old version' (X-Version obsoleta)."""


# ── Ctx dataclass ────────────────────────────────────────────────────────────

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
        self.wait_budget = 90
        self.waited = 0
        self.abort = False
        self.captain_id = None
        self.striker_id = None

    def can_write(self):
        return self.write_count < MAX_WRITES

    def act(self, kind, **details):
        self.actions.append({"type": kind, **details})

    def recompute(self):
        """Recalcula alineación óptima a partir del squad actual."""
        from biwenger.scoring import build_smart_lineup
        ids, ftype, detail, pool = build_smart_lineup(
            self.squad_ids, self.catalog, self.diff_map, self.games_map)
        self.opt_ids, self.opt_type, self.opt_detail, self.pool = (
            ids or [], ftype, detail, pool)

    def cushion(self):
        team_value = sum(
            (self.catalog.get(str(pid)) or {}).get("price", 0) or 0
            for pid in self.squad_ids
        )
        return max(team_value * CUSHION_PCT, CUSHION_MIN)


# ── Globals accessed via biwenger_daily module (tests patch these) ───────────

def _get_REQ():
    m = _bd()
    return m.REQ if m and hasattr(m, "REQ") else {"count": 0}


def _get_CTX():
    m = _bd()
    return m._CTX if m and hasattr(m, "_CTX") else None


def _get_SESSION():
    m = _bd()
    return m._SESSION if m and hasattr(m, "_SESSION") else None


def _get_WAITED():
    m = _bd()
    return m._WAITED if m and hasattr(m, "_WAITED") else 0


def _get_WAIT_BUDGET():
    m = _bd()
    return m._WAIT_BUDGET if m and hasattr(m, "_WAIT_BUDGET") else 90


def _set_CTX(ctx):
    m = _bd()
    if m:
        m._CTX = ctx


def _set_SESSION(s):
    m = _bd()
    if m:
        m._SESSION = s


def _set_WAIT_BUDGET(budget):
    m = _bd()
    if m:
        m._WAIT_BUDGET = budget
        m._WAITED = 0


def _inc_REQ():
    m = _bd()
    if m and hasattr(m, "REQ"):
        m.REQ["count"] += 1


def _add_WAITED(seconds):
    m = _bd()
    if m and hasattr(m, "_WAITED"):
        m._WAITED += seconds


def set_ctx(ctx):
    _set_CTX(ctx)


def set_session(s):
    _set_SESSION(s)


def set_wait_budget(budget):
    _set_WAIT_BUDGET(budget)
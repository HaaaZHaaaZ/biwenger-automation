"""Biwenger config — todas las constantes y helpers de entorno."""
import os

VERSION = "14.0"

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
# DATA_DIR and derived paths are NOT defined at module level so that
# __getattr__ can intercept patches made by tests on biwenger_daily.
# They are resolved lazily via __getattr__ below.
try:
    _data_dir = os.environ.get("BIWENGER_DATA_DIR", "/opt/data")
    os.makedirs(_data_dir, exist_ok=True)
    if not os.access(_data_dir, os.W_OK):
        raise OSError("sin permiso de escritura")
except OSError:
    _data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(_data_dir, exist_ok=True)
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

SQUAD_FIELDS = (
    "players(id),"
    "lineup(round,id,type,playersID,reservesID,"
    "players(id,name,position,altPositions,status,fitness,points,price,"
    "team(id,name,slug,nextGames(*))))"
)


# Allow tests to patch path constants via biwenger_daily module
def __getattr__(name):
    """Delegate patched path constants to biwenger_daily module."""
    import sys
    _PATH_CONSTS = ("DATA_DIR", "LOCKFILE_PATH", "UNKNOWN_STATE_PATH",
                    "STATE_FILE", "TODO_FILE", "REPORT_FILE", "LOG_FILE",
                    "LOG_TXT_FILE", "PROBE_FILE", "RATE_FILE")
    if name in _PATH_CONSTS:
        m = sys.modules.get("biwenger_daily")
        if m and hasattr(m, name):
            return getattr(m, name)
        # Fallback: compute from env var if biwenger_daily not yet loaded
        if name == "DATA_DIR":
            return os.environ.get("BIWENGER_DATA_DIR", "/opt/data")
        if name == "LOCKFILE_PATH":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger.lock")
        if name == "UNKNOWN_STATE_PATH":
            return os.path.join(__getattr__("DATA_DIR"), "unknown_state.json")
        if name == "STATE_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_state.json")
        if name == "TODO_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_todo.md")
        if name == "REPORT_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_report.md")
        if name == "LOG_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_log.json")
        if name == "LOG_TXT_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_log.txt")
        if name == "PROBE_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_probe.json")
        if name == "RATE_FILE":
            return os.path.join(__getattr__("DATA_DIR"), "biwenger_ratelimit.json")
    raise AttributeError(f"module 'biwenger.config' has no attribute {name!r}")
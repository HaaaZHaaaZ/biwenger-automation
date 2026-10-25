"""Biwenger utils — logging, header building, unknown-state, lock, rate limit."""
import fcntl
import json as _json
import os
import time

from biwenger import config as cfg
from biwenger import model


# ── Logging ──────────────────────────────────────────────────────────────────

def log_action(action_type, details, status="info"):
    """Registra una acción en el log JSON (rotado) y en el TXT. Escritura atómica + lock."""
    timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"timestamp": timestamp, "action": action_type, "status": status, "details": details}
    try:
        log_file = cfg.LOG_FILE
        log_txt = cfg.LOG_TXT_FILE
        if os.path.dirname(log_file):
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                logs = _json.load(f)
            except (OSError, ValueError):
                logs = []
            logs.append(entry)
            max_entries = cfg.MAX_LOG_ENTRIES
            logs = logs[-max_entries:]
            tmp = log_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as tf:
                _json.dump(logs, tf, indent=2, ensure_ascii=False)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp, log_file)
            fcntl.flock(f, fcntl.LOCK_UN)
        if os.path.exists(log_txt) and os.path.getsize(log_txt) > 2_000_000:
            os.replace(log_txt, log_txt + ".1")
        with open(log_txt, "a", encoding="utf-8") as f:
            f.write("[" + timestamp + "] [" + status.upper() + "] " + action_type + ": " +
                    _json.dumps(details, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
    return entry


# ── Headers ──────────────────────────────────────────────────────────────────

def get_headers(token=None, league_id=None, user_id=None):
    h = {
        "User-Agent": cfg.UA,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "X-Lang": "es",
        "X-Version": cfg.APP_VERSION,
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


# ── Unknown state ────────────────────────────────────────────────────────────

def save_unknown_state(op):
    # Allow tests to patch via biwenger_daily
    import sys
    m = sys.modules.get("biwenger_daily")
    if m and hasattr(m, "save_unknown_state") and m.save_unknown_state is not save_unknown_state:
        try:
            return m.save_unknown_state(op)
        except Exception:
            pass
    try:
        path = cfg.UNKNOWN_STATE_PATH
        data = []
        if os.path.exists(path):
            with open(path) as f:
                data = _json.load(f)
        data.append(op)
        with open(path, "w") as f:
            _json.dump(data, f)
    except Exception as e:
        log_action("unknown_state_save_error", {"error": str(e)}, "error")


def load_unknown_state():
    try:
        path = cfg.UNKNOWN_STATE_PATH
        if os.path.exists(path):
            with open(path) as f:
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
    with open(cfg.UNKNOWN_STATE_PATH, "w") as f:
        _json.dump(ops, f)


# ── Rate limit file ──────────────────────────────────────────────────────────

def rate_limit_active():
    try:
        with open(cfg.RATE_FILE, "r", encoding="utf-8") as f:
            until_str = _json.load(f)["until"]
        from datetime import datetime as _dt
        until = _dt.fromisoformat(until_str)
        now = _dt.now()
        if now < until:
            return until
    except (OSError, ValueError, KeyError):
        pass
    return None


def set_rate_limit():
    from datetime import datetime as _dt, timedelta as _td
    until = _dt.now() + _td(hours=cfg.RATE_LIMIT_WAIT_HOURS)
    try:
        with open(cfg.RATE_FILE, "w", encoding="utf-8") as f:
            _json.dump({"until": until.isoformat()}, f)
    except OSError:
        pass
    return until


# ── Lock ─────────────────────────────────────────────────────────────────────

def acquire_instance_lock():
    lock_path = cfg.LOCKFILE_PATH
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    return fd


def parse_ts(v):
    """Interpreta una fecha (epoch s/ms o ISO) como datetime local sin zona."""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v > 1e11:
                v = v / 1000.0
            return __import__("datetime").datetime.fromtimestamp(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return parse_ts(int(s))
            dt = __import__("datetime").datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
    except (ValueError, OSError, OverflowError):
        return None
    return None
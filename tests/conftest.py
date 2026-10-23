import importlib
import os
import sys
import tempfile

# El módulo crea ficheros al importarse: aislarlo ANTES del import.
_TMP = tempfile.mkdtemp(prefix="biwenger_test_")
os.environ["BIWENGER_DATA_DIR"] = _TMP
os.environ["BIWENGER_REQUEST_DELAY"] = "0"
os.environ["BIWENGER_START_JITTER_MAX"] = "0"
os.environ.pop("BIWENGER_TOKEN", None)
os.environ.pop("BIWENGER_DRY_RUN", None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

bw_module = importlib.import_module("biwenger_daily")


@pytest.fixture
def bw(tmp_path, monkeypatch):
    """Módulo con todas las rutas redirigidas a un directorio temporal por test."""
    m = bw_module
    monkeypatch.setattr(m, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(m, "LOG_FILE", str(tmp_path / "log.json"))
    monkeypatch.setattr(m, "LOG_TXT_FILE", str(tmp_path / "log.txt"))
    monkeypatch.setattr(m, "UNKNOWN_STATE_PATH", str(tmp_path / "unknown_state.json"))
    monkeypatch.setattr(m, "LOCKFILE_PATH", str(tmp_path / "biwenger.lock"))
    monkeypatch.setattr(m, "RATE_FILE", str(tmp_path / "ratelimit.json"))
    monkeypatch.setattr(m, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(m, "TODO_FILE", str(tmp_path / "todo.md"))
    monkeypatch.setattr(m, "START_JITTER_MAX", 0)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    monkeypatch.setattr(m, "_CTX", None)
    monkeypatch.setattr(m, "_SESSION", None, raising=False)
    monkeypatch.setattr(m, "_WAITED", 0)
    return m


@pytest.fixture
def make_ctx(bw):
    def _make(**flags):
        ctx = bw.Ctx()
        ctx.token, ctx.league_id, ctx.user_id = "tok", 1, 2
        ctx.abort = flags.get("abort", False)
        ctx.read_only = flags.get("read_only", False)
        ctx.dry_run = flags.get("dry_run", False)
        ctx.write_count = flags.get("write_count", 0)
        return ctx
    return _make


class FakeResp:
    def __init__(self, status=200, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

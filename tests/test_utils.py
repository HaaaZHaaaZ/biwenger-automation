"""Tests for biwenger.utils — logging, lock, unknown state, rate limit."""
import json
import os
import tempfile
from datetime import datetime


def test_log_action_writes_json(tmp_path):
    from biwenger.utils import log_action
    import biwenger.config as cfg
    cfg.LOG_FILE = str(tmp_path / "log.json")
    log_action("test_action", {"player_id": 1}, "success")
    # Verify file exists and has correct content
    with open(cfg.LOG_FILE) as f:
        entries = json.load(f)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "test_action"
    assert entry["status"] == "success"
    assert entry["details"]["player_id"] == 1


def test_get_headers():
    from biwenger.utils import get_headers
    h = get_headers("tok", 1, 2)
    assert h["Authorization"] == "Bearer tok"
    assert h["X-League"] == "1"
    assert h["X-User"] == "2"
    assert h["X-Version"] == "631"
    assert h["User-Agent"].startswith("Mozilla/5.0")


def test_unknown_state_save_load(tmp_path):
    from biwenger.utils import save_unknown_state, load_unknown_state
    import biwenger.config as cfg
    cfg.UNKNOWN_STATE_PATH = str(tmp_path / "unknown.json")
    save_unknown_state({"type": "sell", "player_id": 10})
    data = load_unknown_state()
    assert len(data) == 1
    assert data[0]["type"] == "sell"


def test_acquire_instance_lock(tmp_path):
    from biwenger.utils import acquire_instance_lock
    import biwenger.config as cfg
    lock_path = str(tmp_path / "test.lock")
    cfg.LOCKFILE_PATH = lock_path
    fd = acquire_instance_lock()
    assert fd is not None
    # Second call should fail
    assert acquire_instance_lock() is None
    os.close(fd)


def test_parse_ts():
    from biwenger.utils import parse_ts
    assert parse_ts(1700000000) is not None
    assert parse_ts("1700000000") is not None
    assert parse_ts("2024-01-15T10:30:00") is not None
    assert parse_ts(None) is None
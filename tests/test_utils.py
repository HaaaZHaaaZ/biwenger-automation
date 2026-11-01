import pytest
import json
import os
import tempfile


def test_log_action_writes_json(monkeypatch, tmp_path):
    """Log action writes to JSON and TXT files."""
    from biwenger.utils import log_action
    import biwenger.config as cfg
    
    # Use in-memory paths
    log_file = tmp_path / "log.json"
    log_txt = tmp_path / "log.txt"
    
    # Mock cfg to use our paths
    monkeypatch.setattr(cfg, 'LOG_FILE', str(log_file))
    monkeypatch.setattr(cfg, 'LOG_TXT_FILE', str(log_txt))
    
    log_action("test_action", {"player_id": 1}, "success")
    
    # Verify JSON file exists and has correct content
    assert log_file.exists()
    with open(log_file) as f:
        data = json.load(f)
    assert isinstance(data, list) and len(data) >= 1
    entry = data[0]
    assert entry["action"] == "test_action"
    assert entry["status"] == "success"
    
    # Verify TXT file exists and has content
    assert log_txt.exists()
    with open(log_txt) as f:
        txt_content = f.read()
    assert "test_action" in txt_content
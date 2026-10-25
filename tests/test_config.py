"""Tests for biwenger.config — constants and env helpers."""
import os

def test_constants_present():
    from biwenger.config import (
        VERSION, BASE_DIR, DATA_DIR, LOG_FILE, LOG_TXT_FILE,
        MAX_WRITES, MAX_BUYS, MAX_SELLS, MIN_SQUAD, MAX_SQUAD,
        STATUS_MULT, FORMATIONS, BAD_STATUS, POS_NAMES, SQUAD_FIELDS,
    )
    from biwenger.version import __version__
    assert VERSION == __version__
    assert isinstance(MAX_WRITES, int) and MAX_WRITES > 0
    assert isinstance(MAX_BUYS, int)
    assert isinstance(MAX_SELLS, int)
    assert isinstance(MIN_SQUAD, int)
    assert STATUS_MULT["ok"] == 1.00
    assert STATUS_MULT["injured"] == 0.00
    assert STATUS_MULT["warned"] == 0.85
    assert "4-4-2" in [f[0] for f in FORMATIONS]
    assert "injured" in BAD_STATUS
    assert POS_NAMES[1] == "GK"
    assert "players(id)," in SQUAD_FIELDS


def test_version_consistency():
    from biwenger.version import __version__
    from biwenger.config import VERSION
    from biwenger import __version__ as pkg_version
    assert VERSION == __version__
    assert pkg_version == __version__
    assert __version__ == "14.0"

def test_env_helpers():
    from biwenger.config import env_str, env_int, env_float, env_bool
    os.environ["BIWENGER_TEST_STR"] = "hello"
    os.environ["BIWENGER_TEST_INT"] = "42"
    os.environ["BIWENGER_TEST_FLOAT"] = "3.14"
    os.environ["BIWENGER_TEST_BOOL"] = "true"
    assert env_str("BIWENGER_TEST_STR") == "hello"
    assert env_int("BIWENGER_TEST_INT", 0) == 42
    assert env_float("BIWENGER_TEST_FLOAT", 0.0) == 3.14
    assert env_bool("BIWENGER_TEST_BOOL", False) is True
    assert env_str("BIWENGER_TEST_MISSING", "def") == "def"
    assert env_int("BIWENGER_TEST_MISSING", 99) == 99
    assert env_bool("BIWENGER_TEST_MISSING", True) is True
import pytest, json, os, tempfile
from pathlib import Path

def test_upsert_and_load():
    """Test feature store upsert and load_training_data."""
    import sys
    test_dir = tempfile.mkdtemp()
    os.environ["BIWENGER_DATA_DIR"] = test_dir
    
    # Force reload of features module to pick up new DATA_DIR
    if "biwenger.features" in sys.modules:
        del sys.modules["biwenger.features"]
    
    from biwenger.features import init_db, upsert_features, load_training_data
    
    init_db()
    rows = [{
        "player_id": 1, "round": 1, "season_avg": 3.2, "fit_avg": 4.1,
        "diff_home": 40, "diff_away": 60, "minutes": 90, "status": "ok",
        "p_start_est": 0.9, "p_start_real": 1.0, "points_real": 5.3, "position": 4
    }]
    upsert_features(rows)
    X, y_pts, y_ps = load_training_data(min_samples=1)
    
    assert X is not None and len(X) == 1
    assert list(X.columns) == ["season_avg", "fit_avg", "diff_avg", "p_start_est", "minutes", "position"]
    assert X.iloc[0]["season_avg"] == 3.2
    assert y_pts.iloc[0] == 5.3

def test_load_returns_none_for_empty_db():
    """Load_training_data returns None when insufficient data."""
    import sys
    test_dir = tempfile.mkdtemp()
    os.environ["BIWENGER_DATA_DIR"] = test_dir
    
    if "biwenger.features" in sys.modules:
        del sys.modules["biwenger.features"]
    
    from biwenger.features import init_db, load_training_data
    init_db()
    
    X, y_pts, y_ps = load_training_data(min_samples=1000)
    assert X is None and y_pts is None and y_ps is None
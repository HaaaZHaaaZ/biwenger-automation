"""Feature store: persiste features y target real por jugador/jornada."""
import sqlite3, json, os
from pathlib import Path
from biwenger.config import DATA_DIR

DB = Path(DATA_DIR) / "biwenger_features.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_features (
    player_id   INTEGER,
    round       INTEGER,
    season_avg  REAL,
    fit_avg     REAL,
    diff_home   REAL,
    diff_away   REAL,
    minutes     INTEGER,
    status      TEXT,
    p_start_est REAL,
    p_start_real REAL,
    points_real REAL,
    position    INTEGER,
    PRIMARY KEY (player_id, round)
);
CREATE INDEX IF NOT EXISTS idx_player_round ON player_features(player_id, round);
"""

def init_db():
    with sqlite3.connect(DB) as con:
        con.executescript(SCHEMA)

def upsert_features(rows: list[dict]):
    """rows = [{player_id, round, season_avg, fit_avg, diff_home, diff_away,
                minutes, status, p_start_est, p_start_real, points_real, position}, ...]"""
    if not rows:
        return
    with sqlite3.connect(DB) as con:
        con.executemany("""
            INSERT INTO player_features VALUES
            (:player_id, :round, :season_avg, :fit_avg, :diff_home, :diff_away,
             :minutes, :status, :p_start_est, :p_start_real, :points_real, :position)
            ON CONFLICT(player_id, round) DO UPDATE SET
                season_avg=excluded.season_avg, fit_avg=excluded.fit_avg,
                diff_home=excluded.diff_home, diff_away=excluded.diff_away,
                minutes=excluded.minutes, status=excluded.status,
                p_start_est=excluded.p_start_est, p_start_real=excluded.p_start_real,
                points_real=excluded.points_real, position=excluded.position
        """, rows)

def load_training_data(min_samples=30):
    """Devuelve X (features), y_points, y_pstart por posición."""
    try:
        import pandas as pd
    except ImportError:
        return None, None, None
    
    if not DB.exists():
        return None, None, None
        
    with sqlite3.connect(DB) as con:
        df = pd.read_sql("SELECT * FROM player_features WHERE points_real IS NOT NULL", con)
    
    if len(df) < min_samples:
        return None, None, None
    
    df["diff_avg"] = (df["diff_home"] + df["diff_away"]) / 2
    feat_cols = ["season_avg", "fit_avg", "diff_avg", "p_start_est", "minutes", "position"]
    X = df[feat_cols]
    y_pts = df["points_real"]
    y_ps = df["p_start_real"]
    return X, y_pts, y_ps

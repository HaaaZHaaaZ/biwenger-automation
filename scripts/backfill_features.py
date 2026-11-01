#!/usr/bin/env python3
"""Backfill histórico de player_features desde logs y state."""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

from biwenger.features import init_db, upsert_features
from biwenger.config import DATA_DIR, LOG_FILE, STATE_FILE


def extract_from_log():
    """Extrae entradas de log.json con catálogo y partidos."""
    if not os.path.exists(LOG_FILE):
        return []
    
    with open(LOG_FILE) as f:
        logs = json.load(f)
    
    # Filtrar acciones de tipo 'lineup_eval' (tienen catálogo y fixture info)
    return [entry for entry in logs if entry.get("action") == "lineup_eval"]


def extract_from_state():
    """Extrae estado histórico de biwenger_state.json."""
    if not os.path.exists(STATE_FILE):
        return []
    
    with open(STATE_FILE) as f:
        state = json.load(f)
    
    # Extraer solo los estados con catálogo y fixture info
    return [state]


def build_rows(entry):
    """Construye filas de player_features a partir de una entrada de log/state."""
    rows = []
    
    # Extraer catálogo
    catalog = entry.get("details", {}).get("catalog") or entry.get("details")
    if not catalog:
        return rows
    
    # Extraer fixture info (dificultad, condición)
    diff_map = entry.get("details", {}).get("diff_map") or {}
    games_map = entry.get("details", {}).get("games_map") or {}
    round_name = entry.get("details", {}).get("round_name") or ""
    
    # Extraer round (jornada) de la fecha
    timestamp = entry.get("timestamp", "")
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        round_num = int(round_name.split()[0]) if round_name else 0
    except (ValueError, AttributeError):
        round_num = 0
    
    # Procesar cada jugador
    for pid, cp in catalog.items():
        if not isinstance(cp, dict):
            continue
        
        # Datos del jugador
        player_id = int(pid)
        position = int(cp.get("position", 0))
        season_avg = float(cp.get("points", 0)) / (cp.get("playedHome", 0) + cp.get("playedAway", 0) + 1e-6)
        
        # Datos de fitness
        fitness = cp.get("fitness", [])[-5:]
        fit_avg = sum(f for f in fitness if isinstance(f, (int, float))) / max(len(fitness), 1)
        
        # Datos de dificultad rival
        team_id = cp.get("teamID")
        diff_home = diff_map.get(team_id, {}).get("rating", 50)
        diff_away = diff_home  # Simplificación: usar misma dificultad
        
        # Datos de minutos (simplificación: usar 90 si no hay info)
        minutes = int(cp.get("minutes", 90))
        
        # Datos de estado
        status = (cp.get("status", "ok")).lower()
        
        # Datos de p_start (estimado)
        p_start_est = float(cp.get("p_start", 0.7))
        
        # Datos reales (simplificación: usar puntos reales si están disponibles)
        points_real = cp.get("points", 0)
        p_start_real = 1.0 if minutes >= 60 else 0.0  # Simplificación
        
        rows.append({
            "player_id": player_id,
            "round": round_num,
            "season_avg": season_avg,
            "fit_avg": fit_avg,
            "diff_home": diff_home,
            "diff_away": diff_away,
            "minutes": minutes,
            "status": status,
            "p_start_est": p_start_est,
            "p_start_real": p_start_real,
            "points_real": points_real,
            "position": position
        })
    
    return rows


def main():
    """Backfill histórico desde logs y state."""
    init_db()
    
    # Extraer datos
    log_entries = extract_from_log()
    state_entries = extract_from_state()
    
    # Construir filas
    rows = []
    for entry in log_entries + state_entries:
        rows.extend(build_rows(entry))
    
    # Insertar en la base de datos
    if rows:
        upsert_features(rows)
        print(f"✅ Backfilled {len(rows)} rows")
    else:
        print("⚠️ No se encontraron datos para backfill")


if __name__ == "__main__":
    main()
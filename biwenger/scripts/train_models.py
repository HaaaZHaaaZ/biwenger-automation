#!/usr/bin/env python3
"""Script para entrenar modelos ML por posición usando datos históricos."""

import os
import sys
import joblib
import numpy as np

# Añadir el directorio padre al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from biwenger.models import ModelManager, POS_MODELS, POSITIONS
from biwenger.features import load_training_data


def train_models():
    """Entrena y guarda modelos ML para cada posición."""
    print("Iniciando entrenamiento de modelos ML...")

    # Cargar datos de entrenamiento
    X, y_pts, y_ps, positions = load_training_data()
    if X is None:
        print("❌ No hay datos de entrenamiento disponibles.")
        print("Ejecuta primero: python -m biwenger.features.backfill")
        return False

    from sklearn.linear_model import LinearRegression
    from sklearn.isotonic import IsotonicRegression

    mm = ModelManager()
    trained = 0

    for pos_id, tag in POS_MODELS.items():
        # Filtrar datos por posición
        mask = positions == pos_id if hasattr(positions, '__iter__') else [p == pos_id for p in positions]
        if isinstance(mask, list):
            mask = np.array(mask)

        n_samples = np.sum(mask) if hasattr(mask, '__iter__') else 1
        if n_samples < 20:
            print(f"⚠️  Posición {tag}: solo {n_samples} muestras (mínimo 20). Saltando.")
            continue

        # Features: [season_avg, fit_avg, easy*100, p_start, minutes, pos]
        X_pos = X[mask]
        y_pts_pos = y_pts[mask]
        y_ps_pos = y_ps[mask]

        # Modelo de regresión lineal para puntos esperados
        lr = LinearRegression()
        lr.fit(X_pos, y_pts_pos)

        # Modelo isotónico para p_start (probabilidad de titularidad)
        iso = IsotonicRegression(out_of_bounds="clip")
        # Usar p_start_est como features y p_start_real como target
        iso.fit(X_pos[:, 3] if X_pos.shape[1] > 3 else X_pos[:, 4], y_ps_pos)

        # Guardar modelo
        model = {"lr": lr, "iso": iso}
        mm.save(tag, model)
        trained += 1
        print(f"✅ Modelo entrenado para {tag}: {n_samples} muestras")

    # Guardar el ModelManager
    mm.save_all(mm.models)
    print(f"\n📊 Entrenamiento completado: {trained}/{len(POS_MODELS)} modelos guardados")
    return trained > 0


def main():
    """Punto de entrada."""
    success = train_models()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
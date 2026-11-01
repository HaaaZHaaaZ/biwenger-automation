"""Modelos ligeros por posición (GK/DEF/MID/FWD).

Incluye ``ModelManager`` con métodos load/save/predict usando joblib y sklearn.
"""
import joblib
import numpy as np
from pathlib import Path

from biwenger.config import __getattr__ as get_config
from biwenger.features import load_training_data

MODEL_DIR = Path(get_config("DATA_DIR")) / "models"
MODEL_DIR.mkdir(exist_ok=True)

POS_MODELS = {1: "gk", 2: "def", 3: "mid", 4: "fwd"}
TAG_TO_POS = {v: k for k, v in POS_MODELS.items()}
POSITIONS = ["gk", "def", "mid", "fwd"]


class ModelManager:
    """Gestor de modelos ML por posición."""

    def __init__(self, model_dir=None):
        self.model_dir = Path(model_dir) if model_dir is not None else MODEL_DIR
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.models = {}

    def _path(self, tag):
        return self.model_dir / f"{tag}.joblib"

    def load(self, tag=None):
        """Carga modelos. Si tag es None, carga todos los disponibles."""
        if tag is not None:
            p = self._path(tag)
            if p.exists():
                self.models[tag] = joblib.load(p)
            return self.models.get(tag)
        for t in POSITIONS:
            p = self._path(t)
            if p.exists():
                self.models[t] = joblib.load(p)
        return self.models

    def save(self, tag, model):
        """Guarda un modelo (dict con lr/iso) bajo el tag de posición."""
        self.models[tag] = model
        joblib.dump(model, self._path(tag))
        return self._path(tag)

    def save_all(self, models):
        for tag, model in models.items():
            self.save(tag, model)

    def predict(self, tag, X):
        """Predice puntos a partir de features para una posición."""
        model = self.models.get(tag) or self.load(tag)
        if model is None:
            raise FileNotFoundError(f"No model for position {tag}")
        lr = model["lr"]
        X = np.asarray(X)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return lr.predict(X)

    def predict_iso(self, tag, x):
        """Predice probabilidad de titularidad (isotónica)."""
        model = self.models.get(tag) or self.load(tag)
        if model is None:
            raise FileNotFoundError(f"No model for position {tag}")
        return model["iso"].predict(np.asarray(x))

    def available(self):
        return [t for t in POSITIONS if self._path(t).exists()]


def train_and_save():
    X, y_pts, y_ps = load_training_data()
    if X is None:
        return False
    from sklearn.linear_model import LinearRegression
    from sklearn.isotonic import IsotonicRegression
    mm = ModelManager()
    for pos_id, tag in POS_MODELS.items():
        mask = (X["position"] == pos_id) if "position" in X.columns else slice(None)
        if hasattr(mask, "sum") and mask.sum() < 20:
            continue
        lr = LinearRegression().fit(X[mask], y_pts[mask])
        iso = IsotonicRegression(out_of_bounds="clip").fit(X[mask]["p_start_est"], y_ps[mask])
        mm.save(tag, {"lr": lr, "iso": iso})
    return True


def load_models():
    mm = ModelManager()
    return mm.load()


# Singleton instance used across the app
MODEL_MANAGER = ModelManager()
MODEL_MANAGER.load()
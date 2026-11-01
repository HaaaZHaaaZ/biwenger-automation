import os
import tempfile
import pytest
import joblib
import numpy as np
from biwenger.models import ModelManager, train_and_save, POS_MODELS
from biwenger.features import load_training_data


def test_models_load_and_predict(tmp_path):
    """Testea carga y predicción de modelos."""
    # Crear directorio de modelos
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    
    # Crear modelos de prueba
    from sklearn.linear_model import LinearRegression
    from sklearn.isotonic import IsotonicRegression
    
    mm = ModelManager(str(model_dir))
    for tag in POS_MODELS.values():
        lr = LinearRegression().fit(np.random.rand(10, 5), np.random.rand(10))
        iso = IsotonicRegression().fit(np.random.rand(10), np.random.rand(10))
        mm.save(tag, {"lr": lr, "iso": iso})
    
    # Cargar modelos
    mm.load()
    assert len(mm.models) == len(POS_MODELS)
    
    # Probar predicciones
    for tag in POS_MODELS.values():
        X = np.random.rand(3, 5)
        pred = mm.predict(tag, X)
        assert pred.shape == (3,)
        
        x = np.random.rand(1)  # predict_iso espera 1D
        prob = mm.predict_iso(tag, x)
        assert prob.shape == (1,)


def test_models_train_and_load():
    """Testea entrenamiento y carga de modelos desde datos reales."""
    # Verificar que los datos de entrenamiento existan
    try:
        X, y_pts, y_ps = load_training_data()
        if X is None:
            pytest.skip("No hay datos de entrenamiento disponibles")
    except Exception:
        pytest.skip("No hay datos de entrenamiento disponibles")
    
    # Entrenar modelos
    success = train_and_save()
    assert success, "Entrenamiento de modelos falló"
    
    # Verificar que los modelos se guardaron
    mm = ModelManager()
    available = mm.available()
    assert len(available) > 0, "No se guardaron modelos"


def test_models_available():
    """Testea detección de modelos disponibles."""
    mm = ModelManager()
    available = mm.available()
    assert isinstance(available, list)
    assert all(t in POS_MODELS.values() for t in available)

# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones [SemVer](https://semver.org/lang/es/).

## [14.2.1] - 2026-11-02

### Arreglado
- El resumen de "Ofertas recibidas" del registro usa el mismo filtro que `stage_received_offers` (antes ocultaba ofertas de otros usuarios); eliminada una línea duplicada de pujas propias.
- `tests/conftest.py` fija `BIWENGER_DRY_RUN=true`: `test_ctx_defaults` ya no falla según el `.env` local.

### Cambiado
- `X-Version` por defecto 632 (antes 631; la API actual usa 632).

### Eliminado
- Código ML sin uso: `biwenger/models.py`, `biwenger/features.py`, `biwenger/scripts/train_models.py`, `scripts/backfill_features.py`, `tests/test_models.py`, `tests/test_features.py` y el test de scoring con modelos.
- Dependencias `pandas`, `numpy`, `scikit-learn` y `joblib` de `requirements.txt`.
- `stage_process_own_sale_offers` y sus tests: filtraba nuestras propias pujas, no ofertas de compradores, y ya estaba fuera del flujo desde 14.2.0.

## [14.2.0] - 2026-11-02

### Añadido
- Lectura de las reglas reales de la liga desde la API: sistema de puntuación, capitán/ariete, multiposición, cupo y ventas simultáneas.
- Multiposición: el once se reparte en huecos con `altPositions` cuando la liga lo permite, con reintento en posición real si la API lo rechaza.
- Formación 3-6-1.
- Tests de reglas de liga (`tests/test_league_rules.py`).

### Cambiado
- Scorer nuevo: media regularizada por posición, forma ponderada, reparto casa/fuera real y rival de la jornada correcta para los 20 equipos (backtest: +0,51 pts/jornada en 3 jornadas).
- Ventas por valor de fondo: una duda puntual ya no pone en venta a un buen jugador; se conserva el portero de reserva.
- Compras por mejora real del once (mínimo +0,30 pts/jornada); con el cupo lleno se pone a la venta al peor suplente.
- Ofertas recibidas: se procesa primero la mejor.
- Se reserva siempre una escritura para la alineación.
- Con capitán/ariete desactivados en la liga ya no se reenvía la alineación en cada pasada.

### Arreglado
- El estado incierto (`unknown_state`) se resuelve en la pasada de solo lectura; ya no bloquea indefinidamente.
- `dry_run` ya no se marca en las pasadas reales.
- Se respeta `BIWENGER_LEAGUE_ID`.

### Eliminado
- El scorer deja de usar los modelos ML (nunca llegaron a estar entrenados).

## [14.1.0] - 2026-11-01

### Añadido
- Módulo `biwenger/models.py` (modelos por posición) y `scripts/train_models.py` — sin uso desde 14.2.0.
- Script `biwenger/scripts/validate_strategy.py` para validar en cuentas de prueba.

### Cambiado
- Umbrales: `BUY_MARGIN=0.03`, `CUSHION_PCT=0.05`, `ACCEPT_MACHINE_MIN=0.90`, `MAX_SELLS=6`.
- Venta de suplentes con alineación cerrada (score < 1.5).

Versiones anteriores: ver la sección "Novedades" del README.

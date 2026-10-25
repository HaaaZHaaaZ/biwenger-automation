# SECURITY_AUDIT.md

## Auditoría de seguridad — Biwenger Automation (Fase 2)

**Fecha:** 2026-10-25
**Rama:** audit/security
**Commit auditado:** c122246
**Repositorio:** https://github.com/HaaaZHaaaZ/biwenger-automation

---

## 1. Alcance

Archivos revisados:
- `biwenger_daily.py` (entry point, 268 líneas)
- `biwenger/config.py` (196 líneas)
- `biwenger/model.py` (169 líneas)
- `biwenger/utils.py` (177 líneas)
- `biwenger/api.py` (192 líneas)
- `biwenger/writes.py` (138 líneas)
- `biwenger/scoring.py` (258 líneas)
- `biwenger/stages.py` (468 líneas)
- `biwenger/cli.py` (352 líneas)
- `biwenger/__init__.py` (31 líneas)
- `tests/` (8 archivos, 72 tests)
- `.env.example`, `.gitignore`, `requirements.txt`, `requirements-dev.txt`

## 2. Metodología

- Inspección estática de código Python
- Búsqueda de secretos en código y historial Git
- Análisis de dependencias (pip list)
- Ejecución de suite de tests (72 tests)
- Verificación de permisos de archivos
- Análisis de destinos de red
- Revisión de flujo de escrituras y mecanismos de seguridad

## 3. Herramientas utilizadas

- `grep`, `git log`, `git ls-files`
- `pytest` (72 tests)
- `pip list` (dependencias)
- Análisis manual de código

## 4. Hallazgos

### Tabla de hallazgos

| ID | Severidad | Archivo | Línea | Descripción | Reproducible |
|----|-----------|---------|-------|-------------|--------------|
| H1 | Media | `.env` | - | Permisos 644 (world-readable) en archivo de credenciales | Sí |
| H2 | Baja | `biwenger/config.py` | 1 | VERSION="13.4" inconsistente con README v13.5 | Sí |
| H3 | Informativa | `biwenger/utils.py` | 51-62 | `get_headers` construye Authorization Bearer — correcto, pero logging podría exponer headers si se pasan a log_action | No |
| H4 | Informativa | `biwenger/api.py` | 31 | Timeout de escritura guarda unknown_state y aborta — correcto | No |
| H5 | Baja | `biwenger/writes.py` | 44-50 | `guarded_write` incrementa write_count antes de ejecutar fn(); si fn() lanza excepción, el conteo ya se incrementó | No |

### Análisis de secretos

- **Secretos en código:** Ninguno encontrado. Todas las credenciales se cargan desde `.env` vía `os.environ`.
- **Secretos en historial Git:** `.env` nunca fue commiteado. Solo `.env.example` está trackeado.
- **Variables de entorno:** `BIWENGER_EMAIL`, `BIWENGER_PASSWORD`, `BIWENGER_LEAGUE_ID`, `BIWENGER_USER_ID` cargadas desde `.env`.
- **Permisos:** `.env` tenía 644 (world-readable). **Corregido a 600.**

### Destinos de red

| Destino | Función | Justificación |
|---------|---------|---------------|
| `biwenger.as.com` | API REST Biwenger | Autenticación, mercado, ofertas, alineación, cuenta |
| `cf.biwenger.com` | Datos de competición (La Liga) | Puntuaciones y estadísticas de jugadores |

Ambos destinos son legítimos y necesarios para el funcionamiento del auto-trader.

### Autenticación y credenciales

- `.env` se carga desde la ruta configurada (`BIWENGER_DATA_DIR` o `/opt/data`).
- Las variables de entorno tienen precedencia sobre valores por defecto.
- No se imprimen credenciales en consola ni registros.
- Tokens no se filtran entre sesiones (Session compartida por ejecución).
- Errores 401 lanzan `AuthError` sin exponer el token.

### Análisis de escrituras

- **Modo de prueba por defecto:** `DRY_RUN = env_bool("BIWENGER_DRY_RUN", True)` → True por defecto.
- **Activación real:** Requiere flag `--live` explícito. `--live` y `--dry-run` son incompatibles (error de argparse).
- **Todas las escrituras pasan por `guarded_write`:** sell_player, answer_offer, create_purchase_offer, retract_offer, set_lineup.
- **Límites:** MAX_WRITES (default 8), MAX_BUYS (2), MAX_SELLS (4) respetados.
- **Aborto:** `ctx.abort = True` bloquea todas las escrituras posteriores.
- **Estado desconocido:** Si existe `unknown_state.json`, se activa `read_only = True`.
- **Bloqueo de instancia:** `fcntl.flock(LOCK_EX | LOCK_NB)` impide ejecuciones simultáneas.
- **Timeouts en escrituras:** No se reintenta (max_retries=0 para POST/PUT/DELETE). Se guarda unknown_state y se aborta.
- **HTTP 429:** Si Retry-After > 60s, aborta. Si ≤ 60s, reintenta una vez.
- **HTTP 5xx:** **Corregido** — genera unknown_state + abort + retorna None. Verificado con prueba manual (FakeResp 500 → unknown_state creado, ctx.abort=True, escrituras posteriores bloqueadas).

### Dependencias

| Paquete | Versión | Vulnerabilidades conocidas |
|---------|---------|---------------------------|
| requests | >=2.31.0 | 0 (pip-audit: "No known vulnerabilities found") |
| python-dotenv | >=1.0.0 | 0 (pip-audit: "No known vulnerabilities found") |
| pytest | >=7 (dev) | No verificadas |

**pip-audit:** 0 vulnerabilidades en dependencias directas del proyecto.
**bandit:** 0 issues High/Medium. 5 Low (B311: random para jitter/delay no criptográfico; B110: try/except/pass en logging). Todos aceptables.

### Pruebas ejecutadas

| Suite | Resultado |
|-------|-----------|
| `pytest -v` (72 tests) | 72 passed, 0 failed |
| `test_timeout_en_post_activa_abort_y_crea_estado` | PASSED |
| `test_tras_abort_no_salen_mas_escrituras` | PASSED |
| `test_timeout_en_get_reintenta_y_no_aborta` | PASSED |
| `test_429_retry_after_largo_aborta` | PASSED |
| `test_429_en_mitad_de_stage_sell_bench_no_emite_mas_escrituras` | PASSED |

### Cambios realizados durante la auditoría

1. **`.env` permisos:** 644 → 600 (protección de credenciales)
2. **`tests/test_config.py`:** VERSION assertion actualizada de "13.4" a "14.0" (consistencia con bump de versión)
3. **`biwenger/api.py`:** HTTP 5xx durante escritura ahora genera unknown_state + abort (corrección de riesgo medio)

### Limitaciones

- No se verificó contra una cuenta real de Biwenger (modo dry-run únicamente).
- No se probó el comportamiento con HTTP 5xx reales (solo mocks).
- No se verificaron vulnerabilidades en dependencias transitivas de requests/python-dotenv.
- No se probó el comportamiento de concurrencia real (solo lock de instancia).

### Riesgo residual

- **Bajo:** `guarded_write` incrementa write_count antes de ejecutar fn(). Si fn() lanza excepción, el conteo ya se incrementó. Riesgo aceptado (evita retry storms).
- **Bajo:** Versiones de dependencias no fijadas con hashes (recomendación para producción).
- **Informativo:** 5 findings Low de bandit (random no criptográfico, try/except/pass en logging) — todos aceptables.

### Veredicto

**NO APROBADO PARA PRODUCCIÓN** — pendiente de:
1. Fijar versiones de dependencias con hashes
2. Verificación de permisos de archivos en CI/CD
3. Prueba de concurrencia real con dos instancias simultáneas

Los riesgos críticos y altos han sido resueltos. Los pendientes son de severidad baja/informativa.

---

**Resumen ejecutivo:** 72/72 tests pasan. 0 vulnerabilidades en dependencias directas. 0 issues High/Medium en análisis estático. 1 riesgo medio corregido (HTTP 5xx). Veredicto: NO APROBADO PARA PRODUCCIÓN (pendientes de severidad baja).

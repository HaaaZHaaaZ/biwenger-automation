# ⚽ Biwenger Auto-Trader v13.4

> Automatización inteligente del juego Biwenger vía API REST — login, mercado, alineación, ofertas y más.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen.svg)
![Version](https://img.shields.io/badge/version-13.4-blue.svg)

---

## 📑 Tabla de contenidos

- [Novedades v13.4](#-novedades-v134)
- [Características](#-características)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Tests y verificación](#-tests-y-verificación)
- [Documentación detallada](#-documentación-detallada)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Seguridad operativa](#-seguridad-operativa)
- [Automatización con cron](#-automatización-con-cron)
- [Diseñado para agentes de IA](#-diseñado-para-agentes-de-ia)
- [Pendiente](#-pendiente)
- [Licencia](#-licencia)

---

## 🆕 Novedades v13.4

- **Informe detallado de ejecución.** Al final de cada run el script imprime por stdout un informe completo: estado de cuenta, plantilla puntuada por posiciones (GK/DEF/MID/FWD), acciones (ofertas recibidas, ventas, compras, alineación), resumen (acciones/writes/peticiones) e incidencias. Diseñado para entrega directa por Telegram (el cron lo envía).
- **Cambio de alineación visible.** Cuando se cambia la alineación, el informe indica quién **sale** y quién **entra**.

---

## ✨ Características

| Módulo | Capacidad |
|--------|-----------|
| **Login** | Bearer token + sesión persistente con `requests.Session()` |
| **Alineación** | 7 formaciones evaluadas, scorer con p_start, localía, dificultad del rival |
| **Free Market** | Pujas dinámicas según competencia estimada (baja/media/alta) |
| **Ventas** | Venta automática de suplentes con score < 2.0 o lesionados, previa validación de reemplazo |
| **Desbloqueo de cupo** | Acepta ofertas de la máquina (≥90%) sobre suplentes en venta para liberar plantilla bloqueada (16/16) |
| **Ofertas recibidas** | Consulta `?status=waiting` · Acepta ≥110% mercado, ≥125% sin reemplazo, o si el jugador está lesionado ≥90% |
| **Capitán & Ariete** | Activables por variable de entorno, con scoring y selección automática |
| **Logs** | Doble salida: `biwenger_log.json` (estructurado) + `biwenger_log.txt` (legible) |
| **Cron** | Ejecución programable 2× al día con jitter aleatorio |
| **Safe modes** | Dry-run por defecto; `--live` para escribir; `--probe` (descubre campos API) |

---

## 🚀 Instalación

```bash
git clone https://github.com/HaaaZHaaaZ/biwenger-automation.git
cd biwenger-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # solo para tests
cp .env.example .env
# Edita .env con tus credenciales
```

---

## ▶️ Uso

```bash
# Dry-run (por defecto): analiza y registra, NO escribe
python3 biwenger_daily.py

# Ejecución real (única forma de escribir)
python3 biwenger_daily.py --live

# Dry-run explícito
python3 biwenger_daily.py --dry-run

# Descubrir campos de capitán/ariete
python3 biwenger_daily.py --probe
```

**Códigos de salida:** `0` OK · `1` Error · `3` Credenciales faltantes · `5` X-Version obsoleta · `6` Rate limit

> ⚠️ Sin `--live` no se emite ninguna escritura, aunque `BIWENGER_DRY_RUN=false` en el entorno.

---

## ✅ Tests y verificación

```bash
# Ejecutar la suite completa
.venv/bin/python -m pytest -v

# Verificación de cierre (compilación + grep de escrituras + pytest)
./verify.sh; echo "exit=$?"
```

`verify.sh` devuelve exit code ≠ 0 si falla la compilación, el grep detecta escrituras fuera de `guarded_write`, o falla algún test. La salida completa queda en `VERIFY_OUTPUT.txt`.

---

## 📚 Documentación detallada

- [Variables de entorno](docs/environment.md) — credenciales, estrategia de compra/venta, ofertas, alineación, saldo, técnicas.
- [Scorer y límites](docs/scoring.md) — fórmula de puntuación y límites del sistema (peticiones, sesiones, rate limit).
- [Tutorial Hermes Agent](docs/hermes-tutorial.md) — cómo orquestar este script con un agente de IA.

---

## 🏗️ Estructura del proyecto

```
biwenger-automation/
├── biwenger_daily.py      # Script principal
├── .env.example           # Plantilla de credenciales
├── .env                   # ⚠️ Tus credenciales (NO se sube)
├── .gitignore             # Archivos ignorados
├── requirements.txt       # Dependencias de ejecución
├── requirements-dev.txt   # Dependencias de test (pytest)
├── verify.sh              # Verificación de cierre
├── VERIFY_OUTPUT.txt      # Salida de la última verificación
├── README.md              # Documentación
├── tests/                 # Suite pytest
│   ├── conftest.py
│   ├── test_safety.py
│   ├── test_abort.py
│   ├── test_guarded.py
│   └── test_write_modes.py
└── docs/                  # Documentación detallada
    ├── environment.md
    ├── scoring.md
    └── hermes-tutorial.md
```

---

## 🔒 Seguridad operativa

- **Dry-run por defecto:** el bot no escribe nada salvo que se pase `--live`.
- **Lockfile de instancia única:** `BIWENGER_LOCKFILE_PATH` evita ejecuciones solapadas (flock no bloqueante; si hay otra viva, sale sin operar).
- **guarded_write:** todas las escrituras pasan por un único guard (`abort` → `read_only` → `dry_run` → `MAX_WRITES`).
- **Unknown state:** si una escritura da timeout, se crea `BIWENGER_UNKNOWN_STATE_PATH`; mientras exista, el bot opera en modo solo lectura hasta que el usuario lo borre a mano.
- **Presupuesto global de espera:** `BIWENGER_WAIT_BUDGET_SECONDS` (default 90s). Al agotarse, aborta la ejecución.
- **Retry-After > 60s:** no se reintenta ni se recorta; se aborta la operación y se registra.
- **Reintentos solo en GET:** las escrituras (POST/PUT/DELETE) no se reintentan tras error de red, para no duplicar ofertas/ventas.

- `.env` y `*.env` están en `.gitignore` — **nunca se suben credenciales al repositorio**
- Las credenciales se leen desde variables de entorno o archivo `.env` exclusivamente
- El script usa una sesión `requests.Session()` aislada

---

## 🔄 Automatización con cron

```bash
# Ejecutar 2 veces al día (9:00 y 21:00) en modo real
0 9,21 * * * cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py --live
```

> Sin `--live` el cron solo simularía. El flag es obligatorio para que el bot escriba.

---

## 🤖 Diseñado para agentes de IA

Este proyecto está pensado para ser **operado por un agente de IA**. El script es determinista y autónomo: lee el estado de la cuenta, decide y ejecuta (vender, comprar, alinear) sin preguntar, y registra cada acción en `biwenger_log.json` / `biwenger_log.txt`.

Principios: sin interacción humana, idempotente, límites estrictos (10 peticiones/sesión, 2 sesiones/día), modo seguro por defecto (dry-run, `--probe`), estado persistente y logs estructurados.

Ver [Tutorial Hermes Agent](docs/hermes-tutorial.md) para la guía completa de implementación.

---

## ⏳ Pendiente

Fuera del alcance de v13.3, documentado como deuda técnica:

- `log_action` en JSONL append con `RotatingFileHandler` (hoy: JSON + lock + escritura atómica).
- Reintento único o estado explícito `rate_limited` en `api()` para 429 en escrituras con `Retry-After ≤ 60s`.
- Registro de `unknown_outcome` ante 5xx o respuesta ilegible tras enviar una escritura.
- `resolve_unknown_state` (resolución automática por GET); hoy el modo lectura se levanta borrando el fichero a mano.
- 5 tests de `tests/test_safety.py` aún en rojo (429/timeout/abort).

---

## 📝 Licencia

MIT — haz lo que quieras con el código, pero **no responsabilizamos de pérdidas en tu liga fantasy**.

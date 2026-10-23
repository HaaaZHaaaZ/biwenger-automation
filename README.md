# ⚽ Biwenger Auto-Trader v13

> Automatización inteligente del juego Biwenger vía API REST — login, mercado, alineación, ofertas y más.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen.svg)

---

## 📑 Tabla de contenidos

- [Características](#-características)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Documentación detallada](#-documentación-detallada)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Seguridad](#-seguridad)
- [Automatización con cron](#-automatización-con-cron)
- [Diseñado para agentes de IA](#-diseñado-para-agentes-de-ia)
- [Licencia](#-licencia)

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
| **Safe modes** | `--dry-run` (simula sin escribir) + `--probe` (descubre campos API) |

---

## 🚀 Instalación

```bash
git clone https://github.com/HaaaZHaaaZ/biwenger-automation.git
cd biwenger-automation
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv
cp .env.example .env
# Edita .env con tus credenciales
```

---

## ▶️ Uso

```bash
# Ejecución normal
python3 biwenger_daily.py

# Simulación (sin escrituras)
python3 biwenger_daily.py --dry-run

# Descubrir campos de capitán/ariete
python3 biwenger_daily.py --probe
```

**Códigos de salida:** `0` OK · `1` Error · `3` Credenciales faltantes · `5` X-Version obsoleta · `6` Rate limit

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
├── README.md              # Documentación
└── docs/                  # Documentación detallada
    ├── environment.md
    ├── scoring.md
    └── hermes-tutorial.md
```

---

## 🛡️ Seguridad

- `.env` y `*.env` están en `.gitignore` — **nunca se suben credenciales al repositorio**
- Las credenciales se leen desde variables de entorno o archivo `.env` exclusivamente
- El script usa una sesión `requests.Session()` aislada
- Modo `--dry-run` bloquea todas las escrituras
- Verificación de cambios: usa `scripts/verify_sell_gate.py` antes de alterar la estrategia en producción

---

## 🔄 Automatización con cron

```bash
# Ejecutar 2 veces al día (9:00 y 21:00)
0 9,21 * * * cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py
```

---

## 🤖 Diseñado para agentes de IA

Este proyecto está pensado para ser **operado por un agente de IA**. El script es determinista y autónomo: lee el estado de la cuenta, decide y ejecuta (vender, comprar, alinear) sin preguntar, y registra cada acción en `biwenger_log.json` / `biwenger_log.txt`.

Principios: sin interacción humana, idempotente, límites estrictos (10 peticiones/sesión, 2 sesiones/día), modo seguro (`--dry-run`, `--probe`), estado persistente y logs estructurados.

Ver [Tutorial Hermes Agent](docs/hermes-tutorial.md) para la guía completa de implementación.

---

## 📝 Licencia

MIT — haz lo que quieras con el código, pero **no responsabilizamos de pérdidas en tu liga fantasy**.

# ⚽ Biwenger Auto-Trader v13

> Automatización inteligente del juego Biwenger vía API REST — login, mercado, alineación, ofertas y más.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-production-brightgreen.svg)

---

## ✨ Características

| Módulo | Capacidad |
|--------|-----------|
| **Login** | Bearer token + sesión persistente con `requests.Session()` |
| **Alineación** | 7 formaciones evaluadas, scorer con p_start, localía, dificultad del rival |
| **Free Market** | Pujas dinámicas según competencia estimada (baja/media/alta) |
| **Ventas** | Venta automática de suplentes con score < 2.0 o lesionados, previa validación de reemplazo |
| **Desbloqueo de cupo** | Acepta ofertas de la máquina (≥90%) sobre suplentes en venta para liberar plantilla bloqueada (16/16) |
| **Ofertas recibidas** | Consulta `?status=waiting` (API filtra pendientes) · Acepta ≥110% mercado, ≥125% sin reemplazo, o si el jugador está lesionado ≥90% |
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

## 🔧 Variables de entorno

### Credenciales (requeridas)

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_EMAIL` | Email de tu cuenta | — |
| `BIWENGER_PASSWORD` | Contraseña | — |
| `BIWENGER_TOKEN` | Token Bearer directo (alternativa a email+pass) | vacío |
| `BIWENGER_LEAGUE_ID` | ID de tu liga | 0 (auto) |
| `BIWENGER_USER_ID` | ID de tu usuario | 0 (auto) |

### Estrategia de compra

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_BUY_MARGIN` | Mejora mínima sobre el peor titular para comprar | `0.05` (5%) |
| `BIWENGER_BID_LOW` | Multiplicador para puja baja (sin competencia) | `1.04` |
| `BIWENGER_BID_MID` | Multiplicador para puja media | `1.10` |
| `BIWENGER_BID_HIGH` | Multiplicador para puja alta (con competencia) | `1.20` |
| `BIWENGER_MAX_BID_PCT` | Techo máximo de puja | `1.25` |
| `BIWENGER_BID_PLUS_ONE` | +1€ para evitar empates exactos | `true` |
| `BIWENGER_MAX_BUYS` | Compras máximas por ejecución | `2` |

### Estrategia de venta

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_SELL_SCORE_MIN` | Score mínimo para mantener un suplente | `2.0` |
| `BIWENGER_MAX_SELLS` | Ventas máximas por ejecución | `6` |
| `BIWENGER_ACCEPT_MACHINE_MIN` | Acepta ofertas de la máquina (≥90%) sobre suplentes en venta para desbloquear cupo | `0.90` |
| `BIWENGER_MAX_TEAM_SIZE` | Cupo máximo de la liga (jugadores + ofertas abiertas) | `16` |
| `BIWENGER_MIN_SQUAD` | Plantilla mínima (nunca bajar de aquí) | `12` |
| `BIWENGER_MATCH_SOON_HOURS` | Horas antes de un partido para no vender | `48` |
| `BIWENGER_SELL_BENCH_LINEUP_READY` | Vender suplentes aunque tengan partido si la alineación ya está lista | `true` |
| `BIWENGER_MAX_DROP_PCT` | Caída de precio máxima para vender urgente | `0.08` |

### Ofertas recibidas

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_ACCEPT_NORMAL` | Aceptar si oferta ≥ N% del mercado | `1.10` (110%) |
| `BIWENGER_ACCEPT_HIGH` | Aceptar sin reemplazo si oferta ≥ N% | `1.25` (125%) |
| `BIWENGER_ACCEPT_INJURED` | Aceptar si lesionado y oferta ≥ N% | `0.90` (90%) |

### Alineación

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_MIN_LINEUP_GAIN` | Mejora mínima para cambiar alineación | `0.05` (5%) |
| `BIWENGER_CAPTAIN_KEY` | Nombre del campo capitán en la API | vacío (desactivado) |
| `BIWENGER_STRIKER_KEY` | Nombre del campo ariete en la API | vacío (desactivado) |
| `BIWENGER_CAPTAIN_MAX_VALUE` | Valor máximo para elegir capitán | 0 (sin tope) |

### Control de saldo

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_CUSHION_PCT` | Porcentaje del equipo como colchón | `0.08` (8%) |
| `BIWENGER_CUSHION_MIN` | Colchón mínimo en € | `500000` |

### Técnicas

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_VERSION` | Versión de la API (cabecera X-Version) | `631` |
| `BIWENGER_REQUEST_TIMEOUT` | Timeout por petición (s) | `30` |
| `BIWENGER_MAX_RETRIES` | Reintentos por error | `1` |
| `BIWENGER_REQUEST_DELAY` | Pausa media entre peticiones (s) | `0.8` |
| `BIWENGER_START_JITTER_MAX` | Jitter aleatorio inicial (s) | `0` |
| `BIWENGER_DRY_RUN` | Modo solo simulación | `false` |
| `BIWENGER_DATA_DIR` | Directorio para logs y estado | `/opt/data` |
| `BIWENGER_RATE_LIMIT_WAIT_HOURS` | Espera tras rate limit 429 | `4` |

---

## 📊 Scorer

```
score = (0.35·ppp + 0.35·forma5 + 0.90·facilidad_rival) × mult_estado × p_start
```

**p_start** (probabilidad de titularidad):
- Histórico de minutos últimas 3-5 jornadas
- 90′ consistentes → ~0.9-1.0
- Rotación → 0.5-0.7
- Sin minutos → <0.3

**Multiplicadores de estado:**
| Estado | Multiplicador |
|--------|:------------:|
| `ok` | 1.00 |
| `warned` | 0.85 |
| `doubt` | 0.55 |
| `injured/suspended/sanctioned` | 0.00 |

---

## ⚠️ Límites del sistema

| Recurso | Límite |
|---------|--------|
| Peticiones por sesión | **10** máximo |
| Sesiones por día | **2** (9:00 AM / 9:00 PM) |
| Reintentos tras error | **1** |
| Timeout por petición | **30s** |
| Espera tras 429 | **4 horas** |

---

## 🏗️ Estructura del proyecto

```
biwenger-automation/
├── biwenger_daily.py      # Script principal
├── .env.example           # Plantilla de credenciales
├── .env                   # ⚠️ Tus credenciales (NO se sube)
├── .gitignore             # Archivos ignorados
└── README.md              # Documentación
```

---

## 🛡️ Seguridad

- `.env` y `*.env` están en `.gitignore` — **nunca se suben credenciales al repositorio**
- Las credenciales se leen desde variables de entorno o archivo `.env` exclusivamente
- El script usa una sesión `requests.Session()` aislada
- Modo `--dry-run` bloquea todas las escrituras
- Verificación de cambios: usa `scripts/verify_sell_gate.py` antes de alterar la estrategia en producción

## 🔄 Automatización con cron

```bash
# Ejecutar 2 veces al día (9:00 y 21:00)
0 9,21 * * * cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py

# Con jitter de 15 min
15,45 9,21 * * * cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py
```

---

## 📝 Licencia

MIT — haz lo que quieras con el código, pero **no responsabilizamos de pérdidas en tu liga fantasy**.
# Variables de entorno — Biwenger Auto-Trader

## Credenciales (requeridas)

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_EMAIL` | Email de tu cuenta | — |
| `BIWENGER_PASSWORD` | Contraseña | — |
| `BIWENGER_TOKEN` | Token Bearer directo (alternativa a email+pass) | vacío |
| `BIWENGER_LEAGUE_ID` | ID de tu liga | 0 (auto) |
| `BIWENGER_USER_ID` | ID de tu usuario | 0 (auto) |

## Estrategia de compra

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_BUY_MARGIN` | Mejora mínima sobre el peor titular para comprar | `0.05` (5%) |
| `BIWENGER_BID_LOW` | Multiplicador para puja baja (sin competencia) | `1.04` |
| `BIWENGER_BID_MID` | Multiplicador para puja media | `1.10` |
| `BIWENGER_BID_HIGH` | Multiplicador para puja alta (con competencia) | `1.20` |
| `BIWENGER_MAX_BID_PCT` | Techo máximo de puja | `1.25` |
| `BIWENGER_BID_PLUS_ONE` | +1€ para evitar empates exactos | `true` |
| `BIWENGER_MAX_BUYS` | Compras máximas por ejecución | `2` |

## Estrategia de venta

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

## Ofertas recibidas

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_ACCEPT_NORMAL` | Aceptar si oferta ≥ N% del mercado | `1.10` (110%) |
| `BIWENGER_ACCEPT_HIGH` | Aceptar sin reemplazo si oferta ≥ N% | `1.25` (125%) |
| `BIWENGER_ACCEPT_INJURED` | Aceptar si lesionado y oferta ≥ N% | `0.90` (90%) |

## Alineación

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_MIN_LINEUP_GAIN` | Mejora mínima para cambiar alineación | `0.05` (5%) |
| `BIWENGER_CAPTAIN_KEY` | Nombre del campo capitán en la API | vacío (desactivado) |
| `BIWENGER_STRIKER_KEY` | Nombre del campo ariete en la API | vacío (desactivado) |
| `BIWENGER_CAPTAIN_MAX_VALUE` | Valor máximo para elegir capitán | 0 (sin tope) |

## Control de saldo

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_CUSHION_PCT` | Porcentaje del equipo como colchón | `0.08` (8%) |
| `BIWENGER_CUSHION_MIN` | Colchón mínimo en € | `500000` |

## Técnicas

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

# Biwenger Automation

Automatización del juego Biwenger vía API — login, ventas, compras, alineación automática y cron scheduler.

## Características (v10)

- **Login automático** con token Bearer
- **Optimización de alineación** con 7 formaciones (4-4-2, 4-3-3, 3-4-3, 3-5-2, 5-3-2, 4-5-1, 5-4-1)
- **Scorer mejorado** con probabilidad de titularidad (p_start), localía y dificultad de rival
- **Compras con pujas dinámicas** según competencia estimada
- **Ofertas recibidas** con reglas inteligentes (110%, 125%, lesiones) y simulación de plantilla
- **Ventas de suplentes** con validación de reemplazo y fecha de partido
- **Control de saldo** con colchón de seguridad
- **Capitán y ariete** (activar con variables de entorno)
- **Logs completos** en JSON y texto
- **Cron scheduler** para ejecución automática
- **Modo --dry-run** (simula sin escribir) y **--probe** (descubre campos de la API)

## Instalación

```bash
# Clonar repositorio
git clone https://github.com/HaaaZHaaaZ/biwenger-automation.git
cd biwenger-automation

# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install requests

# Configurar credenciales
cp .env.example .env
# Editar .env con tus credenciales
```

## Uso

```bash
# Ejecutar normalmente
python3 biwenger_daily.py

# Simular sin escribir
python3 biwenger_daily.py --dry-run

# Descubrir campos de la API (capitán/ariete)
python3 biwenger_daily.py --probe
```

## Configuración de Cron

```bash
# Ejecutar dos veces al día (9 AM y 9 PM)
0 9,21 * * * cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py
```

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `BIWENGER_EMAIL` | Email de la cuenta | (requerido) |
| `BIWENGER_PASSWORD` | Contraseña | (requerido) |
| `BIWENGER_LEAGUE_ID` | ID de la liga | 0 (auto) |
| `BIWENGER_USER_ID` | ID del usuario | 0 (auto) |
| `BIWENGER_VERSION` | Versión de la API | 631 |
| `BIWENGER_CAPTAIN_KEY` | Campo del capitán | (vacío) |
| `BIWENGER_STRIKER_KEY` | Campo del ariete | (vacío) |
| `BIWENGER_DRY_RUN` | Modo simulación | false |
| `BIWENGER_MAX_WRITES` | Máx. escrituras por corrida | 8 |
| `BIWENGER_BUY_MARGIN` | Margen de compra | 0.05 |
| `BIWENGER_CUSHION_PCT` | Colchón de saldo | 0.08 |

## Estructura

```
biwenger-automation/
├── biwenger_daily.py      # Script principal
├── .env.example           # Plantilla de credenciales
├── .gitignore            # Archivos ignorados
└── README.md             # Este archivo
```

## Notas

- **NO** subas tus credenciales al repositorio
- El script respeta los límites de la API (429 rate limit)
- Las credenciales se leen de variables de entorno o archivo `.env`
- El modo `--dry-run` es seguro: no escribe nada

## Licencia

MIT

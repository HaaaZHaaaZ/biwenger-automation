# Biwenger Automation

Automatización del juego Biwenger vía API — login, ventas, compras, alineación automática y cron scheduler.

## Características

- **Login automático** con token Bearer
- **Optimización de alineación** con 7 formaciones (4-4-2, 4-3-3, 3-4-3, 3-5-2, 5-3-2, 4-5-1, 5-4-1)
- **Scorer mejorado** con probabilidad de titularidad, localía y dificultad de rival
- **Compras con pujas dinámicas** según competencia estimada
- **Ofertas recibidas** con reglas inteligentes (110%, 125%, lesiones)
- **Ventas de suplentes** con validación de reemplazo
- **Control de saldo** con colchón de seguridad
- **Logs completos** en JSON y texto
- **Cron scheduler** para ejecución automática

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
# Ejecutar manualmente
python3 biwenger_daily.py

# O con variables de entorno
BIWENGER_EMAIL=xxx BIWENGER_PASSWORD=yyy python3 biwenger_daily.py
```

## Configuración de Cron

```bash
# Ejecutar dos veces al día (9 AM y 9 PM)
0 9,21 * * * cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py
```

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

## Licencia

MIT

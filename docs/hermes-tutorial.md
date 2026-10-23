# Tutorial: implementar con Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) es el agente de IA que orquesta este script. Pasos para replicar la automatización:

## 1. Clonar el repo en el servidor del agente

```bash
git clone https://github.com/HaaaZHaaaZ/biwenger-automation.git /opt/data/biwenger-automation
cd /opt/data/biwenger-automation
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv
cp .env.example .env
# Edita .env con tus credenciales de Biwenger
```

## 2. Configurar el cron en Hermes

En `~/.hermes/config.yaml` (o `/opt/data/config.yaml`), define la tarea programada:

```yaml
cron:
  jobs:
    - name: "biwenger-daily"
      schedule: "0 9,21 * * *"   # 9:00 y 21:00
      command: "cd /opt/data/biwenger-automation && source .venv/bin/activate && python3 biwenger_daily.py"
      notify: true                # avisa por Telegram al terminar
```

## 3. Dar al agente contexto persistente (memoria)

El agente debe recordar entre sesiones los parámetros de la liga y el estado. En Hermes, usa la herramienta `memory` para guardar hechos duraderos, por ejemplo:

- Liga ID, user ID, saldo actual, puntos, posición.
- Cuentas de prueba y sus UIDs.
- Parámetros de estrategia (colchón, umbrales, max sells).
- Endpoints confirmados y pitfalls (404 en compras de test, 500 en lineup).

## 4. Skills recomendadas

Carga las skills de Biwenger en Hermes para que el agente tenga el conocimiento del dominio:

- `biwenger` — reglas del juego, puntuación, mercado, estrategia.
- `biwenger-automation` — endpoints API, flujo de operaciones, límites.
- `biwenger_web` — fallback vía navegador cuando la API falla.

```
skill_view(name='biwenger-automation')
```

## 5. Ejecución autónoma

El agente ejecuta `biwenger_daily.py` sin confirmación. Tras cada corrida:
- Lee `biwenger_log.txt` para el resumen.
- Actualiza `biwenger_state.json` y `biwenger_todo.md`.
- Notifica por Telegram con puntos, saldo, posición y acciones.

## 6. Verificación antes de cambios

Antes de alterar la estrategia en producción, el agente debe ejecutar la lógica aislada:

```bash
python3 scripts/verify_sell_gate.py
```

Esto simula decisiones con los datos de `biwenger_state.json` sin gastar peticiones de la API.

## 7. Buenas prácticas del agente

- **Nunca subir credenciales** al repositorio (`.env` está en `.gitignore`).
- **Actualizar el README** cada vez que se modifique el script o la estrategia.
- **Sincronizar** la copia de referencia (`biwenger-automation/biwenger_daily.py`) con la que ejecuta el cron (`/opt/data/biwenger_daily.py`) usando `cp`.
- **Avisar antes de tocar la cuenta principal**; en cuentas de prueba puede actuar de forma autónoma.

# Scorer y límites del sistema — Biwenger Auto-Trader

## Scorer (v14.2.0)

```
base  = 0,7·media_temporada + 0,3·forma_reciente
base  = (partidos·base + 4·media_posición) / (partidos + 4)
score = base × local × rival × mult_estado × p_jugar^1,5
```

- **p_jugar**: últimos 5 partidos ponderados; las bajas no cuentan en contra.
- **Rival**: `difficulty.rating` de la jornada objetivo, con sensibilidad por posición.
- **Valor de fondo** (`player_value`): base × p_jugar^1,5, sin estado ni rival. Decide las ventas.
- Los parámetros están en `biwenger/config.py`.

**Multiplicadores de estado:**

| Estado | Multiplicador |
|--------|:------------:|
| `ok` | 1.00 |
| `warned` | 0.85 |
| `doubt` | 0.55 |
| `injured/suspended/sanctioned` | 0.00 |

## Límites del sistema

| Recurso | Límite |
|---------|--------|
| Peticiones por sesión | ~8 en una pasada normal |
| Sesiones por día | **2** (9:00 / 21:00 UTC) |
| Reintentos tras error | **1** |
| Timeout por petición | **30s** |
| Espera tras 429 | **4 horas** |

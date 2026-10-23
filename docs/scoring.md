# Scorer y límites del sistema — Biwenger Auto-Trader

## Scorer

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

## Límites del sistema

| Recurso | Límite |
|---------|--------|
| Peticiones por sesión | **10** máximo |
| Sesiones por día | **2** (9:00 AM / 9:00 PM) |
| Reintentos tras error | **1** |
| Timeout por petición | **30s** |
| Espera tras 429 | **4 horas** |

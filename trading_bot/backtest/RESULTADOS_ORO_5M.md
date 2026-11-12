# Oro en 5 minutos: backtest rápido (2026-11-10)

Datos: XAU/USD de Twelve Data, 18.419 velas de 5m, del 2026-08-12 al 2026-11-10.
Entradas solo de 15:00 a 18:30 del servidor (13:00-16:30 UTC); cierre forzado a las 20:00.
Costo: spread 0,34 + deslizamiento 0,15 USD por onza. Script: `backtest/oro_5m_reglas.py`.

| Regla | R:R | Operaciones | Ganadoras | R por operación | Total | 1ª mitad | 2ª mitad |
|---|---|---|---|---|---|---|---|
| S1 retroceso a la EMA20 + tendencia 1h | 2 | 70 | 33% | −0,19 | −13,5R | −8,6R | −4,9R |
| S2 ruptura del rango 15:00-15:30 + tendencia 1h, stop = rango | 2 | 40 | 35% | +0,04 | +1,6R | +3,6R | −2,0R |
| S3 RSI(2) extremo + tendencia | 2 | 55 | 36% | −0,10 | −5,4R | −9,3R | +4,0R |
| **S2c ruptura del rango + tendencia 1h, stop = mitad del rango** | **2** | **40** | **45%** | **+0,27** | **+10,7R** | **+4,8R** | **+5,9R** |
| Entradas al azar (referencia) | 2 | 26 | 27% | −0,12 | −3,2R | | |

Conclusión honesta: S2c es la única que gana en las dos mitades, pero son solo 40
operaciones y fue la mejor de ~11 variantes probadas (sesgo de selección: parte del
resultado puede ser suerte). Es una candidata, no una estrategia probada. Se prueba con
10 operaciones en la demo con 0,25% de riesgo (250 USD) y se anota en
`paper_signals/oro_5m_demo.csv`.

## Reglas de S2c (hora del servidor de MetaTrader)
1. Rango: máximo y mínimo de las velas de 5m de 15:00 a 15:25 (cierra 15:30).
2. Dirección: EMA20 vs EMA50 en 1h (última vela cerrada). Arriba: solo compras; abajo: solo ventas.
3. Entrada: primera vela de 5m (de 15:30 a 18:30) que CIERRA fuera del rango a favor de la
   dirección; se entra a mercado al abrir la siguiente vela. Solo la primera ruptura de cada lado.
4. Stop: a media altura del rango desde la entrada (distancia = (máximo − mínimo) / 2).
5. Objetivo: 2 veces la distancia del stop. Sin cierre parcial (para medir la regla tal cual).
6. Cierre obligatorio a las 20:00 si sigue abierta.
7. Lote = 250 / (distancia del stop × 100).
8. Días de dato fuerte de EE. UU. a las 15:30 (empleo, IPC, Fed): no se opera ese día
   (el backtest no los quitó; es una protección extra).

## Regla del usuario (2026-11-10): EMA20 vs EMA50 en 5m y 15m + ruptura del rango reciente
Dirección: EMA20 bajo EMA50 en 5m y en 15m = solo ventas (y al revés). Entrada: vela de 5m que
cierra fuera del rango de las últimas 6 o 12 velas. Objetivo 2R. Script:
`backtest/oro_5m_regla_usuario.py`.

| Rango | Horario (servidor) | Stop | Operaciones | Total | 1ª mitad | 2ª mitad |
|---|---|---|---|---|---|---|
| 30 min | 09:00-18:30 | medio rango | 313 | −6,1R | +11,8R | −17,9R |
| 30 min | 09:00-18:30 | rango completo | 205 | +0,9R | +13,7R | −12,8R |
| 60 min | 09:00-18:30 | medio rango | 212 | +14,9R | +34,3R | −19,4R |
| 60 min | 09:00-18:30 | rango completo | 133 | +12,3R | +18,2R | −6,0R |
| 30/60 min | 15:00-18:30 | ambos | 64-111 | −5,9R a −10,7R | | |

Conclusión: ganó en la primera mitad (agosto-septiembre) y perdió en la segunda (octubre-noviembre)
en todas las variantes: no es estable. Da ~2-3 operaciones por día (riesgo de sobreoperar).

## Filtros del Trend Meter de TradingView sobre S2c (2026-11-12)
Datos actualizados: 18.995 velas de 5m, del 2026-08-12 al 2026-11-12 (incluye la ganadora del
11-nov). Script: `backtest/oro_5m_trend_meter.py`.

| Variante (objetivo 2R) | Operaciones | Ganadoras | R por op. | Total | 1ª mitad | 2ª mitad |
|---|---|---|---|---|---|---|
| S2c base (dirección EMA20/50 de 1h) | 41 | 46% | +0,31 | +12,5R | +4,8R | +7,8R |
| S2c con dirección EMA240/600 en 5m | 41 | 46% | +0,31 | +12,5R | idéntico | idéntico |
| + 3 puntos del Trend Meter (MACD, RSI13, RSI5) | 34 | 44% | +0,21 | +7,1R | +1,1R | +6,0R |
| + Trend Bar 1 (EMA20/50 de 5m) | 19 | 47% | +0,28 | +5,3R | +0,7R | +4,5R |
| + 3 puntos + Trend Bar 1 | 17 | 53% | +0,44 | +7,4R | +1,8R | +5,6R |

Conclusión: la EMA240/600 en 5m da exactamente las mismas operaciones que la EMA20/50 de 1h
(sirve para ver la dirección en TradingView sin cambiar de gráfica). Los filtros del Trend Meter
quitan operaciones y bajan la ganancia total; la mejora por operación del filtro doble se basa en
17 operaciones (ruido probable). Se mantiene S2c sin filtros.

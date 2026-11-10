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

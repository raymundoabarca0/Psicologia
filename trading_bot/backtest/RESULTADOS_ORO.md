# Oro 1H/15m Liquidez — resultados del backtest (2026-11-18)

Código: `backtest/oro_liquidez.py` (motor) y `backtest/oro_estudio.py` (estudio).
Pine: `pine/Oro_1H_15m_liquidez.pine` (v4 original en el commit 95ce0af, v5 actualizado).
Datos crudos: `resultados_oro/` (json y csv con cada operación).

## Datos y supuestos

- XAU/USD de 15m de Twelve Data, de 2022-12 a 2026-11-18 (93.520 velas). Se quitaron
  los fines de semana y la pausa de 17:00 a 18:00 de Nueva York (desde 2025 el proveedor
  trae velas sintéticas que no existen en MetaTrader). No es el feed de tu broker.
- Costos: spread de 0,30 USD/onza por operación y slippage de 0,10 en la entrada y en
  los stops. Comisión 0.
- La tendencia de 1H y el PDH/PDL usan solo velas cerradas. Se probó cortando los datos
  en 5 fechas: las operaciones anteriores a cada corte salen idénticas (sin look-ahead).
- Entrada en la apertura de la vela siguiente a la señal. Stop/TP dentro de la vela con
  la regla de TradingView; con la regla pesimista (stop primero) el resultado no cambia.
- El resultado se mide en R (1R = distancia al stop). La cuenta de 100 USD con 0,01 lote
  se simula aparte.
- In-sample (IS) = 2023–2024. Fuera de muestra (OOS) = 2025-01-01 a 2026-11-18.

## 1. Script tal cual (v4): NO es rentable después de costos

| | Ops | Acierto | PF | Expectativa | DD máx | Sharpe |
|---|---|---|---|---|---|---|
| 2023–2026 | 564 | 36,5% | 0,95 | −0,025 R | 35,8 R | −0,23 |
| IS 2023–24 | 302 | 30,8% | 0,97 | −0,016 R | 26,3 R | −0,08 |
| OOS 2025–26 | 262 | 43,1% | 0,93 | −0,037 R | 21,4 R | −0,39 |

Por año: 2023 +0,009 R · 2024 −0,047 · 2025 −0,006 · 2026 −0,073.
Sin costos daría +0,055 R por operación: los costos se comen toda la ventaja.

## 2. Filtros (uno a la vez, expectativa en R; error estándar ≈ 0,07–0,11)

| Cambio vs. base | IS | OOS | Veredicto |
|---|---|---|---|
| Base | −0,016 | −0,037 | |
| Quitar tendencia 1H | −0,102 | −0,075 | **Aporta** (el filtro más claro) |
| Quitar confirmación | −0,139 | −0,037 | Aporta (sobre todo en IS) |
| Quitar sesión Londres/NY | −0,060 | −0,025 | Aporta poco |
| Quitar noticias | −0,048 | −0,037 | Aporta poco |
| Quitar rango Asia | −0,017 | +0,011 | Neutro |
| Quitar zonas 50% | −0,013 | −0,014 | Neutro |
| Quitar volatilidad mín. | +0,008 | −0,041 | Neutro / ruido |
| Quitar evitar PDH/PDL | −0,012 | −0,052 | Neutro |
| Sin break-even | −0,006 | +0,017 | BE no ayuda (diferencia chica) |
| BE + trailing | −0,034 | −0,036 | Trailing no ayuda |
| Trailing sin TP | −0,002 | −0,055 | No ayuda |
| TP 1,5R | −0,069 | −0,090 | **Peor** |
| TP 3R | −0,011 | −0,063 | Mixto |
| Supertrend 1H / ADX / pivotes | mixtos o peores | | No activar |

Ningún filtro solo vuelve rentable la base.

## 3. Walk-forward (optimizado en 2023–24, validado en 2025–26 sin tocar)

Rejilla de 324 combinaciones: TP (1,5–3R), stop máx. (1,5–2,5 ATR), velas de
confirmación (2–5), volatilidad mínima (0,5–0,9), margen del stop (0,1–0,3 ATR).
Solo 37% de las combinaciones ganan en IS. Se eligió la de mejor meseta (promedio con sus
vecinas), que coincidió con la mejor bruta: **TP 3R, stop 2,5 ATR, margen 0,1 ATR,
confirmación 2 velas, volatilidad mín. 0,9.**

| | Ops | Acierto* | PF | Expectativa | DD máx | Sharpe | Peor racha |
|---|---|---|---|---|---|---|---|
| IS 2023–24 | 190 | 31,6% | 1,33 | +0,18 R (±0,12) | 14,5 R | 1,08 | 13 |
| **OOS 2025–26** | 173 | 45,1% | 1,26 | **+0,14 R (±0,12)** | 12,5 R | 0,67 | 9 |

\*Incluye cierres en break-even con ganancia pequeña.
Por año: 2023 +0,33 · 2024 −0,01 · 2025 +0,13 · 2026 +0,15 R.
Compras +0,21 R (232); ventas +0,07 R (131). Barridos +0,18; rupturas +0,15.

Chequeos de sobreajuste:
- El ranking de IS predice el de OOS (correlación de rangos 0,78). Lo que funciona es
  consistente: stops más amplios y TP más lejos (los costos pesan menos en R).
- Pero en OOS la combinación típica sigue en −0,015 R, y solo 39% gana.
- Costos más altos: con spread 0,50 queda en +0,12 R OOS; con spread 0,80 y slippage
  0,20, en +0,08 R.
- **+0,14 ± 0,12 R no es estadísticamente distinto de cero** (t ≈ 1,2).
- Todo el periodo fue un mercado alcista del oro (1.800 → 4.000+). Las compras explican
  casi toda la ganancia; en un mercado lateral o bajista el resultado puede ser otro.

## 4. Sensibilidad ±20% (configuración robusta)

Los 24 cambios (±20% en 12 parámetros) siguen positivos en IS y en OOS (OOS entre
+0,04 y +0,20 R). Los más delicados: `rangeLen` +20% (OOS +0,04) y `atrMult` 2,0
(+0,06). Es una meseta, no un pico aislado. En la base (v4), casi todos los cambios
quedan negativos.

## 5. Monte Carlo (1.000 remuestreos de las operaciones OOS)

| | Base v4 | Robusta v5 |
|---|---|---|
| Total en R (mediana; 5%–95%) | −9 (−42 a +21) | +23 (−11 a +58) |
| Prob. de terminar negativo | 70% | 13% |
| Drawdown mediano / peor 5% | 27 R / 50 R | 15 R / 28 R |
| Racha perdedora mediana / peor 5% | 9 / 13 | 7 / 12 |
| Cuenta de 100 USD con 1 onza: prob. de quiebra | 83% | 36% |

## 6. Tu cuenta: 100 USD, 0,01 lote (1 onza), máximo 10% por operación

- Con el oro en 3.700–4.700, el stop típico es de 10–25 USD por onza. Con 100 USD, la
  mayoría de las señales de 2025–26 arriesgan más de 10% y se saltan: 171 saltadas contra
  61 tomadas.
- v5 empezando con 100 USD en 2025-01: termina en 86,56 USD, con un drawdown máximo de
  61%. El riesgo medio fue de 6,9% por operación.
- v4 en el mismo periodo: termina en 57,82 USD, con un drawdown de 77%.
- Esto choca con la regla del experimento (1% por operación). Con 100 USD y lote mínimo
  de 0,01 no se puede arriesgar 1% en oro: haría falta una cuenta cent o micro lotes
  (0,001), o unos 1.500–2.500 USD.
- En el Pine, `max_drawdown` (10%) y `max_intraday_loss` (3%) cortan la estrategia
  después de la primera pérdida si usas lote fijo con 100 USD.

## 7. Prueba extra en 2020-07 a 2022 (oro bajando de 2.070 a 1.620)

| | 2020-07 a 2022 | 2023–24 | 2025–26 |
|---|---|---|---|
| v4 original | +0,038 ± 0,06 | −0,016 | −0,037 |
| v5 robusta | **+0,035 ± 0,09** (258 ops, DD 24,8 R) | +0,18 | +0,14 |
| v5 sin costos | +0,12 | +0,25 | +0,17 |

v5 no pierde en un mercado bajista (las ventas dan +0,17 R), pero en ese periodo su
ventaja casi desaparece después de costos. Sale positiva en los 3 periodos, aunque
débil: no es prueba de ventaja.

## Conclusión

- v4 tal cual: pierde después de costos, dentro y fuera de muestra. No operarla.
- v5: positiva fuera de muestra (+0,14 R), estable ante cambios de ±20% y ante costos
  más altos. Pero la ventaja no es estadísticamente segura y viene de un mercado alcista.
- Siguiente paso recomendado: paper o demo con 1% de riesgo, al menos 100 operaciones,
  antes de usar dinero real. Con 100 USD reales y 0,01 lote, el riesgo por operación es
  demasiado alto.

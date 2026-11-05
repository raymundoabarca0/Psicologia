# Resultados Etapa 2 — Backtest walk-forward

**Veredicto: ninguna de las tres estrategias es apta para pasar a paper trading.** Ninguna muestra una ventaja robusta después de costes.

## Metodología

- **Datos:** Binance Spot, BTC/USDT y ETH/USDT, velas de 4h, del 2020-01-01 al 2026-10-31 (14.975 velas por activo).
  - Hay 2 velas faltantes por activo (el 2020-02-19, que no figura en el historial de Binance).
  - El desplome del 19-may-2021 se **conserva**: es real, y descartarlo ocultaría stops.
- **Walk-forward:** se optimiza 2 años y se prueba 6 meses, avanzando 6 meses cada vez.
  - Hay 10 ventanas de prueba encadenadas, del **2022-01-01 al 2026-10-31**: el bajista de 2022, la recuperación de 2023, el alcista de 2024 y el lateral-bajista de 2025–26.
  - **Todo lo que se reporta abajo es fuera de muestra.**
- **Rejillas pequeñas:** 8–12 combinaciones por estrategia, elegidas por el Sharpe de entrenamiento con al menos 10 operaciones.
- **Costes:** comisión 0,1% por lado, slippage 0,05% y spread 0,02%. Hay una prueba de estrés con todos los costes al doble (x2).
- **Ejecución:**
  - Las señales se calculan al cierre de la vela y se ejecutan en la apertura de la siguiente.
  - Si en una vela se tocan el stop y el take-profit, se asume el stop.
  - Un gap bajo el stop se ejecuta a la apertura.
  - Las entradas pasan por el mismo `RiskManager` y `OrderValidator` del bot real, con los filtros reales de Binance.
- **Benchmark:** 50/50 BTC/ETH comprado al inicio y mantenido: **+13,1%**, con un drawdown máximo del **69,3%**.

## 1. Configuración pedida (riesgo 1%, capital 100 USD, todas las reglas)

| Estrategia | Costes | Retorno | Sharpe | DD máx. | Profit factor | Operaciones | Win rate | Apagado por DD |
|---|---|---|---|---|---|---|---|---|
| A tendencia EMA | x1 | −9,5% | −0,54 | 10,2% | 0,34 | 29 | 17% | 2022-11-08 |
| B Donchian | x1 | −9,1% | −0,47 | 11,5% | 0,50 | 24 | 17% | 2022-06-07 |
| C RSI(2) | x1 | −9,6% | −0,99 | 10,4% | 0,43 | 71 | 51% | 2023-07-05 |

Las tres tocaron el drawdown del 10% y el bot se apagó.
- **Lo que funcionó:** la protección hizo su trabajo. En 2022 comprar y mantener perdió un 66%; el bot perdió alrededor de un 10% y se detuvo.
- **El problema:** con un acierto del 17–35%, una racha de unas 10 pérdidas seguidas es esperable. Con 1% de riesgo por operación, esa racha basta para tocar el 10% de drawdown.

## 2. Diagnóstico: ¿hay ventaja de fondo? (sin apagado por DD, solo análisis)

| Estrategia | Costes | Retorno 2022–26 | Sharpe | DD máx. | Profit factor | Operaciones |
|---|---|---|---|---|---|---|
| A tendencia EMA | x1 | +12,9% | 0,27 | 20,3% | 1,09 | 282 |
| B Donchian | x1 | −3,2% | 0,01 | 18,9% | 0,98 | 226 |
| C RSI(2) | x1 | −29,0% | −1,56 | 29,7% | 0,53 | 308 |
| A tendencia EMA | x2 | −9,7% | −0,12 | 24,8% | 0,92 | 274 |
| B Donchian | x2 | −7,5% | −0,06 | 21,2% | 0,94 | 209 |

Lectura: **A** gana poco (+2,5% anual), pero con un 20% de drawdown, y la ventaja desaparece con costes x2. **B** queda en cero. **C** pierde de forma consistente.

## 3. Riesgo reducido a 0,25% (capital 1.000 USD para no distorsionar con mínimos)

| Estrategia | Costes | Retorno | Sharpe | DD máx. | Profit factor | Operaciones | Win rate |
|---|---|---|---|---|---|---|---|
| A tendencia EMA | x1 | +4,4% | 0,29 | 5,9% | 1,12 | 277 | 35% |
| B Donchian | x1 | +1,9% | 0,13 | 5,2% | 1,05 | 229 | 26% |
| C RSI(2) | x1 | −8,9% | −1,61 | 9,1% | 0,52 | 309 | 58% |
| A tendencia EMA | x2 | −2,7% | −0,17 | 6,9% | 0,92 | 272 | 32% |
| B Donchian | x2 | −0,5% | −0,01 | 5,8% | 0,99 | 210 | 26% |

**Retorno por año (A/B/C, costes x1):**

| Año | A | B | C | Comprar y mantener |
|---|---|---|---|---|
| 2022 | −2,6% | −3,4% | −1,2% | −66,3% |
| 2023 | −1,0% | +4,7% | −1,4% | +124,7% |
| 2024 | +7,3% | +4,1% | −1,8% | +91,0% |
| 2025 | +2,4% | 0,0% | −1,9% | −7,8% |
| 2026 (hasta oct.) | −1,3% | −3,3% | −2,9% | −15,3% |

Con riesgo de 0,25% ninguna estrategia toca el límite de drawdown. Pero A y B rinden menos de 1% anual, y con costes x2 pierden. Eso **no es una ventaja**: el profit factor de 1,05–1,12 está dentro del ruido.

## Otras observaciones honestas

- **Degradación fuera de muestra:**
  - En entrenamiento, B tuvo Sharpe de 0,6–2,0; fuera de muestra, 0,13.
  - Hubo resultados contraintuitivos, como B con costes x2 rindiendo más que con x1 a riesgo de 0,5%. Eso indica que los resultados dependen mucho de la trayectoria y son poco robustos.
- **Capital de 100 USD:** con riesgo de 0,25%, el mínimo de 5 USDT de Binance hace rechazar entre el 25% y el 50% de las señales, lo que sesga el resultado.
  - Con 100 USD, un riesgo de 0,5–1% por operación es lo mínimo operable.
  - Pero con 1%, el límite de drawdown del 10% salta pronto.
- **C (reversión con RSI):** pierde en todos los escenarios. Se descarta.

## Recomendación

No pasar a paper trading con estas estrategias. Opciones:

1. **Ajustar el enfoque, no los parámetros**, por ejemplo con velas diarias. En diario hay menos operaciones y menos costes, y los filtros de tendencia en cripto suelen funcionar mejor en temporalidades largas. Se evaluaría con la misma metodología y sin mirar antes los resultados de prueba.
2. **Usar el bot solo como gestor de riesgo** de una cartera de largo plazo: comprar y mantener con stops de protección. Así el objetivo es limitar caídas como la del 66% de 2022, no "ganarle" al mercado.
3. **Aceptar que no hay ventaja** y no automatizar trading. A veces es la conclusión correcta.

Reproducir:

```bash
python -m backtest.run --capital 100
python -m backtest.run --capital 100 --diagnostic-no-dd-halt
python -m backtest.run --capital 1000 --risk-pct 0.25
```

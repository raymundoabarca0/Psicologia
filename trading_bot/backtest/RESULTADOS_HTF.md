# HTF Level Breakout — resultados (2026-11-18)

Oro (XAU/USD), gráfico de 15m, HTF diario, valores por defecto del script.
Costos: spread de 0,30 USD/onza más 0,10 de slippage. Código: `htf_breakout.py` y
`htf_estudio.py`. Datos: Twelve Data, de 2020-06 a 2026-11 (sin fines de semana).

## Expectativa por operación (R, ± error estándar)

| Variante | 2020-07 a 2022 | 2023–24 | 2025–26 |
|---|---|---|---|
| Script tal cual | −0,045 ± 0,05 | −0,035 ± 0,06 | +0,097 ± 0,06 |
| Sin cierre por hora | **−0,159** ± 0,09 | +0,004 ± 0,11 | +0,184 ± 0,12 |
| Tendencia EMA 200 1H | −0,056 ± 0,06 | −0,056 ± 0,07 | +0,211 ± 0,07 |
| Sesión Londres/NY | −0,054 ± 0,07 | +0,061 ± 0,07 | +0,017 ± 0,08 |
| Sin hora + tendencia | −0,113 ± 0,10 | +0,009 ± 0,12 | +0,383 ± 0,13 |
| Stop ≤ 4 ATR | −0,118 ± 0,11 | −0,005 ± 0,14 | +0,003 ± 0,13 |
| Sin costos | +0,006 | +0,013 | +0,116 |

- Solo gana en 2025–26, cuando el oro subió de 2.600 a 4.300+. En 2020–22, con el oro
  bajando, ganaron las ventas y perdieron las compras: sigue la dirección del mercado,
  no tiene ventaja propia.
- Quitar el cierre por hora parecía mejorar (2023–26), pero en 2020–22 empeora mucho.
- La combinación de filtros elegida con 2023–24 cayó a +0,03 R en 2025–26 (correlación
  de rangos IS–OOS de −0,60: lo que funciona en un periodo falla en el otro).
- Entradas en falso: 34% terminan en el stop completo (−1 R); 52% cierran por la hora.
- Stop en el pivote: la mediana fue de 34 USD/onza en 2025–26 (peor operación −219 USD con
  0,01 lote). Con 100 USD y 0,01 lote, la prob. de quiebra en el Monte Carlo es de 78%.

Conclusión: no tiene ventaja después de costos. No operarla. Ningún filtro probado la
arregla de forma consistente.

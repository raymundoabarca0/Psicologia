# Oro: seguimiento de tendencia en 4h y diario (2026-11-12)

Datos: XAU/USD de Twelve Data, 40.484 velas de 1h del 2020-01-24 al 2026-11-12 (10.553 velas de
4h y 1.811 diarias armadas a la hora del servidor). Costo 0,49 USD por onza por operación.
Script: `backtest/oro_tendencia.py`. Referencia: comprar y mantener = +154% (1.571 a 3.995).

| Regla | Operaciones | Ganadoras | R por op. | Total | Caída máx. | Compras / ventas |
|---|---|---|---|---|---|---|
| T1 D1 Donchian 20/10 (tortuga), stop 2 ATR | 55 | 33% | +0,07 | +3,6R | 8,9R | +17,3 / −13,8 |
| T2 4h cruce EMA20/50 a favor del D1, stop 2 ATR | 96 | 20% | +0,14 | +13,5R | 24,6R | +20,1 / −6,5 |
| T3 4h retroceso a EMA20 a favor de D1 y 4h, objetivo 2R | 247 | 36% | +0,04 | +10,0R | 18,2R | +5,5 / +4,6 |
| **T3 igual, objetivo 3R** | **212** | **30%** | **+0,18** | **+38,0R** | **13,4R** | **+46,2 / −8,3** |

Por año (T3, 3R): 2020 −1,2R; 2021 −9,8R; 2022 −3,3R; 2023 +13,0R; 2024 +14,0R; 2025 +26,4R;
2026 −1,2R.

Conclusión honesta: las cuatro ganan en total, pero casi toda la ganancia viene de 2023-2025, la
gran subida del oro, y de las compras. En 2020-2022 (mercado sin tendencia clara) todas perdieron,
y en 2026 van planas o negativas. Es la regla clásica del seguimiento de tendencia: pierde poco y
seguido en laterales y gana mucho en tendencias largas. T3 con 3R es la mejor candidata (~30
operaciones al año, acierta 30%), pero depende de que haya tendencia y se eligió entre 4 variantes.

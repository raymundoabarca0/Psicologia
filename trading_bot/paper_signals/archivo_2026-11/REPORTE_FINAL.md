# Reporte final del experimento de señales (2026-11-04 al 2026-11-11)

## 1. Simulación (100 USD, 1% de riesgo por operación)
| # | Activo | Tipo | Resultado |
|---|---|---|---|
| 1 | BTC venta límite 81.300 | Cancelada: el precio cayó 5.000 sin llegar a la entrada | 0 |
| 2 | Oro venta límite 4.078 | Stop | −1,00R (−1,00 USD) |
| 3 | Oro compra límite 4.112 | Stop | −0,34R (−0,34 USD) |

- Saldo final: **98,66 USD (−1,34%)**. Ganadoras 0 de 2. Profit factor 0.
- Costo de spread: 0,01 USD (~0,01R por operación): no fue la causa de las pérdidas.
- Calibración de probabilidades: no medible. Las 2 operaciones cerradas eran anteriores a la
  columna `prob`; después del 2026-11-05 no se dio ninguna señal nueva porque ninguna pasó el
  filtro (R:R ≥ 2 y valor esperado positivo con margen).
- Gestión parcial: no llegó a aplicarse en la simulación (ninguna operación tocó +1R).

## 2. Demo del usuario (MetaTrader, 100.000 USD)
| Operación | P&L |
|---|---|
| #2 oro venta (entró tarde, lote 0,10) | −124,30 |
| #3 oro compra (protección: stop a la entrada en +1R) | +14,20 |
| 6-nov venta 1 de oro (plan condicional; mitad en 4.057,66 y resto con stop protegido) | +825,60 |
| 6-nov venta 2 de oro (duplicada, cerrada a mano) | +301,75 |
| **Total** | **+1.017,25 (+1,02%)** |

- Ganadoras 3 de 4; profit factor 9,2.
- Falta registrar la venta de oro en 5m del 2026-11-10 (ganadora, sin captura del historial).
- La protección (#3) convirtió una pérdida de ~1.000 USD en +14. La gestión parcial del 6-nov
  aseguró +676 en la mitad y +149 en el resto cuando el oro rebotó a 4.078.
- Ojo: la mayor parte de la ganancia vino de planes condicionales tomados fuera de horario y con
  una posición duplicada (2% de riesgo en una sola idea). Salió bien, pero no fue según las reglas.

## 3. ¿Se cumplió lo esperado?
- **Dirección**: casi siempre correcta. Oro, euro y BTC siguieron el sesgo bajista (dólar fuerte,
  aversión al riesgo): BTC de 80,5k a 72,9k; oro rechazado dos veces en la EMA50 diaria (4.144).
- **Entradas**: casi nunca en horario. Las zonas de entrada se tocaron de madrugada (02:00-04:00 y
  22:00 del servidor) o el precio se fue sin regresar a la zona. De ~10 planes, 1 se activó en
  horario (6-nov) y 2 fallaron (apertura del lunes con gap; señales #2 y #3).
- Lección: con órdenes límite en zonas lejanas y solo 3,5 h de ventana, la mayoría de las ideas
  correctas no se pueden ejecutar. Hay que revisar la ventana o el tipo de entrada.

## 4. Conclusión honesta
- 3 operaciones simuladas y 4 en la demo son una muestra demasiado pequeña: **no distinguen
  habilidad de suerte**. La simulación perdió −1,34%; la demo ganó +1,02% en buena parte por
  decisiones fuera de las reglas.
- Lo que sí funcionó: la protección (stop a la entrada) y la gestión parcial; no operar en
  aperturas ni en datos fuertes (empleo, IPC).
- Siguiente paso propuesto: la prueba de 10 operaciones de oro en 5m con la regla S2c
  (`backtest/RESULTADOS_ORO_5M.md`), que es mecánica y medible, y seguir el análisis diario solo
  como apoyo.

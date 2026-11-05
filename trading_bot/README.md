# Trading Bot (Binance Spot) — seguridad primero

> **Estado: Etapa 2 de 4.** El backtest walk-forward está listo. **Ninguna de las tres estrategias candidatas mostró una ventaja robusta después de costes.** Ver [`backtest/RESULTADOS_ETAPA2.md`](backtest/RESULTADOS_ETAPA2.md).
> **El bot todavía NO opera.** El paper trading (Etapa 3) solo empezará con una estrategia que pase el backtest.

Prioridades: **1) no perder capital por errores; 2) respetar los límites de riesgo; 3) rentabilidad.**

## Instalación

```bash
cd trading_bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
cp config/.env.example .env      # rellena tus keys de TESTNET; nunca subas .env
python -m pytest                 # todos los tests deben pasar antes de usar nada
```

## Descargar datos históricos

Los datos son públicos: no hace falta API key.

```bash
python -m bot.data.downloader --symbol BTC/USDT --timeframe 4h --since 2020-01-01
python -m bot.data.downloader --symbol ETH/USDT --timeframe 4h --since 2020-01-01
```

Los datos se guardan en `data/*.parquet`. Esa carpeta no se sube a git.

Si `api.binance.com` no es accesible desde tu red (por ejemplo, desde servidores en EE. UU.), usa el espejo público de datos con `--public-api https://data-api.binance.vision/api/v3`.

## Backtest

```bash
python -m backtest.run --capital 100                      # todas las reglas activas
python -m backtest.run --capital 100 --risk-pct 0.5       # riesgo más bajo (permitido)
python -m backtest.run --capital 100 --diagnostic-no-dd-halt   # SOLO análisis
```

El backtest hace walk-forward (2 años de entrenamiento y 6 meses de prueba), con comisión, slippage y spread, más una prueba de estrés con costes al doble. Los reportes se guardan en `reports/`.

## Configuración

- **Parámetros:** van en `config/config.yaml`. Cualquier clave desconocida hace fallar el arranque, así un error de escritura no pasa desapercibido.
- **Secretos:** van solo en `.env` o en variables de entorno. Si pones una API key en el YAML, el arranque se rechaza.
- **Límites duros:** están en `bot/risk/hard_limits.py`. El YAML solo puede **endurecerlos**; si intentas relajarlos, la configuración se rechaza.

| Límite | Valor duro |
|---|---|
| Riesgo por operación | 1% del equity (incluye comisiones y slippage en el peor caso) |
| Pérdida diaria | 3% → pausa hasta el día siguiente |
| Drawdown desde el máximo | 10% → apagado; crea el archivo `HALTED` y exige reinicio manual |
| Posiciones simultáneas | 3 |
| Operaciones por día | 10 (4 por defecto) |
| Apalancamiento | ninguno (1x, solo spot y solo largos) |

### Modo real: doble llave

El bot opera con dinero real **solo** si se cumplen las dos condiciones:

1. `live_trading: true` en `config/config.yaml`, **y**
2. `LIVE_TRADING=true` en el entorno.

Si falta cualquiera de las dos, arranca en modo simulado. En modo simulado nunca se leen las keys reales (`BINANCE_API_KEY`), solo las de testnet.

## Seguridad de las API keys

- Crea las keys con permiso de **trading** y **sin permiso de retiro**.
- Restríngelas por IP: usa la IP fija del servidor donde corra el bot.
- Usa keys distintas para testnet y para real.
- Si sospechas que una key se filtró, revócala en Binance de inmediato.

## Cómo detener el bot

| Acción | Efecto |
|---|---|
| `touch KILL` en la carpeta del bot | Cancela órdenes, cierra posiciones y detiene el bot en el siguiente ciclo. |
| Ctrl+C / `kill <pid>` | Detiene el proceso. Las órdenes stop ya colocadas **siguen en el exchange** protegiendo las posiciones. |
| Revocar la API key en Binance | Último recurso: el bot pierde todo acceso. |

Si existe el archivo `HALTED`, el bot se niega a arrancar. Antes de borrarlo, revisa los logs y entiende qué pasó.

*(El bucle de ejecución que consulta estos archivos llega en la Etapa 3.)*

## Arquitectura

```
Estrategia ──Signal──▶ RiskManager ──qty──▶ OrderValidator ──▶ Executor ──▶ Exchange
 (solo propone)      (última palabra)      (mínimos, precisión,
                                            saldo, precio ±1%)
```

| Módulo | Responsabilidad |
|---|---|
| `bot/config.py` | Carga y valida el YAML, resuelve el modo (paper o real) y carga los secretos. |
| `bot/risk/sizing.py` | Calcula el tamaño de posición: (equity × 1%) / pérdida por unidad en el peor caso. Redondea siempre hacia abajo. |
| `bot/risk/limits.py` | Controla la pérdida diaria, el drawdown desde el pico y el contador de operaciones. Su estado es persistible. |
| `bot/risk/manager.py` | Aprueba o rechaza cada entrada. Por defecto rechaza. |
| `bot/execution/order_validator.py` | Valida step, tick, mínimos, saldo y desviación de precio; genera los `clientOrderId` deterministas. |
| `bot/data/validator.py` | Descarta duplicados, OHLC inválido, picos aislados y velas no cerradas; detecta huecos y datos viejos. |
| `bot/data/downloader.py` | Descarga paginada con reintentos y backoff. |
| `bot/safety/kill_switch.py` | Gestiona los archivos `KILL` y `HALTED`. |
| `bot/utils/retry.py` | Backoff exponencial. Solo reintenta errores de red, nunca errores lógicos. |

## Tests

```bash
python -m pytest
```

Los tests cubren, entre otras cosas:
- que el riesgo nunca supere el 1%;
- el redondeo hacia abajo de la cantidad;
- los límites diario y de drawdown, y que este último sea permanente;
- que no se promedien pérdidas;
- la doble llave del modo real;
- la validación de órdenes;
- la idempotencia de los IDs;
- la limpieza de datos;
- los reintentos.

## Limitaciones conocidas (honestas)

- **Stops en spot:** hay un intervalo breve entre el llenado de la entrada y la colocación del stop. Si el stop no se puede colocar, el bot cerrará la posición a mercado (Etapa 3).
- **Gaps:** un stop-limit puede quedar sin ejecutar si el precio salta por debajo del límite. Por eso el límite se coloca un 0,5% por debajo del trigger, pero aun así el riesgo real puede superar el 1% en un gap extremo.
- **Rentabilidad:** ninguna estrategia está validada todavía. Los resultados del backtest se publicarán tal cual, sean buenos o malos.

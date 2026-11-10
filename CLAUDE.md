# Contexto para Claude

Este repositorio tiene dos cosas:
- `PaginaWebAGR.html`: página web (no tocar salvo que el usuario lo pida).
- `trading_bot/`: bot de trading y experimento de señales en paper. Rama de trabajo:
  `claude/new-session-1mlq7o` (desde el 2026-11-05; parte del mismo commit que
  `claude/python-automated-trading-bot-jgl2zz`, que queda como rama anterior; juntarlas al
  final del experimento).

El usuario habla español (México). Prioridad absoluta: proteger el capital y evitar
errores; la rentabilidad es secundaria. Ser honesto: si algo no funciona o pierde, decirlo.

## Límites acordados con el usuario

- No operar por el usuario: él confirma y coloca cada orden a mano (desde el celular).
- Sin scalping: nada de 1m ni 5m. Solo 15m, 30m, 1h, 4h (y D1 para dirección).
  Excepción pedida por el usuario el 2026-11-10: prueba de 10 operaciones de oro en 5m en la
  demo con 0,25% de riesgo (250 USD), regla S2c (ruptura del rango 15:00-15:30). Ver
  `trading_bot/backtest/RESULTADOS_ORO_5M.md`; registro en `paper_signals/oro_5m_demo.csv`.
- No borrar nada del repositorio Psicologia; se deja como está.
- Caveman mode activo por defecto (señales y advertencias completas); "normal mode" lo quita.
- Capital real previsto: 100 USD; todavía no opera con dinero real.

## Estado (2026-11-05)

- Etapa 1 (riesgo, validación de órdenes y datos) y Etapa 2 (backtest walk-forward) hechas.
  Resultado de la Etapa 2: ninguna estrategia simple (EMA, Donchian, RSI2) tiene ventaja
  después de costos. Ver `trading_bot/backtest/RESULTADOS_ETAPA2.md`.
- En curso: experimento de señales discrecionales en paper, del 2026-11-04 al 2026-11-11.
  - Registro: `trading_bot/paper_signals/signals.csv` (nunca editar señales pasadas, salvo
    `manual_close_utc` con la hora ACTUAL; leer esa columna con dtype string).
  - Vigilancia sin señal: `trading_bot/paper_signals/watch.json`.
  - Resultados de la demo del usuario: `trading_bot/paper_signals/demo_usuario.csv`.
  - Herramientas (analyze incluye TREND METER -100..+100, medidor de VOLATILIDAD
    —percentil del ATR14 en 200 velas— y un TABLERO final con ambos, desde el 2026-11-10): `python -m paper_signals.analyze 1d 4h` / `1h 30m 15m`,
    `python -m paper_signals.evaluate`, `python -m paper_signals.charts` (desde `trading_bot/`).
  - Al 2026-11-05: 2 operaciones cerradas, ambas perdedoras (simulación 98,66 USD de 100).
  - Demo del usuario al 2026-11-06: saldo 101.017,25 USD (+1.017,25). El 6-nov ganó +1.127 en
    dos ventas de oro tomadas de planes condicionales (no señales), una de ellas duplicada.
- Twelve Data conectado (2026-11-06): la API key la inyecta el proxy en `api.twelvedata.com`
  (no hay variable de entorno). Plan basic: 8 peticiones/min, 800/día. XAU/USD y EUR/USD
  funcionan. Pasar siempre `timezone=UTC` (por defecto devuelve otra zona horaria).
  Al conectar: XAU/USD ≈ PAXG + 1,3 (varía de +1 a +11); EUR/USD ≈ EURUSDT − 11 pips.
  Integrado en `paper_signals/market.py`: ORO = XAU/USD y EUR = EUR/USD (Twelve Data), BTC sigue
  en Binance. Las señales viejas (PAXGUSDT, EURUSDT) se evalúan con Binance. Velas 4h y D1 de
  Twelve Data se arman desde 1h alineadas a la hora del servidor (UTC+2); se quitan las velas
  planas del fin de semana. La diferencia con el broker del usuario hay que recalcularla contra
  XAU/USD y EUR/USD (pedirle su precio actual).
- Datos: espejo público de Binance `data-api.binance.vision` (api.binance.com bloquea los
  servidores de EE. UU.). Hasta el 2026-11-05: oro = PAXGUSDT, euro = EURUSDT; BTC = BTCUSDT.

## Reglas del experimento (acordadas con el usuario)

- Simulación: 100 USD, riesgo 1% por operación, sin apalancamiento, costos de spread tipo broker.
- Demo del usuario: MetaTrader, saldo 100.000 USD, riesgo 1% = 1.000 USD.
  Oro: 100 onzas por lote (lotes = 1000 / (distancia al stop × 100)).
  Euro: 100.000 por lote (lotes = 1000 / (pips × 10)). BTC: tamaño de contrato por confirmar.
- Diferencia de precios con su broker (aprox., recalcular con un precio actual):
  XAUUSD (su símbolo es "Gold Spot") ≈ XAU/USD de Twelve Data, diferencia ~0 (medido el
  2026-11-06 19:33 del servidor: Bid 4.061,79 / Ask 4.062,13 vs XAU/USD 4.061,9). Su spread
  de oro ≈ 0,34. EURUSD contra EUR/USD: por medir. BTCUSD ≈ BTCUSDT − 37 (contra Binance).
  Dar siempre los niveles en mis precios y en los de su broker.
- Horas: siempre en hora del servidor de MetaTrader (UTC+2 = México + 8 h), formato
  AAAA.MM.DD HH:MM; opcionalmente la de México entre paréntesis.
- Temporalidades: D1 y 4h = dirección; 1h = setup (principal); 30m y 15m = entrada y stop.
  Solo entrar a favor de D1/4h.
- Gestión `parcial` en toda señal nueva: en +1R cerrar 50% y stop del resto a la entrada;
  en +1,5R stop del resto a +0,5R; el resto busca el take-profit.
- Cada señal lleva probabilidad (`prob`) y valor esperado; solo señales con EV positivo con
  margen y R:R ≥ 2. "No operar" es válido; si no hay ventaja, dar planes condicionales.
- No comprar justo debajo de una resistencia del diario ni vender justo encima de un soporte.
- Oro y euro: vender ambos (o comprar ambos) es la misma apuesta al dólar; no duplicar.
- Máximo una señal por activo a la vez; máximo 3% de pérdida diaria.
- Horario recomendado: 15:00–18:30 del servidor (07:00–10:30 México). Evitar 15 min antes y
  30 min después de datos fuertes de EE. UU. (suelen ser a las 15:30 del servidor; el empleo
  sale el primer viernes del mes) y de 23:00 a 01:00 del servidor (spreads altos).
- Fines de semana: oro y euro no cotizan en MetaTrader (viernes ~22:00 UTC a domingo
  ~22:00 UTC); no abrir oro ni euro el viernes después de las 20:00 del servidor.
- Noticias: `get_upcoming_macro_events` de CoinMarketCap como contexto (no es calendario
  oficial); recomendar confirmar en Forex Factory o Investing.com.

## Análisis diario

Tarea programada diaria a las 12:10 UTC (14:10 del servidor), en la sesión del 2026-11-05
(rama `claude/new-session-1mlq7o`). Si esta es una sesión nueva,
el usuario puede pedir recrearla aquí; en ese caso borrar la de la sesión anterior para no
duplicar. El 2026-11-11: reporte final honesto y preguntar si se continúa.

## Skills instaladas (`.claude/skills/`)

caveman (respuestas cortas; las señales y advertencias van siempre completas) y, de
HKUDS/Vibe-Trading (MIT): technical-basic, candlestick, smc, ichimoku, volatility,
commodity-analysis, research-discipline, behavioral-finance. Son guías de metodología, sin
ventaja probada. Antes de decidir, aplicar research-discipline (buscar evidencia en contra).
No instalar AI-Trader (HKUDS): sus skills reciben instrucciones de un servidor externo.
No instalar OmniRoute (cheaper-inference): pasarela de modelos de IA que maneja claves y
puede interceptar HTTPS; no aporta al trading (decidido el 2026-11-06).

## Pendientes

- Cuenta Paper de Interactive Brokers con 10.000 USD y su conector.
- Etapa 3 (paper trading automático del bot) solo con una estrategia que pase el backtest.

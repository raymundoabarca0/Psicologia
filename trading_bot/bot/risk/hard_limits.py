"""Límites duros de riesgo.

Estos valores están en el código a propósito: la configuración (YAML) solo puede
hacerlos MÁS estrictos, nunca relajarlos. La validación de configuración rechaza
cualquier valor que los supere, y el RiskManager vuelve a aplicarlos en tiempo de
ejecución (defensa en profundidad).

Cambiar estos valores requiere modificar el código y pasar por revisión.
"""

from __future__ import annotations

from typing import Final

# Riesgo máximo por operación, en % del capital (equity).
MAX_RISK_PER_TRADE_PCT: Final[float] = 1.0

# Pérdida diaria máxima, en % del equity al inicio del día -> pausa hasta el día siguiente.
MAX_DAILY_LOSS_PCT: Final[float] = 3.0

# Drawdown máximo desde el máximo histórico de equity -> apagado, reinicio manual.
MAX_DRAWDOWN_PCT: Final[float] = 10.0

# Máximo de posiciones abiertas simultáneas.
MAX_OPEN_POSITIONS: Final[int] = 3

# Máximo de operaciones (entradas) por día.
MAX_TRADES_PER_DAY: Final[int] = 10

# Sin apalancamiento: la exposición total no puede superar el equity.
MAX_LEVERAGE: Final[float] = 1.0

# Una posición individual no puede superar este % del equity.
MAX_POSITION_PCT_OF_EQUITY: Final[float] = 100.0

# Desviación máxima permitida entre el precio de la orden y el último precio.
MAX_PRICE_DEVIATION_PCT: Final[float] = 5.0

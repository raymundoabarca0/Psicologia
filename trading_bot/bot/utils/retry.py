"""Reintentos con backoff exponencial (y jitter opcional)."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)


def retry_call(
    fn: Callable[..., T],
    *args,
    retries: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    jitter: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> T:
    """Llama a fn; si lanza una excepción de `retry_on`, reintenta hasta `retries` veces.

    Esperas: base, 2*base, 4*base... (acotado a max_delay). Las excepciones que no
    están en `retry_on` se propagan inmediatamente (p. ej. errores de validación,
    fondos insuficientes: reintentar no los arregla).
    """
    if retries < 0:
        raise ValueError("retries debe ser >= 0")
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except retry_on as exc:
            if attempt >= retries:
                log.error("Fallo definitivo tras %d reintentos: %r", retries, exc)
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            if jitter:
                delay *= random.uniform(0.8, 1.2)
            log.warning("Error %r (intento %d/%d); reintento en %.1fs",
                        exc, attempt + 1, retries, delay)
            sleep(delay)
            attempt += 1

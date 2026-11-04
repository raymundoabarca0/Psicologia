"""Kill switch y halt persistente basados en archivos.

- KILL: si existe este archivo, el bot cancela órdenes, cierra posiciones y se
  detiene de inmediato (lo consulta en cada ciclo). Crear: `touch KILL`.
- HALTED: lo escribe el bot cuando se alcanza el drawdown máximo (u otro error
  grave). Mientras exista, el bot se NIEGA a arrancar. Solo se borra a mano,
  después de revisar qué pasó.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class KillSwitch:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def is_triggered(self) -> bool:
        return self.path.exists()

    def trigger(self, reason: str) -> None:
        self.path.write_text(f"{datetime.now(timezone.utc).isoformat()} {reason}\n",
                             encoding="utf-8")


class HaltFile:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def is_halted(self) -> bool:
        return self.path.exists()

    def reason(self) -> str | None:
        return self.path.read_text(encoding="utf-8").strip() if self.path.exists() else None

    def halt(self, reason: str) -> None:
        # Nunca sobrescribir un halt previo: se conserva la causa original.
        if self.path.exists():
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now(timezone.utc).isoformat()} {reason}\n")
        else:
            self.path.write_text(f"{datetime.now(timezone.utc).isoformat()} {reason}\n",
                                 encoding="utf-8")

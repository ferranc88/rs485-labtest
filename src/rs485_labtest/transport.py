"""Abstraccio de transport serie.

El ``TestEngine`` i el slave treballen contra la interficie minima
``Transport`` en lloc de ``serial.Serial`` directament. Aixo permet:

- tests d'integracio amb ptys sense hardware;
- un transport fals injectable que simuli DUTs defectuosos.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

try:
    import serial
except ImportError:  # pragma: no cover - nomes sense pyserial instal.lat
    serial = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import serial as serial_mod


class WriteTimeout(Exception):
    """El ``write`` ha vencut el write_timeout (buffer de sortida ple)."""


class BaudNotSupported(Exception):
    """L'adaptador/driver no ha pogut fixar el baud rate demanat.

    Tipic amb bauds molt alts o no estandard (p.ex. 307200): cada xip te el
    seu maxim i la seva graella de divisors. Vegeu ``docs/SETUP.md``.
    """


@runtime_checkable
class Transport(Protocol):
    """Interficie minima que necessita el motor de tests."""

    baudrate: int

    @property
    def in_waiting(self) -> int: ...

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def flush(self) -> None: ...

    def reset_input_buffer(self) -> None: ...

    def reset_output_buffer(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """Adaptador de ``serial.Serial`` a la interficie ``Transport``.

    Tradueix ``serial.SerialTimeoutException`` a :class:`WriteTimeout` perque
    el motor no depengui de pyserial.
    """

    def __init__(self, ser: serial_mod.Serial) -> None:
        self._ser = ser

    @property
    def baudrate(self) -> int:
        return self._ser.baudrate

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        try:
            self._ser.baudrate = value
        except (ValueError, OSError) as exc:
            raise BaudNotSupported(
                f"l'adaptador no ha pogut fixar {value} bps: {exc}") from exc

    @property
    def in_waiting(self) -> int:
        return self._ser.in_waiting

    def read(self, size: int = 1) -> bytes:
        return self._ser.read(size)

    def write(self, data: bytes) -> int | None:
        try:
            return self._ser.write(data)
        except serial.SerialTimeoutException as exc:  # type: ignore[union-attr]
            raise WriteTimeout(str(exc)) from exc

    def flush(self) -> None:
        self._ser.flush()

    def reset_input_buffer(self) -> None:
        self._ser.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        self._ser.reset_output_buffer()

    def close(self) -> None:
        self._ser.close()


def open_port(port: str, baud: int, parity: str = "N",
              stopbits: float = 1) -> SerialTransport:
    """Obre un port serie amb la configuracio del banc (timeout curt, WT 2 s)."""
    if serial is None:
        raise RuntimeError("Falta pyserial:  pip install pyserial")
    p = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}[parity]
    s = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE,
         2: serial.STOPBITS_TWO}[stopbits]
    try:
        ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity=p,
                            stopbits=s, timeout=0.01, write_timeout=2)
    except (ValueError, OSError) as exc:
        # separem "no puc obrir el port" de "no puc amb aquest baud"
        if isinstance(exc, ValueError) or "baud" in str(exc).lower():
            raise BaudNotSupported(
                f"no s'ha pogut obrir {port} a {baud} bps: {exc}\n"
                f"  - cada xip te el seu maxim: FTDI FT232R fins ~3M, "
                f"FT2232H/FT232H fins 12M; CP210x ~2M; CH340 ~2M.\n"
                f"  - els bauds no estandard (p.ex. 307200) es generen amb "
                f"divisor fraccionari; RS-485 tolera <~2-3% de desajust.\n"
                f"  - a Linux baixa el latency_timer a 1 (vegeu docs/SETUP.md)."
            ) from exc
        raise
    time.sleep(0.15)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return SerialTransport(ser)

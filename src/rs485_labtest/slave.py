"""Extrem B del banc: escolta, fa eco i obeeix CMD_BAUD."""

from __future__ import annotations

import logging
import struct
import time

from .protocol import T_ACK, T_CMD_BAUD, T_DATA, FrameReader, build_frame
from .transport import Transport, open_port

log = logging.getLogger(__name__)


def run_slave(port: str, baud: int, parity: str = "N", stopbits: float = 1,
              turnaround_us: int = 0, transport: Transport | None = None) -> None:
    """Bucle d'eco. S'atura amb Ctrl-C.

    ``transport`` permet injectar un transport ja obert (tests); si es None,
    s'obre ``port`` amb pyserial.
    """
    ser = transport if transport is not None else open_port(port, baud, parity, stopbits)
    reader = FrameReader()
    rx_ok = 0
    log.info("[slave] %s @ %s bps - escoltant (Ctrl-C surt)", port, baud)
    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            for ftype, seq, payload in reader.feed(data):
                if ftype == T_DATA:
                    rx_ok += 1
                    if turnaround_us:
                        time.sleep(turnaround_us / 1e6)
                    ser.write(build_frame(T_DATA, seq, payload))
                    ser.flush()
                elif ftype == T_CMD_BAUD:
                    new_baud = struct.unpack("<I", payload)[0]
                    ser.write(build_frame(T_ACK, seq, payload))
                    ser.flush()
                    time.sleep(0.10)          # deixar sortir l'ACK del cable
                    ser.baudrate = new_baud
                    ser.reset_input_buffer()
                    log.info("[slave] baud -> %s", new_baud)
                if rx_ok and rx_ok % 2000 == 0:
                    log.info("[slave] eco=%s crc_err=%s junk=%sB",
                             rx_ok, reader.crc_errors, reader.junk)
    except KeyboardInterrupt:
        log.info("[slave] fi. eco=%s crc_err=%s junk=%sB",
                 rx_ok, reader.crc_errors, reader.junk)
    finally:
        ser.close()

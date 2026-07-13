"""Protocol de trama del banc de proves RS-485.

Trama::

    A5 | tipus | seq(32b LE) | len(16b LE) | payload | CRC16-CCITT-FALSE (LE)

Tipus: ``0x00`` DATA (eco), ``0x01`` CMD_BAUD (canvi de baud remot), ``0x02`` ACK.

El format es contractual: els informes generats amb l'script v2.0 han de
seguir sent comparables amb els nous. No canvieu cap camp ni l'ordre de bytes.
"""

from __future__ import annotations

import struct

SOF = 0xA5
T_DATA, T_CMD_BAUD, T_ACK = 0x00, 0x01, 0x02
HDR = struct.Struct("<BBIH")            # SOF, type, seq, len
HDR_LEN = HDR.size
MAX_PAYLOAD = 1024


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_frame(ftype: int, seq: int, payload: bytes = b"") -> bytes:
    """Construeix una trama completa (capcalera + payload + CRC)."""
    body = HDR.pack(SOF, ftype, seq & 0xFFFFFFFF, len(payload)) + payload
    return body + struct.pack("<H", crc16(body))


class FrameReader:
    """Parser resincronitzable. Compta cada byte fora de trama valida (junk).

    El comptador ``junk`` es la metrica clau del banc: amb el bus en repos ha
    de ser 0, i si no ho es, apunta directament a bias de failsafe insuficient.
    """

    def __init__(self) -> None:
        self.buf = bytearray()
        self.junk = 0
        self.crc_errors = 0

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        frames: list[tuple[int, int, bytes]] = []
        self.buf.extend(data)
        while True:
            i = self.buf.find(bytes([SOF]))
            if i < 0:
                self.junk += len(self.buf)
                self.buf.clear()
                break
            if i > 0:
                self.junk += i
                del self.buf[:i]
            if len(self.buf) < HDR_LEN:
                break
            _, ftype, seq, length = HDR.unpack(bytes(self.buf[:HDR_LEN]))
            if length > MAX_PAYLOAD or ftype > T_ACK:
                self.junk += 1
                del self.buf[:1]
                continue
            total = HDR_LEN + length + 2
            if len(self.buf) < total:
                break
            frame = bytes(self.buf[:total])
            rx_crc = struct.unpack("<H", frame[-2:])[0]
            if rx_crc == crc16(frame[:-2]):
                del self.buf[:total]
                frames.append((ftype, seq, frame[HDR_LEN:-2]))
            else:
                # CRC dolent: pot ser trama corrupta o fals SOF; resync byte a byte
                self.crc_errors += 1
                self.junk += 1
                del self.buf[:1]
        return frames

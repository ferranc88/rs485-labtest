"""Transport fals i DUTs simulats per testejar el motor sense hardware.

El `FakeTransport` fa de "cable + extrem remot": el que el master escriu
passa al DUT simulat, i el que el DUT emet queda en cua de lectura (amb
retard opcional per simular turnarounds lents).
"""

from __future__ import annotations

import random
import struct
import time
from typing import Any

from rs485_labtest.protocol import T_ACK, T_CMD_BAUD, T_DATA, FrameReader, build_frame
from rs485_labtest.transport import BaudNotSupported


class FakeTransport:
    """Implementacio en memoria de la interficie Transport.

    ``max_baud`` simula el sostre d'un adaptador real: fixar un baud per sobre
    llenca ``BaudNotSupported``, com faria el driver amb un baud massa alt.
    """

    def __init__(self, dut: BaseDUT, baudrate: int = 115200,
                 max_baud: int | None = None) -> None:
        self.dut = dut
        self.max_baud = max_baud
        self._baud = baudrate
        self.rx = bytearray()
        self.pending: list[tuple[float, bytes]] = []   # (instant_llest, dades)
        self.closed = False

    @property
    def baudrate(self) -> int:
        return self._baud

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        if self.max_baud is not None and value > self.max_baud:
            raise BaudNotSupported(f"{value} > sostre {self.max_baud}")
        self._baud = value

    # ---- costat DUT ----
    def deliver(self, data: bytes, delay_s: float = 0.0) -> None:
        """El DUT posa bytes 'al cable' cap al master."""
        if delay_s:
            self.pending.append((time.monotonic() + delay_s, bytes(data)))
        else:
            self.rx.extend(data)

    def _pump(self) -> None:
        now = time.monotonic()
        self.dut.on_poll(self, now)
        if self.pending:
            ready = [d for t, d in self.pending if t <= now]
            if ready:
                self.pending = [(t, d) for t, d in self.pending if t > now]
                for d in ready:
                    self.rx.extend(d)

    # ---- interficie Transport (costat master) ----
    @property
    def in_waiting(self) -> int:
        self._pump()
        return len(self.rx)

    def read(self, size: int = 1) -> bytes:
        self._pump()
        if not self.rx:
            time.sleep(0.002)          # emula el timeout curt del port real
            self._pump()
        data = bytes(self.rx[:size])
        del self.rx[:size]
        return data

    def write(self, data: bytes) -> int:
        self.dut.on_write(bytes(data), self)
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self._pump()
        if self.rx:
            # bytes d'eco descartats sense llegir: per al DUT es una colisio
            self.dut.on_discard(len(self.rx))
        self.rx.clear()

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class BaseDUT:
    """Comportament d'eco perfecte; les subclasses hi injecten defectes."""

    def __init__(self) -> None:
        self.reader = FrameReader()

    def on_write(self, data: bytes, tp: FakeTransport) -> None:
        for ftype, seq, payload in self.reader.feed(data):
            self.handle_frame(ftype, seq, payload, tp)

    def handle_frame(self, ftype: int, seq: int, payload: bytes,
                     tp: FakeTransport) -> None:
        if ftype == T_DATA:
            tp.deliver(build_frame(T_DATA, seq, payload))
        elif ftype == T_CMD_BAUD:
            tp.deliver(build_frame(T_ACK, seq, payload))

    def on_poll(self, tp: FakeTransport, now: float) -> None:
        pass

    def on_discard(self, nbytes: int) -> None:
        pass


class PerfectDUT(BaseDUT):
    """Eco net i immediat: tot ha de donar PASS."""


class NoisyIdleDUT(BaseDUT):
    """Emet bytes espuris amb el bus en repos (bias de failsafe insuficient).

    `idle_monitor` ha de donar FAIL.
    """

    def __init__(self, rate_bps: float = 2000.0, seed: int = 42) -> None:
        super().__init__()
        self.rate = rate_bps
        self.rng = random.Random(seed)
        self._last: float | None = None

    def on_poll(self, tp: FakeTransport, now: float) -> None:
        if self._last is None:
            self._last = now
            return
        n = int((now - self._last) * self.rate)
        if n:
            self._last = now
            tp.deliver(bytes(self.rng.getrandbits(8) for _ in range(n)))


class SlowTurnaroundDUT(BaseDUT):
    """Retard llarg abans de l'eco: provoca timeouts a turnaround_gap0."""

    def __init__(self, delay_s: float = 0.3) -> None:
        super().__init__()
        self.delay_s = delay_s

    def handle_frame(self, ftype: int, seq: int, payload: bytes,
                     tp: FakeTransport) -> None:
        if ftype == T_DATA:
            tp.deliver(build_frame(T_DATA, seq, payload), delay_s=self.delay_s)
        else:
            super().handle_frame(ftype, seq, payload, tp)


class BitFlipDUT(BaseDUT):
    """Corromp bits de l'eco amb probabilitat p per bit.

    - `recompute_crc=False`: corromp la trama sencera -> errors de CRC/junk.
    - `recompute_crc=True`: corromp nomes el payload i recalcula el CRC ->
      trames valides amb payload equivocat (mismatch), el cas mes perillos.
    """

    def __init__(self, p: float = 0.02, seed: int = 7,
                 recompute_crc: bool = False) -> None:
        super().__init__()
        self.p = p
        self.rng = random.Random(seed)
        self.recompute_crc = recompute_crc

    def _flip(self, data: bytes) -> bytes:
        out = bytearray(data)
        for i in range(len(out)):
            for bit in range(8):
                if self.rng.random() < self.p:
                    out[i] ^= 1 << bit
        return bytes(out)

    def handle_frame(self, ftype: int, seq: int, payload: bytes,
                     tp: FakeTransport) -> None:
        if ftype != T_DATA:
            super().handle_frame(ftype, seq, payload, tp)
            return
        if self.recompute_crc:
            tp.deliver(build_frame(T_DATA, seq, self._flip(payload)))
        else:
            tp.deliver(self._flip(build_frame(T_DATA, seq, payload)))


class BaudSensitiveDUT(BaseDUT):
    """Eco correcte nomes si el baud del master es prou a prop del nominal.

    Simula el pressupost de tolerancia d'un link real: mes enlla de
    ``tolerance_pct`` el que "arriba" es brossa, com faria un UART desajustat.
    """

    def __init__(self, nominal: int = 115200, tolerance_pct: float = 1.5,
                 seed: int = 99) -> None:
        super().__init__()
        self.nominal = nominal
        self.tolerance_pct = tolerance_pct
        self.rng = random.Random(seed)

    def on_write(self, data: bytes, tp: FakeTransport) -> None:
        off_pct = abs(tp.baudrate - self.nominal) / self.nominal * 100.0
        if off_pct > self.tolerance_pct:
            # desajust excessiu: la trama arriba com a soroll
            n = max(1, len(data) // 2)
            tp.deliver(bytes(self.rng.getrandbits(8) for _ in range(n)))
            return
        super().on_write(data, tp)


class LatchUpDUT(BaseDUT):
    """Deixa de respondre despres d'una colisio: post_collision ha de donar FAIL.

    La colisio es detecta quan el master descarta un eco sense haver-lo llegit
    (reset_input_buffer amb bytes pendents), que es exactament el que passa en
    el test collision_blind.
    """

    def __init__(self) -> None:
        super().__init__()
        self.latched = False

    def handle_frame(self, ftype: int, seq: int, payload: bytes,
                     tp: FakeTransport) -> None:
        if self.latched:
            return
        super().handle_frame(ftype, seq, payload, tp)

    def on_discard(self, nbytes: int) -> None:
        if nbytes:
            self.latched = True


def unpack_baud(payload: bytes) -> int:
    """Ajuda per als tests de CMD_BAUD."""
    return struct.unpack("<I", payload)[0]


def make_result(**overrides: Any) -> dict[str, Any]:
    """Resultat de test 'net' per construir casos de verdict()."""
    res: dict[str, Any] = dict(
        name="t", pattern="random", size=64, gap_ms=0, duration_s=1.0,
        baud=115200, collide=False, tx=100, ok=100, crc_err=0, mismatch=0,
        seq_err=0, timeout=0, junk_bytes=0, latencies_ms=[1.0] * 100)
    res.update(overrides)
    return res

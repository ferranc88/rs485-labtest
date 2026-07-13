"""Motor de tests: intercanvis master<->slave i primitives de mesura."""

from __future__ import annotations

import random
import struct
import time
from typing import Any

from .patterns import make_payload
from .protocol import T_ACK, T_CMD_BAUD, T_DATA, FrameReader, build_frame
from .transport import Transport, WriteTimeout


class TestEngine:
    """Executa tests contra el slave i acumula resultats."""

    def __init__(self, ser: Transport, seed: int, quiet: bool = False) -> None:
        self.ser = ser
        self.rng = random.Random(seed)
        self.seq = 0
        self.quiet = quiet

    # ---- primitives ----
    def _exchange(self, ftype: int, payload: bytes,
                  timeout: float) -> tuple[str, float | None, FrameReader]:
        """Envia una trama i espera la resposta. Retorna (status, rtt_ms, reader)."""
        reader = FrameReader()
        self.ser.reset_input_buffer()
        frame = build_frame(ftype, self.seq, payload)
        t0 = time.perf_counter()
        self.ser.write(frame)
        self.ser.flush()
        deadline = t0 + timeout
        while time.perf_counter() < deadline:
            data = self.ser.read(self.ser.in_waiting or 1)
            if not data:
                continue
            for rtype, rseq, rpayload in reader.feed(data):
                rtt = (time.perf_counter() - t0) * 1000.0
                if rseq != self.seq:
                    return "seq_err", rtt, reader
                if ftype == T_DATA and rpayload != payload:
                    return "mismatch", rtt, reader
                if ftype == T_CMD_BAUD and rtype != T_ACK:
                    return "bad_ack", rtt, reader
                return "ok", rtt, reader
        return "timeout", None, reader

    def set_remote_baud(self, new_baud: int, retries: int = 3) -> bool:
        """Ordena al slave canviar de baud i verifica el link al nou baud."""
        payload = struct.pack("<I", new_baud)
        for _ in range(retries):
            st, _, _ = self._exchange(T_CMD_BAUD, payload, timeout=1.0)
            self.seq += 1
            if st == "ok":
                time.sleep(0.15)
                self.ser.baudrate = new_baud
                self.ser.reset_input_buffer()
                # ping de verificacio al nou baud
                st2, _, _ = self._exchange(T_DATA, b"\x55\xAA", timeout=1.0)
                self.seq += 1
                if st2 == "ok":
                    return True
        return False

    # ---- tests ----
    def run_traffic_test(self, name: str, pattern: str, size: int, gap_ms: float,
                         duration_s: float, timeout: float = 0.5,
                         collide: bool = False, warmup: int = 5) -> dict[str, Any]:
        """Test de trafic eco: envia trames i valida les respostes."""
        res: dict[str, Any] = dict(
            name=name, pattern=pattern, size=size, gap_ms=gap_ms,
            duration_s=duration_s, baud=self.ser.baudrate, collide=collide,
            tx=0, ok=0, crc_err=0, mismatch=0, seq_err=0, timeout=0,
            junk_bytes=0, latencies_ms=[])
        t_end = time.monotonic() + duration_s
        n = 0
        while time.monotonic() < t_end:
            payload = make_payload(pattern, size, self.seq, self.rng)
            if collide:
                # transmissio cega sense esperar: forca solapaments
                try:
                    self.ser.write(build_frame(T_DATA, self.seq, payload))
                except WriteTimeout:
                    res["timeout"] += 1        # buffer ple: tambe es informacio
                    self.ser.reset_output_buffer()
                self.seq += 1
                res["tx"] += 1
                self.ser.reset_input_buffer()  # descarta ecos solapats
                if gap_ms:
                    time.sleep(gap_ms / 1000.0)
                continue
            st, rtt, reader = self._exchange(T_DATA, payload, timeout)
            self.seq += 1
            n += 1
            if n <= warmup:            # descarta warmup (buffers USB, caches)
                continue
            res["tx"] += 1
            res["junk_bytes"] += reader.junk
            res["crc_err"] += reader.crc_errors
            if st == "ok":
                res["ok"] += 1
                res["latencies_ms"].append(rtt)
            elif st in ("mismatch", "seq_err", "timeout"):
                res[st] += 1
            if gap_ms:
                time.sleep(gap_ms / 1000.0)
        if collide:
            # drenar el backlog d'ecos fins que el bus calli de veritat
            drained = self._drain_quiet(quiet_s=0.5, max_s=15.0)
            res["drained_bytes"] = drained
        return res

    def _drain_quiet(self, quiet_s: float = 0.5, max_s: float = 15.0) -> int:
        """Llegeix i descarta fins a tenir quiet_s seguits de silenci."""
        total = 0
        t_max = time.monotonic() + max_s
        t_last = time.monotonic()
        while time.monotonic() < t_max:
            data = self.ser.read(self.ser.in_waiting or 1)
            if data:
                total += len(data)
                t_last = time.monotonic()
            elif time.monotonic() - t_last >= quiet_s:
                break
        self.ser.reset_input_buffer()
        return total

    def run_idle_monitor(self, name: str, duration_s: float) -> dict[str, Any]:
        """Bus en silenci total: qualsevol byte rebut es un fantasma del failsafe."""
        reader = FrameReader()
        self.ser.reset_input_buffer()
        t_end = time.monotonic() + duration_s
        raw = 0
        while time.monotonic() < t_end:
            data = self.ser.read(self.ser.in_waiting or 1)
            if data:
                raw += len(data)
                reader.feed(data)
        return dict(name=name, duration_s=duration_s, baud=self.ser.baudrate,
                    idle_test=True, raw_bytes=raw, junk_bytes=raw,
                    tx=0, ok=0, crc_err=0, mismatch=0, seq_err=0, timeout=0,
                    latencies_ms=[])

    def sanity_ping(self, tries: int = 5) -> tuple[int, int]:
        """Comprova que el link respon (usat post-colisio)."""
        ok = 0
        for _ in range(tries):
            st, _, _ = self._exchange(T_DATA, b"\xA5\x5A\xF0\x0F", timeout=0.5)
            self.seq += 1
            ok += (st == "ok")
        return ok, tries

"""Motor de tests: intercanvis master<->slave i primitives de mesura."""

from __future__ import annotations

import random
import struct
import time
from typing import Any, Callable

from .patterns import make_payload
from .protocol import HDR_LEN, T_ACK, T_CMD_BAUD, T_DATA, FrameReader, build_frame
from .transport import BaudNotSupported, Transport, WriteTimeout

ProgressCB = Callable[["dict[str, Any]"], None]


def min_exchange_timeout(baud: int, size: int, base: float) -> float:
    """Timeout minim per a un intercanvi, mai mes curt que el temps fisic.

    Una trama gran a baud baix pot trigar mes a anar i tornar que el timeout
    fix: a 9600 bps una trama de 250 B fa ~0,54 s d'anada i tornada, per sobre
    del 0,5 s per defecte, i donaria un FALS timeout. Escalem el timeout amb el
    temps de transmissio (8N1 = 10 bits/byte, anada + tornada) amb marge.
    """
    frame_bits = (HDR_LEN + size + 2) * 10        # 8N1
    rtt_s = frame_bits / baud * 2.0               # master TX + eco del slave
    return max(base, rtt_s * 1.5 + 0.05)


class TestEngine:
    """Executa tests contra el slave i acumula resultats.

    ``on_progress`` es un callback opcional per a feedback en directe: rep el
    dict de resultats parcial mentre el test corre, escanyat a ``progress_dt``
    segons. S'invoca sempre *despres* de mesurar cada RTT, mai durant, aixi la
    latencia reportada no queda contaminada pel temps de pintar la UI.
    """

    def __init__(self, ser: Transport, seed: int, quiet: bool = False,
                 on_progress: ProgressCB | None = None,
                 progress_dt: float = 0.2) -> None:
        self.ser = ser
        self.rng = random.Random(seed)
        self.seq = 0
        self.quiet = quiet
        self._on_progress = on_progress
        self._progress_dt = progress_dt
        self._last_progress = 0.0

    def _emit(self, res: dict[str, Any]) -> None:
        """Notifica progres al callback, escanyat en el temps (barat si es None)."""
        if self._on_progress is None:
            return
        now = time.monotonic()
        if now - self._last_progress >= self._progress_dt:
            self._last_progress = now
            self._on_progress(res)

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
                try:
                    self.ser.baudrate = new_baud
                except BaudNotSupported:
                    # el nostre extrem no pot amb aquest baud: aquell baud
                    # queda marcat com a fallit, pero la bateria continua
                    return False
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
        # el timeout no pot ser mes curt que el temps fisic de la trama
        timeout = min_exchange_timeout(self.ser.baudrate, size, timeout)
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
                self._emit(res)
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
            self._emit(res)
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
        res: dict[str, Any] = dict(
            name=name, duration_s=duration_s, baud=self.ser.baudrate,
            idle_test=True, raw_bytes=0, junk_bytes=0,
            tx=0, ok=0, crc_err=0, mismatch=0, seq_err=0, timeout=0,
            latencies_ms=[])
        t_end = time.monotonic() + duration_s
        while time.monotonic() < t_end:
            data = self.ser.read(self.ser.in_waiting or 1)
            if data:
                res["raw_bytes"] += len(data)
                res["junk_bytes"] = res["raw_bytes"]
                reader.feed(data)
            self._emit(res)
        return res

    def run_fullduplex_test(self, name: str, pattern: str, size: int,
                            window: int, duration_s: float, timeout: float = 0.5,
                            warmup: int = 5) -> dict[str, Any]:
        """Trafic simultani en les dues direccions (nomes cablejat de 4 fils).

        Envia fins a ``window`` trames sense esperar l'eco de cadascuna: mentre
        el master transmet la trama N+k, el slave ja li esta retornant la N.
        Aixo deixa **els dos parells actius alhora**, cosa impossible en 2 fils
        (alla seria una colisio al bus compartit). Els ecos es casen per ``seq``.

        Fa servir el protocol i el slave de sempre: el que canvia es que el
        master no serialitza els intercanvis.
        """
        res: dict[str, Any] = dict(
            name=name, pattern=pattern, size=size, gap_ms=0,
            duration_s=duration_s, baud=self.ser.baudrate, collide=False,
            fullduplex=True, window=window,
            tx=0, ok=0, crc_err=0, mismatch=0, seq_err=0, timeout=0,
            junk_bytes=0, latencies_ms=[])

        # una trama pot fer cua darrere de tota la finestra abans no torna
        frame_s = (HDR_LEN + size + 2) * 10 / self.ser.baudrate
        deadline_s = min_exchange_timeout(self.ser.baudrate, size, timeout) \
            + window * frame_s

        reader = FrameReader()
        self.ser.reset_input_buffer()
        inflight: dict[int, tuple[bytes, float]] = {}   # seq -> (payload, t_sent)
        t_end = time.monotonic() + duration_s
        n = 0

        while time.monotonic() < t_end or inflight:
            # 1) omplir la finestra sense esperar respostes
            while len(inflight) < window and time.monotonic() < t_end:
                payload = make_payload(pattern, size, self.seq, self.rng)
                try:
                    self.ser.write(build_frame(T_DATA, self.seq, payload))
                except WriteTimeout:
                    res["timeout"] += 1        # buffer de sortida ple
                    self.ser.reset_output_buffer()
                    break
                inflight[self.seq] = (payload, time.perf_counter())
                self.seq += 1

            # 2) recollir el que hagi tornat mentrestant
            data = self.ser.read(self.ser.in_waiting or 1)
            if data:
                for _rtype, rseq, rpayload in reader.feed(data):
                    sent = inflight.pop(rseq, None)
                    if sent is None:
                        res["seq_err"] += 1    # eco no demanat o duplicat
                        continue
                    payload, t0 = sent
                    rtt = (time.perf_counter() - t0) * 1000.0
                    n += 1
                    if n <= warmup:
                        continue
                    res["tx"] += 1
                    if rpayload != payload:
                        res["mismatch"] += 1
                    else:
                        res["ok"] += 1
                        res["latencies_ms"].append(rtt)

            # 3) caducar les que ja no tornaran
            now_p = time.perf_counter()
            for s in [s for s, (_p, t0) in inflight.items()
                      if now_p - t0 > deadline_s]:
                inflight.pop(s)
                n += 1
                if n > warmup:
                    res["tx"] += 1
                    res["timeout"] += 1

            res["junk_bytes"] = reader.junk
            res["crc_err"] = reader.crc_errors
            self._emit(res)

        return res

    def run_baud_offset_test(self, name: str, offset_pct: float,
                             pattern: str = "random", size: int = 32,
                             gap_ms: float = 0, duration_s: float = 5,
                             timeout: float = 0.3, warmup: int = 2) -> dict[str, Any]:
        """Mesura el marge de tolerancia de baud del link.

        Desplaça el baud del *master* un ``offset_pct`` % respecte del nominal
        (el slave es queda al nominal) i corre trafic d'eco. Un link UART
        tolera ~2% de desajust acumulat entre extrems; cada re-clock pel cami
        (p.ex. conversio a fibra) en consumeix una part. El FER en funcio del
        desajust diu quant marge queda.
        """
        nominal = self.ser.baudrate
        skewed = int(round(nominal * (1.0 + offset_pct / 100.0)))
        try:
            self.ser.baudrate = skewed
        except BaudNotSupported as exc:
            return dict(name=name, pattern=pattern, size=size, gap_ms=gap_ms,
                        duration_s=duration_s, baud=nominal, collide=False,
                        tx=0, ok=0, crc_err=0, mismatch=0, seq_err=0, timeout=0,
                        junk_bytes=0, latencies_ms=[],
                        baud_offset_pct=offset_pct, baud_skewed=skewed,
                        baud_set_failed=str(exc))
        try:
            res = self.run_traffic_test(name, pattern, size, gap_ms, duration_s,
                                        timeout=timeout, warmup=warmup)
        finally:
            self.ser.baudrate = nominal
            time.sleep(0.05)                  # deixar drenar el que quedi al vol
            self.ser.reset_input_buffer()
        res["baud"] = nominal                 # el nominal es la referencia del test
        res["baud_offset_pct"] = offset_pct
        res["baud_skewed"] = skewed
        return res

    def sanity_ping(self, tries: int = 5) -> tuple[int, int]:
        """Comprova que el link respon (usat post-colisio)."""
        ok = 0
        for _ in range(tries):
            st, _, _ = self._exchange(T_DATA, b"\xA5\x5A\xF0\x0F", timeout=0.5)
            self.seq += 1
            ok += (st == "ok")
        return ok, tries

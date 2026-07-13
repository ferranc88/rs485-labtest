#!/usr/bin/env python3
"""
rs485_labtest.py  v2.0 - Bateria d'estres laboratory-grade per links RS-485
============================================================================
Valida links RS-485 half-duplex (p.ex. convertidors RS-485 <-> fibra optica)
amb una bateria automatitzada de proves, criteris PASS/FAIL explicits i
informes reproduibles (JSON + Markdown + CSV de latencies).

Requisits:  pip install pyserial

US BASIC
--------
Extrem B (respon, deixar corrent):
    python3 rs485_labtest.py slave --port /dev/ttyUSB1 --baud 115200

Extrem A (orquestra la bateria):
    python3 rs485_labtest.py battery --port /dev/ttyUSB0 --baud 115200 \
        --profile standard --label "NDR6_protoB_Vcm+7V" --outdir results/

Perfils: smoke (~2 min) | standard (~15 min) | soak (~2 h)

El master controla el baud del slave remotament (protocol CMD/ACK), aixi el
barrido de bauds es fa sense tocar l'extrem B.

Tests individuals tambe disponibles:
    python3 rs485_labtest.py master --port /dev/ttyUSB0 --pattern 0x55 ...

CRITERIS PASS/FAIL (per defecte, ajustables)
--------------------------------------------
  - Frame Error Rate  == 0        (--max-fer per relaxar)
  - Bytes de brossa   == 0        (soroll fora de trama: failsafe/bias)
  - Idle monitor      == 0 bytes  (bus en repos ha de callar)
  - Recuperacio post-colisio      (el bus no es queda encallat)
"""

import argparse
import csv
import json
import os
import platform
import random
import statistics
import struct
import sys
import time
from datetime import datetime, timezone

try:
    import serial
except ImportError:
    sys.exit("Falta pyserial:  pip install pyserial")

VERSION = "2.0"

# ------------------------------------------------------------------ protocol
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
    body = HDR.pack(SOF, ftype, seq & 0xFFFFFFFF, len(payload)) + payload
    return body + struct.pack("<H", crc16(body))


class FrameReader:
    """Parser resincronitzable. Compta cada byte fora de trama valida (junk)."""

    def __init__(self):
        self.buf = bytearray()
        self.junk = 0
        self.crc_errors = 0

    def feed(self, data: bytes):
        frames = []
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


# ------------------------------------------------------------------ patterns
def make_payload(pattern: str, size: int, seq: int, rng: random.Random) -> bytes:
    if pattern == "random":
        return bytes(rng.getrandbits(8) for _ in range(size))
    if pattern == "counter":
        return bytes((seq + i) & 0xFF for i in range(size))
    if pattern == "walking":
        return bytes((1 << ((seq + i) % 8)) & 0xFF for i in range(size))
    val = int(pattern, 0) & 0xFF
    return bytes([val] * size)


# --------------------------------------------------------------------- port
def open_port(port: str, baud: int, parity: str = "N", stopbits: float = 1) -> serial.Serial:
    p = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}[parity]
    s = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE,
         2: serial.STOPBITS_TWO}[stopbits]
    ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity=p,
                        stopbits=s, timeout=0.01, write_timeout=2)
    time.sleep(0.15)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


# --------------------------------------------------------------------- slave
def run_slave(args):
    ser = open_port(args.port, args.baud, args.parity, args.stopbits)
    reader = FrameReader()
    rx_ok = 0
    print(f"[slave] {args.port} @ {args.baud} bps - escoltant (Ctrl-C surt)")
    try:
        while True:
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            for ftype, seq, payload in reader.feed(data):
                if ftype == T_DATA:
                    rx_ok += 1
                    if args.turnaround_us:
                        time.sleep(args.turnaround_us / 1e6)
                    ser.write(build_frame(T_DATA, seq, payload))
                    ser.flush()
                elif ftype == T_CMD_BAUD:
                    new_baud = struct.unpack("<I", payload)[0]
                    ser.write(build_frame(T_ACK, seq, payload))
                    ser.flush()
                    time.sleep(0.10)          # deixar sortir l'ACK del cable
                    ser.baudrate = new_baud
                    ser.reset_input_buffer()
                    print(f"[slave] baud -> {new_baud}")
                if rx_ok and rx_ok % 2000 == 0:
                    print(f"[slave] eco={rx_ok} crc_err={reader.crc_errors} junk={reader.junk}B")
    except KeyboardInterrupt:
        print(f"\n[slave] fi. eco={rx_ok} crc_err={reader.crc_errors} junk={reader.junk}B")
    finally:
        ser.close()


# ------------------------------------------------------------------- engine
class TestEngine:
    """Executa tests contra el slave i acumula resultats."""

    def __init__(self, ser: serial.Serial, seed: int, quiet: bool = False):
        self.ser = ser
        self.rng = random.Random(seed)
        self.seq = 0
        self.quiet = quiet

    # ---- primitives ----
    def _exchange(self, ftype, payload, timeout):
        """Envia una trama i espera la resposta. Retorna (status, rtt_ms, reader_stats)."""
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
    def run_traffic_test(self, name, pattern, size, gap_ms, duration_s,
                         timeout=0.5, collide=False, warmup=5):
        res = dict(name=name, pattern=pattern, size=size, gap_ms=gap_ms,
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
                except serial.SerialTimeoutException:
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

    def _drain_quiet(self, quiet_s=0.5, max_s=15.0):
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

    def run_idle_monitor(self, name, duration_s):
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

    def sanity_ping(self, tries=5):
        """Comprova que el link respon (usat post-colisio)."""
        ok = 0
        for _ in range(tries):
            st, _, _ = self._exchange(T_DATA, b"\xA5\x5A\xF0\x0F", timeout=0.5)
            self.seq += 1
            ok += (st == "ok")
        return ok, tries


# ------------------------------------------------------------------ battery
def battery_plan(profile, bauds, base_baud):
    """Retorna llista de (descripcio, tipus, kwargs)."""
    d = dict(smoke=dict(short=5, med=8, long=10, idle=5),
             standard=dict(short=20, med=45, long=60, idle=30),
             soak=dict(short=60, med=300, long=1800, idle=120))[profile]

    core = [
        ("sanity",            "traffic", dict(pattern="counter", size=8,   gap_ms=20,  duration_s=d["short"])),
        ("turnaround_gap0",   "traffic", dict(pattern="random",  size=8,   gap_ms=0,   duration_s=d["med"])),
        ("min_frames",        "traffic", dict(pattern="random",  size=1,   gap_ms=0,   duration_s=d["short"])),
        ("pattern_0x55",      "traffic", dict(pattern="0x55",    size=64,  gap_ms=0,   duration_s=d["med"])),
        ("pattern_0x00_DC",   "traffic", dict(pattern="0x00",    size=64,  gap_ms=0,   duration_s=d["med"])),
        ("pattern_0xFF_DC",   "traffic", dict(pattern="0xFF",    size=64,  gap_ms=0,   duration_s=d["med"])),
        ("saturation_250B",   "traffic", dict(pattern="random",  size=250, gap_ms=0,   duration_s=d["med"])),
        ("failsafe_paused",   "traffic", dict(pattern="0x00",    size=250, gap_ms=500, duration_s=d["long"])),
        ("idle_monitor",      "idle",    dict(duration_s=d["idle"])),
        ("collision_blind",   "traffic", dict(pattern="random",  size=32,  gap_ms=0,   duration_s=d["short"], collide=True)),
        ("post_collision",    "ping",    dict()),
        ("ber_random_long",   "traffic", dict(pattern="random",  size=128, gap_ms=0,   duration_s=d["long"])),
    ]

    plan = [(f"{name}@{base_baud}", kind, kw) for name, kind, kw in core]
    # barrido de bauds: subset representatiu a cada baud extra
    subset = ["turnaround_gap0", "pattern_0x00_DC", "failsafe_paused", "idle_monitor"]
    for b in bauds:
        if b == base_baud:
            continue
        plan.append((f"__setbaud__{b}", "baud", dict(baud=b)))
        for name, kind, kw in core:
            if name in subset:
                plan.append((f"{name}@{b}", kind, dict(kw)))
    if len(bauds) > 1:
        plan.append((f"__setbaud__{base_baud}", "baud", dict(baud=base_baud)))
    return plan


def verdict(res, max_fer, max_p99_ms):
    """Aplica criteris. Retorna (PASS/FAIL/INFO, [motius])."""
    reasons = []
    if res.get("idle_test"):
        if res["raw_bytes"] > 0:
            reasons.append(f"{res['raw_bytes']}B rebuts amb bus en repos (failsafe sospitos)")
        return ("FAIL" if reasons else "PASS"), reasons
    if res.get("collide"):
        return "INFO", ["test de colisio: vegeu post_collision"]
    errs = res["crc_err"] + res["mismatch"] + res["seq_err"] + res["timeout"]
    fer = errs / res["tx"] if res["tx"] else 0.0
    if fer > max_fer:
        reasons.append(f"FER {100*fer:.4f}% > llindar {100*max_fer:.4f}%")
    if res["junk_bytes"] > 0:
        reasons.append(f"{res['junk_bytes']}B de brossa fora de trama")
    if res["mismatch"] > 0:
        reasons.append(f"{res['mismatch']} trames amb payload corrupte (CRC passat!)")
    lat = res["latencies_ms"]
    if lat and max_p99_ms:
        lat_s = sorted(lat)
        p99 = lat_s[min(int(len(lat_s) * 0.99), len(lat_s) - 1)]
        if p99 > max_p99_ms:
            reasons.append(f"p99 latencia {p99:.1f}ms > {max_p99_ms}ms")
    return ("FAIL" if reasons else "PASS"), reasons


def lat_stats(lat):
    if not lat:
        return {}
    s = sorted(lat)
    q = lambda p: s[min(int(len(s) * p), len(s) - 1)]
    return dict(n=len(s), min=round(s[0], 3), p50=round(q(.5), 3),
                p95=round(q(.95), 3), p99=round(q(.99), 3),
                max=round(s[-1], 3), stdev=round(statistics.pstdev(s), 3))


def ber_bound(res, size):
    """Cota superior de BER al 95%% CL (regla de 3) si 0 errors; estimacio si n'hi ha."""
    bits = res["tx"] * (HDR_LEN + size + 2) * 10  # 8N1 = 10 bits/byte
    if bits == 0:
        return None, None
    errs = res["crc_err"] + res["mismatch"] + res["timeout"]
    if errs == 0:
        return 3.0 / bits, True     # upper bound, rule of three
    return errs / bits, False       # cota inferior (>=1 bit dolent per trama)


def run_battery(args):
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = args.label or "unlabeled"
    base = os.path.join(outdir, f"rs485_{label}_{stamp}")

    seed = args.seed if args.seed is not None else random.randrange(2**31)
    ser = open_port(args.port, args.baud, args.parity, args.stopbits)
    eng = TestEngine(ser, seed)

    meta = dict(script_version=VERSION, timestamp_utc=stamp, label=label,
                port=args.port, base_baud=args.baud, parity=args.parity,
                stopbits=args.stopbits, profile=args.profile, seed=seed,
                bauds=args.bauds, max_fer=args.max_fer, max_p99_ms=args.max_p99,
                platform=platform.platform(), python=sys.version.split()[0],
                pyserial=serial.VERSION, operator_notes=args.notes or "")

    plan = battery_plan(args.profile, args.bauds, args.baud)
    n_tests = sum(1 for _, k, _ in plan if k in ("traffic", "idle", "ping"))
    print(f"\n=== BATERIA RS-485 v{VERSION} === label={label} profile={args.profile} "
          f"seed={seed}\n    {n_tests} tests | resultats a {base}.* \n")

    results = []
    all_lat_rows = []
    idx = 0
    t_start = time.monotonic()
    aborted = False
    skipping = False
    try:
        for name, kind, kw in plan:
            if kind == "baud":
                b = kw["baud"]
                print(f"--- canvi de baud remot -> {b} ...", end=" ", flush=True)
                if eng.set_remote_baud(b):
                    print("OK")
                    skipping = False
                else:
                    print("FALLIT (el slave no respon al nou baud); s'ometen els seus tests")
                    skipping = True
                    results.append(dict(name=f"setbaud_{b}", baud=b, tx=0, ok=0,
                                        crc_err=0, mismatch=0, seq_err=0, timeout=0,
                                        junk_bytes=0, verdict="FAIL",
                                        reasons=["canvi de baud remot fallit"], lat={}))
                continue
            if skipping:
                continue
            idx += 1
            print(f"[{idx:>2}/{n_tests}] {name:<28}", end=" ", flush=True)
            if kind == "traffic":
                res = eng.run_traffic_test(name, **kw)
            elif kind == "idle":
                res = eng.run_idle_monitor(name, **kw)
            elif kind == "ping":
                ok, tries = eng.sanity_ping()
                res = dict(name=name, baud=ser.baudrate, tx=tries, ok=ok,
                           crc_err=0, mismatch=0, seq_err=0, timeout=tries - ok,
                           junk_bytes=0, latencies_ms=[], post_collision=True)
            v, reasons = verdict(res, args.max_fer, args.max_p99)
            res["verdict"], res["reasons"] = v, reasons
            res["lat"] = lat_stats(res["latencies_ms"])
            if kind == "traffic" and not res.get("collide"):
                ub, is_bound = ber_bound(res, kw.get("size", 0))
                if ub:
                    res["ber"] = f"{'<' if is_bound else '>='}{ub:.2e}" + \
                                 (" @95%CL" if is_bound else "")
            for ms in res["latencies_ms"]:
                all_lat_rows.append((name, res["baud"], ms))
            res.pop("latencies_ms")
            results.append(res)
            extra = f" | {', '.join(reasons)}" if reasons else ""
            lat = res.get("lat") or {}
            lati = f" p50={lat.get('p50')}ms p99={lat.get('p99')}ms" if lat else ""
            print(f"{v:<4} tx={res.get('tx',0)} ok={res.get('ok',0)}{lati}{extra}")
    except KeyboardInterrupt:
        aborted = True
        print("\n!! Bateria interrompuda per l'usuari - es genera informe parcial")
    finally:
        ser.close()

    meta["elapsed_s"] = round(time.monotonic() - t_start, 1)
    meta["aborted"] = aborted
    write_reports(base, meta, results, all_lat_rows)
    n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
    print(f"\n=== RESULTAT GLOBAL: {'FAIL' if n_fail else 'PASS'} "
          f"({n_fail} FAIL / {len(results)} tests, {meta['elapsed_s']}s) ===")
    print(f"Informes: {base}.json  {base}.md  {base}_latencies.csv")
    sys.exit(1 if n_fail or aborted else 0)


# ------------------------------------------------------------------ reports
def write_reports(base, meta, results, lat_rows):
    with open(base + ".json", "w") as f:
        json.dump(dict(meta=meta, results=results), f, indent=2)

    with open(base + "_latencies.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["test", "baud", "rtt_ms"])
        w.writerows(lat_rows)

    lines = [f"# Informe estres RS-485 - {meta['label']}", ""]
    lines += [f"- **Data (UTC):** {meta['timestamp_utc']}",
              f"- **Port / baud base:** {meta['port']} @ {meta['base_baud']} "
              f"({meta['parity']},{meta['stopbits']})",
              f"- **Perfil:** {meta['profile']} | **Seed:** {meta['seed']} "
              f"| **Durada:** {meta['elapsed_s']} s"
              + (" | **INTERROMPUT**" if meta.get("aborted") else ""),
              f"- **Entorn:** {meta['platform']}, Python {meta['python']}, "
              f"pyserial {meta['pyserial']}",
              f"- **Criteris:** FER <= {meta['max_fer']}, junk == 0"
              + (f", p99 <= {meta['max_p99_ms']} ms" if meta['max_p99_ms'] else ""), ""]
    if meta.get("operator_notes"):
        lines += [f"- **Notes operador:** {meta['operator_notes']}", ""]

    lines += ["| # | Test | Baud | TX | OK | CRC | Mism | Seq | TO | Junk(B) | p50/p99 (ms) | BER | Veredicte |",
              "|---|------|------|----|----|-----|------|-----|----|---------|--------------|-----|-----------|"]
    for i, r in enumerate(results, 1):
        lat = r.get("lat") or {}
        latstr = f"{lat.get('p50','-')}/{lat.get('p99','-')}" if lat else "-"
        lines.append(f"| {i} | {r['name']} | {r.get('baud','-')} | {r.get('tx',0)} "
                     f"| {r.get('ok',0)} | {r.get('crc_err',0)} | {r.get('mismatch',0)} "
                     f"| {r.get('seq_err',0)} | {r.get('timeout',0)} "
                     f"| {r.get('junk_bytes', r.get('raw_bytes',0))} | {latstr} "
                     f"| {r.get('ber','-')} | **{r['verdict']}** |")
    fails = [r for r in results if r["verdict"] == "FAIL"]
    lines += ["", "## Motius de FAIL" if fails else "## Sense fallades", ""]
    for r in fails:
        for reason in r["reasons"]:
            lines.append(f"- **{r['name']}**: {reason}")
    lines += ["", "## Guia d'interpretacio", "",
              "- **Junk amb bus en repos / idle_monitor FAIL** -> bias de failsafe insuficient; "
              "mirar diferencial A-B en idle amb sonda (ha de ser > +200 mV).",
              "- **Timeouts amb gap=0** -> el driver enable (auto-direccio) es queda actiu "
              "massa temps i trepitja la resposta.",
              "- **Mismatch (payload corrupte amb framing valid)** -> marge de bit degradat: "
              "jitter, slew-rate o reflexions.",
              "- **p99 >> p50** -> turnaround no determinista (auto-baud o buffers).",
              "- **post_collision FAIL** -> latch-up: un transceptor es queda en TX.", ""]
    with open(base + ".md", "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    def common(p):
        p.add_argument("--port", required=True)
        p.add_argument("--baud", type=int, default=115200)
        p.add_argument("--parity", choices=["N", "E", "O"], default="N")
        p.add_argument("--stopbits", type=float, choices=[1, 1.5, 2], default=1)

    ps = sub.add_parser("slave", help="extrem que fa eco")
    common(ps)
    ps.add_argument("--turnaround-us", type=int, default=0,
                    help="retard artificial abans de l'eco")

    pb = sub.add_parser("battery", help="bateria automatitzada (master)")
    common(pb)
    pb.add_argument("--profile", choices=["smoke", "standard", "soak"], default="standard")
    pb.add_argument("--bauds", type=int, nargs="*", default=[],
                    help="bauds addicionals per al barrido, p.ex. --bauds 9600 921600")
    pb.add_argument("--label", default="", help="identificador del DUT/condicio (Vcm, temp...)")
    pb.add_argument("--notes", default="", help="notes de l'operador per a l'informe")
    pb.add_argument("--outdir", default="results")
    pb.add_argument("--seed", type=int, default=None, help="llavor RNG (reproduibilitat)")
    pb.add_argument("--max-fer", type=float, default=0.0, help="llindar FER (0 = cap error)")
    pb.add_argument("--max-p99", type=float, default=0.0,
                    help="llindar p99 latencia en ms (0 = sense llindar)")

    pm = sub.add_parser("master", help="test individual manual")
    common(pm)
    pm.add_argument("--pattern", default="random")
    pm.add_argument("--size", type=int, default=64)
    pm.add_argument("--gap", type=float, default=0.0)
    pm.add_argument("--duration", type=float, default=60.0)
    pm.add_argument("--timeout", type=float, default=0.5)
    pm.add_argument("--collide", action="store_true")

    pd = sub.add_parser("duo", help="bateria completa amb els 2 extrems al mateix PC")
    common(pd)                       # --port = extrem master (A)
    pd.add_argument("--slave-port", required=True,
                    help="port de l'extrem que fa eco (B), p.ex. /dev/ttyUSB1")
    pd.add_argument("--profile", choices=["smoke", "standard", "soak"], default="standard")
    pd.add_argument("--bauds", type=int, nargs="*", default=[])
    pd.add_argument("--label", default="")
    pd.add_argument("--notes", default="")
    pd.add_argument("--outdir", default="results")
    pd.add_argument("--seed", type=int, default=None)
    pd.add_argument("--max-fer", type=float, default=0.0)
    pd.add_argument("--max-p99", type=float, default=0.0)

    args = ap.parse_args()

    if args.mode == "slave":
        run_slave(args)
    elif args.mode == "battery":
        args.bauds = list(dict.fromkeys(args.bauds))   # dedupe, conserva ordre
        run_battery(args)
    elif args.mode == "duo":
        import subprocess
        args.bauds = list(dict.fromkeys(args.bauds))
        cmd = [sys.executable, os.path.abspath(__file__), "slave",
               "--port", args.slave_port, "--baud", str(args.baud),
               "--parity", args.parity, "--stopbits", str(args.stopbits)]
        print(f"[duo] arrencant slave a {args.slave_port} ...")
        slave = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE)
        time.sleep(1.0)
        if slave.poll() is not None:
            err = slave.stderr.read().decode(errors="replace").strip()
            sys.exit(f"[duo] el slave ha mort en arrencar:\n{err}")
        try:
            run_battery(args)          # fa sys.exit amb 0/1
        finally:
            slave.terminate()
            try:
                slave.wait(timeout=3)
            except subprocess.TimeoutExpired:
                slave.kill()
            print("[duo] slave aturat")
    else:
        ser = open_port(args.port, args.baud, args.parity, args.stopbits)
        eng = TestEngine(ser, seed=0)
        res = eng.run_traffic_test("manual", args.pattern, args.size,
                                   args.gap, args.duration,
                                   timeout=args.timeout, collide=args.collide)
        v, reasons = verdict(res, 0.0, 0.0)
        res["lat"] = lat_stats(res.pop("latencies_ms"))
        print(json.dumps(dict(res, verdict=v, reasons=reasons), indent=2))
        ser.close()


if __name__ == "__main__":
    main()

"""Bateria automatitzada: pla de tests, criteris PASS/FAIL i orquestracio."""

from __future__ import annotations

import argparse
import os
import platform
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .catalog import HALF_DUPLEX_ONLY
from .engine import TestEngine
from .interfaces import DEFAULT_INTERFACE, interface_duplex
from .monitor import Monitor, MultiMonitor, TelegramMonitor, make_monitor
from .notify import build_notifier
from .protocol import HDR_LEN
from .report import write_reports
from .transport import Transport, open_port

# desajustos de baud provats (en %); ±1% ha de passar (llindar --baud-margin),
# la resta caracteritza on es trenca el link (INFO)
BAUD_OFFSETS_PCT = (1.0, -1.0, 2.0, -2.0, 3.0, -3.0)


def battery_plan(profile: str, bauds: list[int], base_baud: int,
                 tests: list[str] | None = None, duplex: str = "half"
                 ) -> list[tuple[str, str, dict[str, Any]]]:
    """Retorna llista de (descripcio, tipus, kwargs).

    ``tests`` limita el pla a un subconjunt dels tests del nucli (en l'ordre
    canonic); si es None, es corren tots.

    ``duplex`` es l'unic que fa variar el pla:

    - ``half`` (RS-485 2 fils): bus compartit -> tests de colisio i turnaround.
    - ``full`` (RS-485 4 fils, RS-422, RS-232): un cami per sentit -> no hi ha
      contesa, i s'hi poden fer els tests de carrega simultania.
    """
    d = dict(smoke=dict(short=5, med=8, long=10, idle=5),
             standard=dict(short=20, med=45, long=60, idle=30),
             soak=dict(short=60, med=300, long=1800, idle=120))[profile]

    core: list[tuple[str, str, dict[str, Any]]] = [
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
    if duplex == "full":
        # cada sentit te el seu cami: no hi ha bus compartit, aixi que en punt
        # a punt les colisions no existeixen i els seus tests no apliquen
        core = [t for t in core if t[0] not in HALF_DUPLEX_ONLY]
        # ...pero s'hi poden fer proves que en half serien una colisio:
        # les dues direccions carregades alhora
        core += [
            ("fullduplex_load",   "fullduplex", dict(pattern="random", size=64,  window=8, duration_s=d["med"])),
            ("fullduplex_sat250", "fullduplex", dict(pattern="random", size=250, window=8, duration_s=d["med"])),
        ]

    if tests is not None:
        want = set(tests)
        core = [t for t in core if t[0] in want]

    plan = [(f"{name}@{base_baud}", kind, kw) for name, kind, kw in core]

    # marge de tolerancia de baud: el master es desplaça, el slave queda al nominal
    if tests is None or "baud_offset" in tests:
        for off in BAUD_OFFSETS_PCT:
            plan.append((f"baud_offset{off:+g}%@{base_baud}", "offset",
                         dict(offset_pct=off, pattern="random", size=32,
                              gap_ms=0, duration_s=d["short"], timeout=0.3)))
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


def verdict(res: dict[str, Any], max_fer: float,
            max_p99_ms: float) -> tuple[str, list[str]]:
    """Aplica criteris. Retorna (PASS/FAIL/INFO, [motius])."""
    reasons = []
    if res.get("idle_test"):
        if res["raw_bytes"] > 0:
            reasons.append(f"{res['raw_bytes']}B rebuts amb bus en repos (failsafe sospitos)")
        return ("FAIL" if reasons else "PASS"), reasons
    if res.get("collide"):
        return "INFO", ["test de colisio: vegeu post_collision"]
    off = res.get("baud_offset_pct")
    if off is not None:
        if res.get("baud_set_failed"):
            msg = f"no s'ha pogut fixar el baud desplaçat: {res['baud_set_failed']}"
            return ("FAIL" if res.get("offset_required") else "INFO"), [msg]
        if not res.get("offset_required"):
            errs = res["crc_err"] + res["mismatch"] + res["seq_err"] + res["timeout"]
            fer = errs / res["tx"] if res["tx"] else 0.0
            return "INFO", [f"desajust {off:+.1f}%: FER {100 * fer:.2f}% "
                            f"(caracteritzacio del marge)"]
        # dins del marge exigit: cauen els criteris normals de mes avall
    errs = res["crc_err"] + res["mismatch"] + res["seq_err"] + res["timeout"]
    fer = errs / res["tx"] if res["tx"] else 0.0
    if fer > max_fer:
        reasons.append(f"FER {100 * fer:.4f}% > llindar {100 * max_fer:.4f}%")
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


def lat_stats(lat: list[float]) -> dict[str, Any]:
    """Estadistics de latencia (percentils sobre la llista ordenada)."""
    if not lat:
        return {}
    s = sorted(lat)

    def q(p: float) -> float:
        return s[min(int(len(s) * p), len(s) - 1)]

    return dict(n=len(s), min=round(s[0], 3), p50=round(q(.5), 3),
                p95=round(q(.95), 3), p99=round(q(.99), 3),
                max=round(s[-1], 3), stdev=round(statistics.pstdev(s), 3))


def ber_bound(res: dict[str, Any], size: int) -> tuple[float | None, bool | None]:
    """Cota superior de BER al 95% CL (regla de 3) si 0 errors; estimacio si n'hi ha.

    Intencionat i important: amb 0 errors mai es reporta "BER = 0", sino la
    cota superior estadistica ``< 3/n_bits`` al 95% de confianca.
    """
    bits = res["tx"] * (HDR_LEN + size + 2) * 10  # 8N1 = 10 bits/byte
    if bits == 0:
        return None, None
    errs = res["crc_err"] + res["mismatch"] + res["timeout"]
    if errs == 0:
        return 3.0 / bits, True     # upper bound, rule of three
    return errs / bits, False       # cota inferior (>=1 bit dolent per trama)


def run_battery(args: argparse.Namespace, transport: Transport | None = None,
                monitor: Monitor | None = None) -> None:
    """Orquestra la bateria completa i escriu els informes.

    Surt del proces amb codi 1 si hi ha cap FAIL o la corrida s'interromp.
    Un Ctrl-C genera igualment l'informe parcial marcat com a interromput.

    El feedback (linia a linia o TUI en directe) el gestiona un ``Monitor``;
    si no se'n passa cap, es tria segons ``--live``, el TTY i si hi ha ``rich``.
    """
    if monitor is None:
        monitor = make_monitor(getattr(args, "live", "auto"),
                               bool(getattr(args, "quiet", False)), __version__)
        notifier = build_notifier(args)
        if notifier is not None:
            monitor = MultiMonitor([monitor, TelegramMonitor(notifier)])

    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = args.label or "unlabeled"
    base = os.path.join(outdir, f"rs485_{label}_{stamp}")

    iface = getattr(args, "interface", DEFAULT_INTERFACE)
    duplex = interface_duplex(iface)

    seed = args.seed if args.seed is not None else random.randrange(2**31)
    ser = transport if transport is not None else open_port(
        args.port, args.baud, args.parity, args.stopbits)
    on_progress = monitor.test_progress if monitor.wants_progress else None
    eng = TestEngine(ser, seed, on_progress=on_progress)

    try:
        import serial
        pyserial_version = serial.VERSION
    except ImportError:  # pragma: no cover - nomes amb transport injectat
        pyserial_version = "absent"

    meta = dict(script_version=__version__, timestamp_utc=stamp, label=label,
                port=args.port, base_baud=args.baud, parity=args.parity,
                stopbits=args.stopbits, profile=args.profile, seed=seed,
                bauds=args.bauds, max_fer=args.max_fer, max_p99_ms=args.max_p99,
                tests=getattr(args, "tests", None),
                baud_margin=getattr(args, "baud_margin", 1.0),
                interface=iface, duplex=duplex,
                platform=platform.platform(), python=sys.version.split()[0],
                pyserial=pyserial_version, operator_notes=args.notes or "")

    plan = battery_plan(args.profile, args.bauds, args.baud,
                        tests=getattr(args, "tests", None), duplex=duplex)
    n_tests = sum(1 for _, k, _ in plan
                  if k in ("traffic", "idle", "ping", "offset", "fullduplex"))

    results = []
    all_lat_rows = []
    idx = 0
    t_start = time.monotonic()
    aborted = False
    skipping = False
    monitor.battery_start(meta, n_tests, base)
    try:
        for name, kind, kw in plan:
            if kind == "baud":
                b = kw["baud"]
                baud_ok = eng.set_remote_baud(b)
                monitor.baud_change(b, baud_ok)
                skipping = not baud_ok
                if not baud_ok:
                    results.append(dict(name=f"setbaud_{b}", baud=b, tx=0, ok=0,
                                        crc_err=0, mismatch=0, seq_err=0, timeout=0,
                                        junk_bytes=0, verdict="FAIL",
                                        reasons=["canvi de baud remot fallit"], lat={}))
                continue
            if skipping:
                continue
            idx += 1
            monitor.test_start(idx, n_tests, name, kind)
            if kind == "traffic":
                res = eng.run_traffic_test(name, **kw)
            elif kind == "fullduplex":
                res = eng.run_fullduplex_test(name, **kw)
            elif kind == "offset":
                res = eng.run_baud_offset_test(name, **kw)
                res["offset_required"] = (
                    abs(res["baud_offset_pct"]) <= getattr(args, "baud_margin", 1.0))
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
            if kind in ("traffic", "fullduplex") and not res.get("collide"):
                ub, is_bound = ber_bound(res, kw.get("size", 0))
                if ub:
                    res["ber"] = f"{'<' if is_bound else '>='}{ub:.2e}" + \
                                 (" @95%CL" if is_bound else "")
            for ms in res["latencies_ms"]:
                all_lat_rows.append((name, res["baud"], ms))
            res.pop("latencies_ms")
            results.append(res)
            monitor.test_end(res)
    except KeyboardInterrupt:
        aborted = True
        monitor.note("\n!! Bateria interrompuda per l'usuari - es genera informe parcial")
    finally:
        ser.close()

    meta["elapsed_s"] = round(time.monotonic() - t_start, 1)
    meta["aborted"] = aborted
    write_reports(base, meta, results, all_lat_rows)
    n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
    monitor.battery_end(results, n_fail, meta["elapsed_s"], base)
    sys.exit(1 if n_fail or aborted else 0)

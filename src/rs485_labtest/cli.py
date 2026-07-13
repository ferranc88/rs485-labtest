"""CLI del banc de proves: modes slave | master | battery | duo."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time

from . import __version__
from .battery import lat_stats, run_battery, verdict
from .engine import TestEngine
from .slave import run_slave
from .transport import BaudNotSupported, open_port

log = logging.getLogger(__name__)

DESCRIPTION = """\
Bateria d'estres laboratory-grade per a links RS-485 half-duplex
(p.ex. convertidors RS-485 <-> fibra optica com el NDR6).

Perfils: smoke (~2 min) | standard (~15 min) | soak (~2 h)

El master controla el baud del slave remotament (protocol CMD/ACK), aixi el
barrido de bauds es fa sense tocar l'extrem B.

Criteris PASS/FAIL per defecte (ajustables):
  - Frame Error Rate  == 0        (--max-fer per relaxar)
  - Bytes de brossa   == 0        (soroll fora de trama: failsafe/bias)
  - Idle monitor      == 0 bytes  (bus en repos ha de callar)
  - Recuperacio post-colisio      (el bus no es queda encallat)
"""


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200,
                   help="baud base; s'accepta qualsevol valor, tambe alt o no "
                        "estandard (p.ex. 307200), fins on arribi l'adaptador")
    p.add_argument("--parity", choices=["N", "E", "O"], default="N")
    p.add_argument("--stopbits", type=float, choices=[1, 1.5, 2], default=1)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rs485-labtest", description=DESCRIPTION,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}")
    ap.add_argument("--verbose", action="store_true",
                    help="sortida de diagnostic (nivell DEBUG)")
    ap.add_argument("--quiet", action="store_true",
                    help="nomes avisos i errors; sense progres per consola")
    sub = ap.add_subparsers(dest="mode", required=True)

    ps = sub.add_parser("slave", help="extrem que fa eco")
    _common(ps)
    ps.add_argument("--turnaround-us", type=int, default=0,
                    help="retard artificial abans de l'eco")

    pb = sub.add_parser("battery", help="bateria automatitzada (master)")
    _common(pb)
    pb.add_argument("--profile", choices=["smoke", "standard", "soak"], default="standard")
    pb.add_argument("--bauds", type=int, nargs="*", default=[],
                    help="bauds addicionals per al barrido (canvi remot al slave); "
                         "s'accepten valors alts/no estandard, p.ex. "
                         "--bauds 9600 307200 921600 2000000")
    pb.add_argument("--label", default="", help="identificador del DUT/condicio (Vcm, temp...)")
    pb.add_argument("--notes", default="", help="notes de l'operador per a l'informe")
    pb.add_argument("--outdir", default="results")
    pb.add_argument("--seed", type=int, default=None, help="llavor RNG (reproduibilitat)")
    pb.add_argument("--max-fer", type=float, default=0.0, help="llindar FER (0 = cap error)")
    pb.add_argument("--max-p99", type=float, default=0.0,
                    help="llindar p99 latencia en ms (0 = sense llindar)")
    pb.add_argument("--live", choices=["auto", "rich", "plain"], default="auto",
                    help="feedback en directe: auto (TUI si hi ha terminal), "
                         "rich (forca la TUI), plain (linia a linia)")

    pm = sub.add_parser("master", help="test individual manual")
    _common(pm)
    pm.add_argument("--pattern", default="random")
    pm.add_argument("--size", type=int, default=64)
    pm.add_argument("--gap", type=float, default=0.0)
    pm.add_argument("--duration", type=float, default=60.0)
    pm.add_argument("--timeout", type=float, default=0.5)
    pm.add_argument("--collide", action="store_true")

    pd = sub.add_parser("duo", help="bateria completa amb els 2 extrems al mateix PC")
    _common(pd)                       # --port = extrem master (A)
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
    pd.add_argument("--live", choices=["auto", "rich", "plain"], default="auto",
                    help="feedback en directe: auto (TUI si hi ha terminal), "
                         "rich (forca la TUI), plain (linia a linia)")
    return ap


def _run_duo(args: argparse.Namespace) -> None:
    """Arrenca el slave com a subproces i corre la bateria des del mateix PC."""
    cmd = [sys.executable, "-m", "rs485_labtest", "slave",
           "--port", args.slave_port, "--baud", str(args.baud),
           "--parity", args.parity, "--stopbits", str(args.stopbits)]
    log.info("[duo] arrencant slave a %s ...", args.slave_port)
    slave = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
    time.sleep(1.0)
    if slave.poll() is not None:
        err = b""
        if slave.stderr is not None:
            err = slave.stderr.read()
        sys.exit(f"[duo] el slave ha mort en arrencar:\n{err.decode(errors='replace').strip()}")
    try:
        run_battery(args)          # fa sys.exit amb 0/1
    finally:
        slave.terminate()
        try:
            slave.wait(timeout=3)
        except subprocess.TimeoutExpired:
            slave.kill()
        log.info("[duo] slave aturat")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(message)s")

    try:
        if args.mode == "slave":
            run_slave(args.port, args.baud, args.parity, args.stopbits,
                      turnaround_us=args.turnaround_us)
        elif args.mode == "battery":
            args.bauds = list(dict.fromkeys(args.bauds))   # dedupe, conserva ordre
            run_battery(args)
        elif args.mode == "duo":
            args.bauds = list(dict.fromkeys(args.bauds))
            _run_duo(args)
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
    except BaudNotSupported as exc:
        sys.exit(f"[baud] {exc}")


if __name__ == "__main__":  # pragma: no cover
    main()

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
from .catalog import FULL_DUPLEX_ONLY, HALF_DUPLEX_ONLY, TEST_ORDER, unknown_tests
from .engine import TestEngine
from .interfaces import (
    DEFAULT_INTERFACE,
    INTERFACES,
    interface_duplex,
    interface_for_wires,
)
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


def _battery_opts(p: argparse.ArgumentParser) -> None:
    """Opcions comunes de battery i duo."""
    p.add_argument("--interface", choices=list(INTERFACES), default=DEFAULT_INTERFACE,
                   help="interficie sota prova. Determina el pla (half-duplex "
                        "-> colisions; full-duplex -> carrega simultania) i la "
                        "guia d'interpretacio de l'informe")
    p.add_argument("--wires", type=int, choices=[2, 4], default=None,
                   help="alias antic de --interface (2 = rs485-half, "
                        "4 = rs485-full)")
    p.add_argument("--profile", choices=["smoke", "standard", "soak"], default="standard")
    p.add_argument("--bauds", type=int, nargs="*", default=[],
                   help="bauds addicionals per al barrido (canvi remot al slave); "
                        "s'accepten valors alts/no estandard, p.ex. "
                        "--bauds 9600 307200 921600 2000000")
    p.add_argument("--tests", nargs="*", default=None, metavar="TEST",
                   help="corre nomes aquests tests del nucli (per defecte tots); "
                        f"noms valids: {', '.join(TEST_ORDER)}")
    p.add_argument("--label", default="", help="identificador del DUT/condicio (Vcm, temp...)")
    p.add_argument("--notes", default="", help="notes de l'operador per a l'informe")
    p.add_argument("--outdir", default="results")
    p.add_argument("--seed", type=int, default=None, help="llavor RNG (reproduibilitat)")
    p.add_argument("--max-fer", type=float, default=0.0, help="llindar FER (0 = cap error)")
    p.add_argument("--max-p99", type=float, default=0.0,
                   help="llindar p99 latencia en ms (0 = sense llindar)")
    p.add_argument("--baud-margin", type=float, default=1.0,
                   help="desajust de baud (%%) que el link HA de tolerar al test "
                        "baud_offset; els desajustos mes grans son caracteritzacio "
                        "informativa (per defecte 1.0)")
    p.add_argument("--live", choices=["auto", "rich", "plain"], default="auto",
                   help="feedback en directe: auto (TUI si hi ha terminal), "
                        "rich (forca la TUI), plain (linia a linia)")
    p.add_argument("--notify", choices=["auto", "telegram", "off"], default="auto",
                   help="notificacions Telegram (alerta a cada FAIL i resum "
                        "final): auto = actiu si hi ha RS485_TELEGRAM_TOKEN i "
                        "RS485_TELEGRAM_CHAT_ID; off = mai")


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

    sub.add_parser("wizard", help="assistent interactiu: et pregunta i llança")
    sub.add_parser("notify-test", help="prova la config de notificacions Telegram")

    pb = sub.add_parser("battery", help="bateria automatitzada (master)")
    _common(pb)
    _battery_opts(pb)

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
    _battery_opts(pd)
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


def _resolve_interface(args: argparse.Namespace) -> None:
    """``--wires`` (alias antic) mana nomes si s'ha donat explicitament."""
    if getattr(args, "wires", None) is not None:
        args.interface = interface_for_wires(args.wires)


def _validate_tests(args: argparse.Namespace) -> None:
    tests = getattr(args, "tests", None)
    if not tests:
        return
    bad = unknown_tests(tests)
    if bad:
        sys.exit(f"[tests] noms desconeguts: {', '.join(bad)}\n"
                 f"  valids: {', '.join(TEST_ORDER)}")
    iface = getattr(args, "interface", DEFAULT_INTERFACE)
    duplex = interface_duplex(iface)
    wrong = sorted(set(tests) &
                   (FULL_DUPLEX_ONLY if duplex == "half" else HALF_DUPLEX_ONLY))
    if wrong:
        need = "full-duplex" if duplex == "half" else "half-duplex"
        sys.exit(f"[tests] {', '.join(wrong)} nomes te sentit en {need}; "
                 f"has demanat --interface {iface} ({duplex}-duplex)")


def _dispatch(args: argparse.Namespace) -> None:
    if args.mode == "slave":
        run_slave(args.port, args.baud, args.parity, args.stopbits,
                  turnaround_us=args.turnaround_us)
    elif args.mode == "battery":
        args.bauds = list(dict.fromkeys(args.bauds))   # dedupe, conserva ordre
        _resolve_interface(args)
        _validate_tests(args)
        run_battery(args)
    elif args.mode == "duo":
        args.bauds = list(dict.fromkeys(args.bauds))
        _resolve_interface(args)
        _validate_tests(args)
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


def _notify_test() -> None:
    """Envia un missatge de prova; si falta el chat_id, ajuda a trobar-lo."""
    import os

    from .notify import ENV_CHAT, ENV_TOKEN, TelegramNotifier, discover_chat_ids

    token = os.environ.get(ENV_TOKEN)
    chat = os.environ.get(ENV_CHAT)
    if not token:
        sys.exit(f"falta {ENV_TOKEN} (te'l dona @BotFather a Telegram)")
    if not chat:
        print(f"falta {ENV_CHAT}. Buscant chats que hagin escrit al bot…")
        ids = discover_chat_ids(token)
        if ids:
            for cid, name in ids:
                print(f"  chat_id={cid}  ({name})")
            print(f"Exporta {ENV_CHAT} amb un d'aquests i torna a provar.")
        else:
            print("Cap. Escriu /start al bot des del teu Telegram i reintenta.")
        sys.exit(1)
    ok = TelegramNotifier(token, chat).send(
        "🔔 rs485-labtest: prova de notificació correcta.")
    if ok:
        print("Enviat ✓ (mira el teu Telegram).")
    else:
        sys.exit("No s'ha pogut enviar; revisa el token, el chat_id i la xarxa.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    level = logging.INFO
    if getattr(args, "verbose", False):
        level = logging.DEBUG
    elif getattr(args, "quiet", False):
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(message)s")

    if args.mode == "notify-test":
        _notify_test()
        return

    if args.mode == "wizard":
        from .wizard import run_wizard
        _, args = run_wizard()

    try:
        _dispatch(args)
    except BaudNotSupported as exc:
        sys.exit(f"[baud] {exc}")


if __name__ == "__main__":  # pragma: no cover
    main()

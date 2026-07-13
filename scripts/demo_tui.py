#!/usr/bin/env python3
"""Captura un frame representatiu de la TUI en directe (per a docs/README).

No toca hardware: alimenta el RichMonitor amb un estat de bateria a mig
correr i exporta el render actual a text i SVG. Nomes per documentar l'aspecte.
"""
from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rs485_labtest.monitor import RichMonitor  # noqa: E402


def build_frame() -> RichMonitor:
    import time

    m = RichMonitor("0.3.0")
    # estat inicial sense engegar la sessio Live (nomes volem un frame estatic)
    m.meta = dict(label="NDR6_protoB_Vcm+7V", profile="standard", seed=1830294821)
    m.n_tests = 12
    m.base = "results/rs485_x"
    m.t_start = time.monotonic() - 132.0

    # tests ja completats
    done = [
        ("sanity@115200", 115200, 210, 210, 0, dict(p50=1.8, p99=2.4), "PASS", []),
        ("turnaround_gap0@115200", 115200, 1893, 1893, 0, dict(p50=1.7, p99=2.2), "PASS", []),
        ("min_frames@115200", 115200, 2104, 2104, 0, dict(p50=1.4, p99=1.9), "PASS", []),
        ("pattern_0x55@115200", 115200, 1502, 1502, 0, dict(p50=4.1, p99=4.8), "PASS", []),
        ("pattern_0x00_DC@115200", 115200, 1498, 1483, 47, {}, "FAIL",
         ["47B de brossa fora de trama"]),
    ]
    for name, baud, tx, ok, junk, lat, v, reasons in done:
        m.test_start(0, 12, name, "traffic")
        m.test_end(dict(name=name, baud=baud, tx=tx, ok=ok, junk_bytes=junk,
                        crc_err=0, mismatch=0, seq_err=0, timeout=tx - ok,
                        lat=lat, verdict=v, reasons=reasons))

    # test en curs
    m.test_start(6, 12, "pattern_0xFF_DC", "traffic")
    lat = [3.9 + (i % 7) * 0.12 for i in range(320)]
    m.cur["t0"] -= 18.5   # simula temps transcorregut dins del test
    m.test_progress(dict(name="pattern_0xFF_DC", baud=115200, tx=741, ok=741,
                         crc_err=0, mismatch=0, seq_err=0, timeout=0,
                         junk_bytes=0, latencies_ms=lat, duration_s=45,
                         collide=False))
    return m


def main() -> None:
    m = build_frame()
    rec = Console(record=True, width=98)
    rec.print(m._render())
    rec.print()
    outdir = Path(__file__).resolve().parents[1] / "docs" / "img"
    outdir.mkdir(parents=True, exist_ok=True)
    rec.save_svg(str(outdir / "live_tui.svg"), title="rs485-labtest live TUI")
    # tambe a stdout per veure'l a la terminal
    Console(width=98).print(m._render())
    print(f"\nSVG desat a {outdir / 'live_tui.svg'}")


if __name__ == "__main__":
    main()

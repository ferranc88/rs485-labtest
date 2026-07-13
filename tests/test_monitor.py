"""Tests dels monitors de feedback: sparkline, sortida plana i TUI rich."""

import io

from fakes import FakeTransport, PerfectDUT, make_result
from rs485_labtest.engine import TestEngine
from rs485_labtest.monitor import (
    NullMonitor,
    PlainMonitor,
    RichMonitor,
    make_monitor,
    sparkline,
)


# ------------------------------------------------------------------ sparkline
def test_sparkline_empty():
    assert sparkline([]) == ""


def test_sparkline_flat_series_is_lowest_block():
    assert sparkline([5.0, 5.0, 5.0]) == "▁▁▁"


def test_sparkline_monotonic_ends_high():
    s = sparkline([float(i) for i in range(8)])
    assert len(s) == 8
    assert s[0] == "▁"
    assert s[-1] == "█"


def test_sparkline_respects_width():
    assert len(sparkline([float(i) for i in range(100)], width=20)) == 20


# --------------------------------------------------------------- make_monitor
def test_quiet_forces_null_monitor():
    m = make_monitor("rich", quiet=True, version="0.3.0")
    assert isinstance(m, NullMonitor)


def test_plain_mode_gives_plain_monitor():
    m = make_monitor("plain", quiet=False, version="0.3.0")
    assert isinstance(m, PlainMonitor)


def test_auto_without_tty_falls_back_to_plain():
    m = make_monitor("auto", quiet=False, version="0.3.0", stream=io.StringIO())
    assert isinstance(m, PlainMonitor)


# ------------------------------------------------------------- PlainMonitor IO
def test_plain_monitor_reproduces_classic_output(capsys):
    m = PlainMonitor("0.3.0")
    meta = dict(label="proto", profile="smoke", seed=42)
    m.battery_start(meta, 12, "results/rs485_proto_X")
    m.test_start(1, 12, "sanity@115200", "traffic")
    res = make_result(tx=200, ok=200,
                      verdict="PASS", reasons=[], lat=dict(p50=1.8, p99=2.4))
    m.test_end(res)
    m.battery_end([res], n_fail=0, elapsed_s=94.2, base="results/rs485_proto_X")
    out = capsys.readouterr().out
    assert "=== BATERIA RS-485 v0.3.0 ===" in out
    assert "[ 1/12] sanity@115200" in out
    # descriu que fa i per que cada test
    assert "què:" in out and "per què:" in out
    assert "→ PASS tx=200 ok=200 p50=1.8ms p99=2.4ms" in out
    assert "RESULTAT GLOBAL: PASS (0 FAIL / 1 tests, 94.2s)" in out


def test_null_monitor_is_silent(capsys):
    m = NullMonitor()
    m.battery_start({}, 1, "b")
    m.test_start(1, 1, "t", "traffic")
    m.test_end(make_result(verdict="PASS", reasons=[], lat={}))
    m.battery_end([], 0, 1.0, "b")
    assert capsys.readouterr().out == ""


# -------------------------------------------------------- RichMonitor drivable
def test_rich_monitor_runs_a_full_battery_without_error():
    # Console cap a un buffer amb terminal forcat: exercita tot el cami de render
    from rich.console import Console

    m = RichMonitor("0.3.0")
    m.console = Console(file=io.StringIO(), force_terminal=True, width=100)

    m.battery_start(dict(label="proto", profile="smoke", seed=1), 3, "b")
    m.test_start(1, 3, "turnaround_gap0", "traffic")
    for tx in range(1, 40):
        m.test_progress(make_result(tx=tx, ok=tx,
                                    latencies_ms=[1.0 + 0.01 * tx] * tx,
                                    duration_s=8))
    m.test_end(make_result(tx=40, ok=40, verdict="PASS", reasons=[],
                           lat=dict(p50=1.2, p99=1.4)))

    m.test_start(2, 3, "idle_monitor", "idle")
    m.test_progress(dict(name="idle_monitor", idle_test=True, raw_bytes=17,
                         duration_s=5))
    m.test_end(dict(name="idle_monitor", idle_test=True, raw_bytes=17,
                    junk_bytes=17, verdict="FAIL",
                    reasons=["17B rebuts"], lat={}))

    m.baud_change(921600, ok=True)
    m.battery_end([{"verdict": "PASS"}, {"verdict": "FAIL"}], n_fail=1,
                  elapsed_s=12.0, base="b")

    output = m.console.file.getvalue()
    assert "RS-485 labtest" in output
    assert "RESULTAT GLOBAL" in output
    assert m.n_pass == 1 and m.n_fail == 1


def test_engine_emits_live_progress_through_real_run():
    # El motor real ha de disparar el callback de progres mentre corre,
    # no nomes al final: aixo es el que fa possible el feedback en directe.
    seen: list[dict] = []
    tp = FakeTransport(PerfectDUT())
    eng = TestEngine(tp, seed=1, on_progress=lambda res: seen.append(dict(res)),
                     progress_dt=0.0)   # sense escanyar, per capturar-ho tot
    res = eng.run_traffic_test("sanity", "counter", 8, 0, duration_s=0.3)
    assert len(seen) >= 2                       # progres emes durant el test
    assert seen[-1]["tx"] <= res["tx"]          # snapshots creixents
    assert seen[0]["tx"] < res["tx"]            # el primer es d'abans d'acabar


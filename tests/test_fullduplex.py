"""Tests del mode 4 fils (full-duplex): pla, carrega simultania i validacio."""

import pytest

from fakes import BitFlipDUT, FakeTransport, PerfectDUT
from rs485_labtest.battery import battery_plan, verdict
from rs485_labtest.cli import main
from rs485_labtest.engine import TestEngine


# ------------------------------------------------------------------ el pla
def test_plan_half_duplex_has_collisions_and_no_fullduplex():
    names = [n for n, _, _ in battery_plan("smoke", [], 115200, duplex="half")]
    assert any(n.startswith("collision_blind") for n in names)
    assert any(n.startswith("post_collision") for n in names)
    assert not any(n.startswith("fullduplex") for n in names)


def test_plan_full_duplex_drops_collisions_and_adds_fullduplex():
    plan = battery_plan("smoke", [], 115200, duplex="full")
    names = [n for n, _, _ in plan]
    # en full-duplex no hi ha bus compartit: els tests de colisio no apliquen
    assert not any(n.startswith("collision_blind") for n in names)
    assert not any(n.startswith("post_collision") for n in names)
    # i s'hi afegeixen els de carrega simultania
    assert any(n.startswith("fullduplex_load") for n in names)
    assert any(n.startswith("fullduplex_sat250") for n in names)
    assert sum(1 for _, k, _ in plan if k == "fullduplex") == 2


def test_plan_full_duplex_keeps_failsafe_and_idle_tests():
    names = [n for n, _, _ in battery_plan("smoke", [], 115200, duplex="full")]
    # el failsafe segueix aplicant a cada parell
    assert any(n.startswith("idle_monitor") for n in names)
    assert any(n.startswith("failsafe_paused") for n in names)


def test_plan_full_duplex_selection_of_fullduplex_only():
    plan = battery_plan("smoke", [], 115200, tests=["fullduplex_load"], duplex="full")
    assert [n for n, _, _ in plan] == ["fullduplex_load@115200"]


# ------------------------------------------------- carrega simultania (motor)
def test_fullduplex_perfect_dut_passes():
    tp = FakeTransport(PerfectDUT())
    eng = TestEngine(tp, seed=1)
    res = eng.run_fullduplex_test("fullduplex_load", "random", 64,
                                  window=8, duration_s=0.4)
    assert res["fullduplex"] is True
    assert res["window"] == 8
    assert res["ok"] > 0
    assert res["junk_bytes"] == 0
    assert res["latencies_ms"]
    assert verdict(res, 0.0, 0.0)[0] == "PASS"


def test_fullduplex_keeps_several_frames_in_flight():
    # el sentit del test: NO serialitza; ha d'omplir la finestra abans de
    # cobrar els ecos (en 2 fils aixo seria una colisio)
    seen_inflight = []

    class CountingDUT(PerfectDUT):
        def on_write(self, data, tp):
            # bytes pendents de llegir pel master = ecos acumulats en vol
            seen_inflight.append(len(tp.rx))
            super().on_write(data, tp)

    tp = FakeTransport(CountingDUT())
    eng = TestEngine(tp, seed=1)
    eng.run_fullduplex_test("fd", "random", 8, window=8, duration_s=0.3)
    assert max(seen_inflight) > 0        # hi havia ecos sense recollir en escriure


def test_fullduplex_all_frames_resolve_no_leak():
    tp = FakeTransport(PerfectDUT())
    eng = TestEngine(tp, seed=1)
    res = eng.run_fullduplex_test("fd", "counter", 32, window=4, duration_s=0.3)
    # cada trama comptada acaba en ok, mismatch, seq_err o timeout
    assert res["tx"] == res["ok"] + res["mismatch"] + res["timeout"]


def test_fullduplex_detects_corruption():
    tp = FakeTransport(BitFlipDUT(p=0.02, seed=7, recompute_crc=True))
    eng = TestEngine(tp, seed=1)
    res = eng.run_fullduplex_test("fd", "random", 64, window=4,
                                  duration_s=0.4, timeout=0.1)
    assert res["mismatch"] > 0
    v, reasons = verdict(res, 0.0, 0.0)
    assert v == "FAIL"
    assert any("payload corrupte" in r for r in reasons)


def test_fullduplex_timeout_budget_accounts_for_window():
    # amb finestra gran, una trama fa cua darrere les altres: el deadline
    # ha de ser prou llarg o tot serien falsos timeouts
    tp = FakeTransport(PerfectDUT())
    eng = TestEngine(tp, seed=1)
    res = eng.run_fullduplex_test("fd", "random", 250, window=16,
                                  duration_s=0.4)
    assert res["timeout"] == 0
    assert res["ok"] > 0


# ------------------------------------------------------------- validacio CLI
def test_cli_rejects_fullduplex_test_on_half_duplex():
    with pytest.raises(SystemExit) as ei:
        main(["battery", "--port", "x", "--interface", "rs485-half",
              "--tests", "fullduplex_load"])
    assert "full-duplex" in str(ei.value)


def test_cli_rejects_collision_test_on_full_duplex():
    with pytest.raises(SystemExit) as ei:
        main(["battery", "--port", "x", "--interface", "rs232",
              "--tests", "collision_blind"])
    assert "half-duplex" in str(ei.value)

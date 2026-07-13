"""Tests del motor contra DUTs simulats: cada defecte ha de disparar el
veredicte que li toca. Aquest es el valor real de la suite (§3.3 del handoff).
"""

from fakes import (
    BitFlipDUT,
    FakeTransport,
    LatchUpDUT,
    NoisyIdleDUT,
    PerfectDUT,
    SlowTurnaroundDUT,
)
from rs485_labtest.battery import verdict
from rs485_labtest.engine import TestEngine


def make_engine(dut, seed=123):
    tp = FakeTransport(dut)
    return TestEngine(tp, seed=seed), tp


# ---------------------------------------------------------------- PerfectDUT
def test_perfect_dut_traffic_passes():
    eng, _ = make_engine(PerfectDUT())
    res = eng.run_traffic_test("sanity", "counter", 8, 0, duration_s=0.4)
    v, reasons = verdict(res, 0.0, 0.0)
    assert v == "PASS", reasons
    assert res["ok"] > 0
    assert res["junk_bytes"] == 0
    assert res["latencies_ms"]


def test_perfect_dut_idle_is_silent():
    eng, _ = make_engine(PerfectDUT())
    res = eng.run_idle_monitor("idle_monitor", duration_s=0.3)
    assert res["raw_bytes"] == 0
    assert verdict(res, 0.0, 0.0)[0] == "PASS"


def test_perfect_dut_survives_collision():
    eng, _ = make_engine(PerfectDUT())
    res = eng.run_traffic_test("collision_blind", "random", 32, 0,
                               duration_s=0.2, collide=True)
    assert verdict(res, 0.0, 0.0)[0] == "INFO"
    ok, tries = eng.sanity_ping()
    assert ok == tries                     # post_collision PASS


def test_perfect_dut_remote_baud_change():
    eng, tp = make_engine(PerfectDUT())
    assert eng.set_remote_baud(921600) is True
    assert tp.baudrate == 921600


# -------------------------------------------------------------- NoisyIdleDUT
def test_noisy_idle_dut_fails_idle_monitor():
    eng, _ = make_engine(NoisyIdleDUT(rate_bps=2000))
    res = eng.run_idle_monitor("idle_monitor", duration_s=0.3)
    assert res["raw_bytes"] > 0
    v, reasons = verdict(res, 0.0, 0.0)
    assert v == "FAIL"
    assert any("failsafe" in r for r in reasons)


# --------------------------------------------------------- SlowTurnaroundDUT
def test_slow_turnaround_dut_times_out():
    eng, _ = make_engine(SlowTurnaroundDUT(delay_s=0.3))
    res = eng.run_traffic_test("turnaround_gap0", "random", 8, 0,
                               duration_s=1.2, timeout=0.1)
    assert res["ok"] == 0
    assert res["timeout"] > 0
    assert verdict(res, 0.0, 0.0)[0] == "FAIL"


# ------------------------------------------------------------------ BitFlip
def test_bitflip_dut_triggers_crc_errors():
    eng, _ = make_engine(BitFlipDUT(p=0.02, seed=7))
    res = eng.run_traffic_test("ber", "random", 64, 0,
                               duration_s=0.6, timeout=0.05)
    assert res["ok"] == 0
    assert res["crc_err"] + res["junk_bytes"] > 0
    assert verdict(res, 0.0, 0.0)[0] == "FAIL"


def test_bitflip_dut_valid_crc_triggers_mismatch():
    # El cas mes perillos: framing valid pero payload equivocat
    eng, _ = make_engine(BitFlipDUT(p=0.02, seed=7, recompute_crc=True))
    res = eng.run_traffic_test("ber", "random", 64, 0,
                               duration_s=0.4, timeout=0.2)
    assert res["mismatch"] > 0
    v, reasons = verdict(res, 0.0, 0.0)
    assert v == "FAIL"
    assert any("payload corrupte" in r for r in reasons)


# ------------------------------------------------------------------ LatchUp
def test_latchup_dut_fails_post_collision():
    dut = LatchUpDUT()
    eng, _ = make_engine(dut)

    ok, tries = eng.sanity_ping()
    assert ok == tries                     # abans de la colisio, el link va be

    eng.run_traffic_test("collision_blind", "random", 32, 0,
                         duration_s=0.2, collide=True)
    assert dut.latched is True

    ok, tries = eng.sanity_ping()
    res = dict(name="post_collision", baud=115200, tx=tries, ok=ok,
               crc_err=0, mismatch=0, seq_err=0, timeout=tries - ok,
               junk_bytes=0, latencies_ms=[], post_collision=True)
    v, _ = verdict(res, 0.0, 0.0)
    assert ok == 0
    assert v == "FAIL"

"""Tests dels criteris PASS/FAIL, estadistics de latencia, BER i pla de bateria."""

from fakes import make_result
from rs485_labtest.battery import battery_plan, ber_bound, lat_stats, verdict
from rs485_labtest.protocol import HDR_LEN


# ------------------------------------------------------------------- verdict
def test_clean_run_passes():
    v, reasons = verdict(make_result(), max_fer=0.0, max_p99_ms=0.0)
    assert (v, reasons) == ("PASS", [])


def test_single_timeout_fails_with_default_fer():
    v, reasons = verdict(make_result(timeout=1, ok=99), 0.0, 0.0)
    assert v == "FAIL"
    assert any("FER" in r for r in reasons)


def test_fer_threshold_can_be_relaxed():
    v, _ = verdict(make_result(timeout=1, ok=99), 0.05, 0.0)
    assert v == "PASS"


def test_junk_bytes_fail():
    v, reasons = verdict(make_result(junk_bytes=3), 0.0, 0.0)
    assert v == "FAIL"
    assert any("brossa" in r for r in reasons)


def test_mismatch_has_specific_reason():
    v, reasons = verdict(make_result(mismatch=2, ok=98), 0.0, 0.0)
    assert v == "FAIL"
    assert any("payload corrupte" in r for r in reasons)


def test_idle_silent_passes():
    res = dict(name="idle", idle_test=True, raw_bytes=0)
    assert verdict(res, 0.0, 0.0) == ("PASS", [])


def test_idle_ghost_bytes_fail():
    res = dict(name="idle", idle_test=True, raw_bytes=17)
    v, reasons = verdict(res, 0.0, 0.0)
    assert v == "FAIL"
    assert any("failsafe" in r for r in reasons)


def test_collision_is_informative():
    v, reasons = verdict(make_result(collide=True), 0.0, 0.0)
    assert v == "INFO"
    assert any("post_collision" in r for r in reasons)


def test_p99_threshold():
    lat = [1.0] * 99 + [50.0]
    v, reasons = verdict(make_result(latencies_ms=lat), 0.0, 10.0)
    assert v == "FAIL"
    assert any("p99" in r for r in reasons)
    v2, _ = verdict(make_result(latencies_ms=lat), 0.0, 0.0)   # 0 = sense llindar
    assert v2 == "PASS"


# ----------------------------------------------------------------- lat_stats
def test_lat_stats_empty():
    assert lat_stats([]) == {}


def test_lat_stats_percentiles():
    st = lat_stats([float(i) for i in range(1, 101)])
    assert st["n"] == 100
    assert st["min"] == 1.0
    assert st["max"] == 100.0
    assert st["p50"] == 51.0
    assert st["p99"] == 100.0


# ----------------------------------------------------------------- ber_bound
def test_ber_bound_zero_errors_is_upper_bound_not_zero():
    res = make_result(tx=1000, crc_err=0, mismatch=0, timeout=0)
    ub, is_bound = ber_bound(res, size=128)
    bits = 1000 * (HDR_LEN + 128 + 2) * 10
    assert is_bound is True
    assert ub == 3.0 / bits
    assert ub > 0.0                      # mai "BER = 0"


def test_ber_bound_with_errors_is_estimate():
    res = make_result(tx=1000, crc_err=5, ok=995)
    est, is_bound = ber_bound(res, size=128)
    assert is_bound is False
    assert est > 0


def test_ber_bound_no_traffic():
    res = make_result(tx=0, ok=0)
    assert ber_bound(res, size=8) == (None, None)


# -------------------------------------------------------------- battery_plan
def test_battery_plan_core_has_12_tests_plus_offset_sweep():
    plan = battery_plan("smoke", [], 115200)
    kinds = [k for _, k, _ in plan]
    assert len(plan) == 18                    # 12 del nucli + 6 desajustos de baud
    assert kinds.count("traffic") == 10
    assert kinds.count("idle") == 1
    assert kinds.count("ping") == 1
    assert kinds.count("offset") == 6


def test_battery_plan_baud_sweep_adds_subset_and_restores_base():
    plan = battery_plan("smoke", [9600, 921600], 115200)
    names = [n for n, _, _ in plan]
    assert "__setbaud__9600" in names
    assert "turnaround_gap0@9600" in names
    assert "idle_monitor@921600" in names
    assert names[-1] == "__setbaud__115200"   # restaura el baud base al final


def test_battery_plan_base_baud_not_repeated():
    plan = battery_plan("smoke", [115200], 115200)
    assert len(plan) == 18                    # cap __setbaud__ per al baud base

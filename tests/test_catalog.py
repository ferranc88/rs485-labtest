"""Tests del cataleg de descripcions i de la seleccio de tests al pla."""

from rs485_labtest.battery import battery_plan
from rs485_labtest.catalog import (
    TEST_CATALOG,
    TEST_ORDER,
    base_name,
    describe,
    unknown_tests,
)


def test_order_and_catalog_are_consistent():
    assert set(TEST_ORDER) == set(TEST_CATALOG)
    assert len(TEST_ORDER) == 15


def test_wire_specific_sets_are_known_and_disjoint():
    from rs485_labtest.catalog import ONLY_2WIRE, ONLY_4WIRE
    assert ONLY_2WIRE <= set(TEST_ORDER)
    assert ONLY_4WIRE <= set(TEST_ORDER)
    assert not (ONLY_2WIRE & ONLY_4WIRE)


def test_every_entry_has_the_four_fields():
    for name, info in TEST_CATALOG.items():
        assert info["title"] and info["what"] and info["why"] and info["icon"], name


def test_base_name_strips_baud_suffix():
    assert base_name("sanity@115200") == "sanity"
    assert base_name("idle_monitor") == "idle_monitor"


def test_describe_works_with_and_without_suffix():
    assert describe("turnaround_gap0@307200")["title"] == describe("turnaround_gap0")["title"]
    assert describe("no_existeix") is None


def test_unknown_tests():
    assert unknown_tests(["sanity", "bogus", "idle_monitor"]) == ["bogus"]
    assert unknown_tests(TEST_ORDER) == []


# ---------------------------------------------- seleccio de tests al battery_plan
def test_battery_plan_runs_all_by_default():
    plan = battery_plan("smoke", [], 115200)
    kinds = [k for _, k, _ in plan if k in ("traffic", "idle", "ping", "offset")]
    assert len(kinds) == 18                   # 12 del nucli + 6 desajustos


def test_describe_matches_offset_entry_names():
    from rs485_labtest.catalog import describe
    assert describe("baud_offset+2%@115200")["title"] == "Marge de tolerancia de baud"


def test_battery_plan_filters_to_selected_tests():
    plan = battery_plan("smoke", [], 115200, tests=["sanity", "idle_monitor"])
    names = [n for n, _, _ in plan]
    assert names == ["sanity@115200", "idle_monitor@115200"]


def test_battery_plan_selection_keeps_canonical_order():
    # demanats desordenats -> surten en l'ordre canonic
    plan = battery_plan("smoke", [], 115200,
                        tests=["idle_monitor", "sanity", "min_frames"])
    names = [base_name(n) for n, _, _ in plan]
    assert names == ["sanity", "min_frames", "idle_monitor"]


def test_battery_plan_selection_applies_to_baud_sweep_subset():
    # nomes idle_monitor esta al subset del barrido; si no el tries, no surt al baud extra
    plan = battery_plan("smoke", [307200], 115200, tests=["sanity"])
    names = [n for n, _, _ in plan]
    assert "sanity@115200" in names
    assert "__setbaud__307200" in names
    assert not any(n.endswith("@307200") for n in names)   # sanity no es del subset

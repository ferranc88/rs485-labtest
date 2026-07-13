"""Tests de la logica pura de l'assistent (parseig i construccio de Namespace)."""

import pytest

from rs485_labtest.wizard import (
    build_namespace,
    parse_baud_list,
    parse_test_selection,
)


# --------------------------------------------------------------- parse_baud_list
def test_parse_baud_list_mixed_separators_and_dedupe():
    assert parse_baud_list("9600, 307200 921600 307200") == [9600, 307200, 921600]


def test_parse_baud_list_empty():
    assert parse_baud_list("   ") == []


def test_parse_baud_list_rejects_nonpositive_and_garbage():
    with pytest.raises(ValueError):
        parse_baud_list("0")
    with pytest.raises(ValueError):
        parse_baud_list("nose")


# ---------------------------------------------------------- parse_test_selection
def test_parse_test_selection_by_index_and_name():
    assert parse_test_selection("1 3 idle_monitor") == [
        "sanity", "min_frames", "idle_monitor"]


def test_parse_test_selection_canonical_order_and_dedupe():
    # entrada desordenada i repetida -> ordre canonic, sense duplicats
    assert parse_test_selection("idle_monitor 1 sanity 9") == [
        "sanity", "idle_monitor"]


def test_parse_test_selection_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        parse_test_selection("99")
    with pytest.raises(ValueError):
        parse_test_selection("no_existeix")


# -------------------------------------------------------------- build_namespace
def test_build_namespace_duo_has_slave_port():
    mode, ns = build_namespace(dict(
        mode="duo", port="A", slave_port="B", baud=307200,
        bauds=[921600], tests=["sanity"], label="x", live="rich"))
    assert mode == "duo"
    assert ns.slave_port == "B"
    assert ns.baud == 307200
    assert ns.bauds == [921600]
    assert ns.tests == ["sanity"]
    assert ns.live == "rich"


def test_build_namespace_battery_has_no_slave_port():
    _, ns = build_namespace(dict(mode="battery", port="A"))
    assert not hasattr(ns, "slave_port")


def test_build_namespace_empty_tests_becomes_none():
    _, ns = build_namespace(dict(mode="battery", port="A", tests=[]))
    assert ns.tests is None


def test_build_namespace_defaults():
    _, ns = build_namespace(dict(mode="battery", port="A"))
    assert ns.baud == 115200
    assert ns.profile == "standard"
    assert ns.max_fer == 0.0
    assert ns.seed is None
    assert ns.verbose is False and ns.quiet is False

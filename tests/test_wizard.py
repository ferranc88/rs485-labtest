"""Tests de la logica pura de l'assistent (parseig, Namespace i presets)."""

import json

import pytest

from rs485_labtest.wizard import (
    build_namespace,
    load_presets,
    parse_baud_list,
    parse_test_selection,
    preset_answers,
    preset_summary,
    save_preset,
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


# ---------------------------------------------------------------------- presets
def test_load_presets_missing_file_is_empty(tmp_path):
    assert load_presets(tmp_path / "no_existeix.json") == {}


def test_load_presets_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "presets.json"
    p.write_text("{trencat", encoding="utf-8")
    assert load_presets(p) == {}


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "presets.json"   # el directori es crea sol
    answers = dict(mode="duo", port="/dev/A", slave_port="/dev/B",
                   baud=307200, bauds=[921600], tests=["sanity"],
                   label="NDR6_Vcm+7V", profile="standard", live="rich")
    save_preset("ndr6", answers, p)
    data = load_presets(p)
    assert "ndr6" in data
    assert data["ndr6"]["baud"] == 307200
    assert data["ndr6"]["_saved_at"]        # marca de temps afegida

    # el preset reconstrueix exactament la mateixa configuracio
    mode, ns = build_namespace(preset_answers(data["ndr6"]))
    assert mode == "duo"
    assert ns.slave_port == "/dev/B"
    assert ns.baud == 307200
    assert ns.tests == ["sanity"]


def test_save_preset_overwrites_same_name_keeps_others(tmp_path):
    p = tmp_path / "presets.json"
    save_preset("a", dict(mode="battery", port="X", baud=9600), p)
    save_preset("b", dict(mode="battery", port="Y"), p)
    save_preset("a", dict(mode="battery", port="X", baud=115200), p)
    data = load_presets(p)
    assert set(data) == {"a", "b"}
    assert data["a"]["baud"] == 115200


def test_preset_answers_strips_internal_keys():
    ans = preset_answers({"mode": "duo", "port": "A", "_saved_at": "2026-07-13"})
    assert "_saved_at" not in ans
    assert ans["mode"] == "duo"


def test_preset_summary_is_one_readable_line():
    s = preset_summary("ndr6", dict(mode="duo", port="/dev/A", baud=307200,
                                    profile="standard", label="Vcm+7V",
                                    _saved_at="2026-07-13T19:30:00"))
    assert s.startswith("ndr6: ")
    assert "307200bps" in s and "Vcm+7V" in s and "2026-07-13" in s
    assert "\n" not in s


def test_presets_file_is_valid_json(tmp_path):
    p = tmp_path / "presets.json"
    save_preset("x", dict(mode="battery", port="A", tests=None, seed=None), p)
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["x"]["tests"] is None

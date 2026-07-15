"""Tests de les interficies: pla segons duplex, guia i traçabilitat."""

import pytest

from rs485_labtest.battery import battery_plan
from rs485_labtest.catalog import FULL_DUPLEX_ONLY, HALF_DUPLEX_ONLY
from rs485_labtest.cli import build_parser, main
from rs485_labtest.interfaces import (
    COMMON_HINTS,
    DEFAULT_INTERFACE,
    INTERFACES,
    describe_interface,
    interface_duplex,
    interface_for_wires,
    interface_hints,
)
from rs485_labtest.report import write_reports
from rs485_labtest.wizard import build_namespace, resolve_interface

ALL = list(INTERFACES)


# ------------------------------------------------------------------ cataleg
def test_the_four_interfaces_we_test_are_there():
    assert set(ALL) == {"rs485-half", "rs485-full", "rs422", "rs232"}


@pytest.mark.parametrize("name", ALL)
def test_every_interface_is_complete(name):
    info = INTERFACES[name]
    assert info["title"] and info["what"] and info["wiring"] and info["icon"]
    assert info["duplex"] in ("half", "full")
    assert info["hints"]


def test_duplex_mapping():
    assert interface_duplex("rs485-half") == "half"
    assert interface_duplex("rs485-full") == "full"
    assert interface_duplex("rs422") == "full"
    assert interface_duplex("rs232") == "full"


def test_unknown_interface_is_conservative():
    assert describe_interface("no_existeix") is None
    assert interface_duplex("no_existeix") == "half"     # el cas mes restrictiu


def test_wires_alias_maps_to_rs485():
    assert interface_for_wires(2) == "rs485-half"
    assert interface_for_wires(4) == "rs485-full"


# --------------------------------------------------------------------- guia
@pytest.mark.parametrize("name", ALL)
def test_hints_include_common_ones(name):
    assert set(COMMON_HINTS) <= set(interface_hints(name))


def test_rs232_guide_does_not_talk_about_differential_bias():
    # el punt de tot plegat: en single-ended, parlar de bias/A-B es enganyos
    hints = " ".join(interface_hints("rs232")).lower()
    assert "single-ended" in hints
    assert "no apliquen" in hints
    # cap consell de mirar el diferencial A-B
    assert "a-b" not in hints


def test_rs485_half_guide_does_talk_about_failsafe_bias():
    hints = " ".join(interface_hints("rs485-half")).lower()
    assert "bias de failsafe" in hints
    assert "a-b" in hints


def test_rs422_guide_says_driver_always_enabled():
    hints = " ".join(interface_hints("rs422")).lower()
    assert "sempre habilitat" in hints


# ---------------------------------------------------- el pla segueix el duplex
@pytest.mark.parametrize("name", ALL)
def test_plan_matches_the_interface_duplex(name):
    plan = battery_plan("smoke", [], 115200, duplex=interface_duplex(name))
    names = {n.split("@")[0] for n, _, _ in plan}
    if interface_duplex(name) == "half":
        assert HALF_DUPLEX_ONLY <= names
        assert not (FULL_DUPLEX_ONLY & names)
    else:
        assert FULL_DUPLEX_ONLY <= names
        assert not (HALF_DUPLEX_ONLY & names)


def test_full_duplex_interfaces_share_the_same_plan():
    # rs485-full, rs422 i rs232 son tots full-duplex punt a punt: mateix pla
    plans = {n: [x[0] for x in battery_plan("smoke", [], 115200,
                                            duplex=interface_duplex(n))]
             for n in ("rs485-full", "rs422", "rs232")}
    assert plans["rs485-full"] == plans["rs422"] == plans["rs232"]


# ---------------------------------------------------------------------- CLI
def test_cli_interface_default_and_choices():
    args = build_parser().parse_args(["battery", "--port", "x"])
    assert args.interface == DEFAULT_INTERFACE
    for name in ALL:
        parsed = build_parser().parse_args(
            ["battery", "--port", "x", "--interface", name])
        assert parsed.interface == name


def test_cli_rejects_unknown_interface():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["battery", "--port", "x",
                                   "--interface", "rs999"])


def test_cli_wires_alias_still_works():
    from rs485_labtest.cli import _resolve_interface

    args = build_parser().parse_args(["battery", "--port", "x", "--wires", "4"])
    _resolve_interface(args)
    assert args.interface == "rs485-full"


def test_cli_without_wires_keeps_the_chosen_interface():
    from rs485_labtest.cli import _resolve_interface

    args = build_parser().parse_args(["battery", "--port", "x",
                                      "--interface", "rs232"])
    _resolve_interface(args)
    assert args.interface == "rs232"        # l'alias no el trepitja


def test_cli_rs232_rejects_collision_tests():
    with pytest.raises(SystemExit) as ei:
        main(["battery", "--port", "x", "--interface", "rs232",
              "--tests", "post_collision"])
    assert "half-duplex" in str(ei.value)


# -------------------------------------------------------------- wizard/presets
def test_wizard_carries_the_interface():
    _, ns = build_namespace(dict(mode="battery", port="A", interface="rs422"))
    assert ns.interface == "rs422"


def test_wizard_defaults_to_rs485_half():
    _, ns = build_namespace(dict(mode="battery", port="A"))
    assert ns.interface == DEFAULT_INTERFACE


def test_old_preset_with_wires_is_migrated():
    # presets desats abans que existis --interface
    assert resolve_interface({"wires": 4}) == "rs485-full"
    assert resolve_interface({"wires": 2}) == "rs485-half"
    _, ns = build_namespace(dict(mode="battery", port="A", wires=4))
    assert ns.interface == "rs485-full"


def test_interface_wins_over_stale_wires_key():
    assert resolve_interface({"interface": "rs232", "wires": 2}) == "rs232"


# ------------------------------------------------------------------- informe
def _meta(**over):
    m = dict(script_version="0.3.0", timestamp_utc="20260714T000000Z",
             label="x", port="/dev/ttyUSB0", base_baud=115200, parity="N",
             stopbits=1, profile="smoke", seed=1, bauds=[], max_fer=0.0,
             max_p99_ms=0.0, platform="t", python="3.12", pyserial="3.5",
             operator_notes="", elapsed_s=1.0, aborted=False,
             interface="rs485-half")
    m.update(over)
    return m


def _results():
    return [dict(name="sanity@115200", baud=115200, tx=1, ok=1, crc_err=0,
                 mismatch=0, seq_err=0, timeout=0, junk_bytes=0,
                 verdict="PASS", reasons=[], lat={})]


def test_report_records_the_interface_under_test(tmp_path):
    base = str(tmp_path / "out")
    write_reports(base, _meta(interface="rs422"), _results(), [])
    md = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "**Interficie:** RS-422" in md
    assert "sempre habilitat" in md              # guia propia del RS-422


def test_report_guide_is_interface_specific(tmp_path):
    base = str(tmp_path / "out232")
    write_reports(base, _meta(interface="rs232"), _results(), [])
    md = (tmp_path / "out232.md").read_text(encoding="utf-8")
    assert "single-ended" in md
    # el consell de RS-485 no ha de sortir en un informe de RS-232
    assert "bias de failsafe insuficient" not in md

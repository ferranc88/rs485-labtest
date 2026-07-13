"""Tests de la CLI: parser, validacio de --tests i despatx del wizard."""

import pytest

from rs485_labtest.cli import build_parser, main


def test_parser_has_wizard_and_tests_option():
    ap = build_parser()
    args = ap.parse_args(["battery", "--port", "x", "--tests", "sanity", "idle_monitor"])
    assert args.tests == ["sanity", "idle_monitor"]
    # el subcomandament wizard existeix i no exigeix --port
    assert ap.parse_args(["wizard"]).mode == "wizard"


def test_tests_defaults_to_none_when_absent():
    args = build_parser().parse_args(["battery", "--port", "x"])
    assert args.tests is None


def test_unknown_test_name_exits_with_message(capsys):
    with pytest.raises(SystemExit) as ei:
        main(["battery", "--port", "x", "--tests", "sanity", "bogus"])
    # sys.exit(str) posa el missatge al codi de sortida
    assert "bogus" in str(ei.value)


def test_duo_also_validates_tests():
    with pytest.raises(SystemExit) as ei:
        main(["duo", "--port", "A", "--slave-port", "B", "--tests", "nope"])
    assert "nope" in str(ei.value)


def test_wizard_dispatches_built_namespace(monkeypatch):
    # run_wizard retorna un Namespace de mode 'battery' amb un test dolent:
    # _dispatch -> _validate_tests ha de fer sortir amb el missatge d'error.
    import argparse

    def fake_wizard():
        ns = argparse.Namespace(
            mode="battery", port="X", baud=115200, parity="N", stopbits=1.0,
            profile="smoke", bauds=[], tests=["bogus"], label="", notes="",
            outdir="results", seed=1, max_fer=0.0, max_p99=0.0, live="plain",
            verbose=False, quiet=False)
        return "battery", ns

    monkeypatch.setattr("rs485_labtest.wizard.run_wizard", fake_wizard)
    with pytest.raises(SystemExit) as ei:
        main(["wizard"])
    assert "bogus" in str(ei.value)

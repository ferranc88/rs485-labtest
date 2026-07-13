"""Tests de la generacio d'informes (JSON + Markdown + CSV)."""

import csv
import json

from rs485_labtest.report import write_reports


def _meta(**overrides):
    meta = dict(script_version="0.3.0", timestamp_utc="20260713T080000Z",
                label="unittest", port="/dev/ttyUSB0", base_baud=115200,
                parity="N", stopbits=1, profile="smoke", seed=1234,
                bauds=[], max_fer=0.0, max_p99_ms=0.0,
                platform="test", python="3.11.0", pyserial="3.5",
                operator_notes="", elapsed_s=12.3, aborted=False)
    meta.update(overrides)
    return meta


def _results():
    return [
        dict(name="sanity@115200", baud=115200, tx=100, ok=100, crc_err=0,
             mismatch=0, seq_err=0, timeout=0, junk_bytes=0, verdict="PASS",
             reasons=[], lat=dict(n=100, min=1.0, p50=1.2, p95=1.5, p99=2.0,
                                  max=2.5, stdev=0.2), ber="<2.61e-06 @95%CL"),
        dict(name="idle_monitor@115200", baud=115200, duration_s=5,
             idle_test=True, raw_bytes=17, junk_bytes=17, tx=0, ok=0,
             crc_err=0, mismatch=0, seq_err=0, timeout=0, verdict="FAIL",
             reasons=["17B rebuts amb bus en repos (failsafe sospitos)"], lat={}),
    ]


def _lat_rows():
    return [("sanity@115200", 115200, 1.234), ("sanity@115200", 115200, 1.5)]


def test_three_files_generated(tmp_path):
    base = str(tmp_path / "rs485_unittest_20260713T080000Z")
    write_reports(base, _meta(), _results(), _lat_rows())
    assert (tmp_path / "rs485_unittest_20260713T080000Z.json").exists()
    assert (tmp_path / "rs485_unittest_20260713T080000Z.md").exists()
    assert (tmp_path / "rs485_unittest_20260713T080000Z_latencies.csv").exists()


def test_json_structure(tmp_path):
    base = str(tmp_path / "out")
    write_reports(base, _meta(), _results(), _lat_rows())
    with open(base + ".json") as f:
        doc = json.load(f)
    assert doc["meta"]["label"] == "unittest"
    assert doc["meta"]["seed"] == 1234
    assert len(doc["results"]) == 2
    assert doc["results"][0]["verdict"] == "PASS"
    assert doc["results"][1]["reasons"]


def test_csv_rows(tmp_path):
    base = str(tmp_path / "out")
    write_reports(base, _meta(), _results(), _lat_rows())
    with open(base + "_latencies.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["test", "baud", "rtt_ms"]
    assert len(rows) == 3


def test_markdown_content(tmp_path):
    base = str(tmp_path / "out")
    write_reports(base, _meta(), _results(), _lat_rows())
    with open(base + ".md") as f:
        md = f.read()
    assert "# Informe estres RS-485 - unittest" in md
    assert "| 1 | sanity@115200 |" in md
    assert "**PASS**" in md and "**FAIL**" in md
    assert "## Motius de FAIL" in md
    assert "failsafe sospitos" in md
    assert "## Guia d'interpretacio" in md
    assert "<2.61e-06 @95%CL" in md         # la BER es cota, no zero


def test_markdown_marks_aborted_run(tmp_path):
    base = str(tmp_path / "out")
    write_reports(base, _meta(aborted=True), _results(), _lat_rows())
    with open(base + ".md") as f:
        assert "INTERROMPUT" in f.read()


def test_markdown_without_fails_says_so(tmp_path):
    base = str(tmp_path / "out")
    results = [_results()[0]]
    write_reports(base, _meta(), results, _lat_rows())
    with open(base + ".md") as f:
        md = f.read()
    assert "## Sense fallades" in md
    assert "## Motius de FAIL" not in md

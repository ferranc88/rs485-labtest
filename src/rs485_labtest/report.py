"""Escriptura d'informes: JSON estructurat, Markdown llegible i CSV de latencies."""

from __future__ import annotations

import csv
import json
from typing import Any


def write_reports(base: str, meta: dict[str, Any], results: list[dict[str, Any]],
                  lat_rows: list[tuple[str, int, float]]) -> None:
    """Genera ``base.json``, ``base.md`` i ``base_latencies.csv``."""
    with open(base + ".json", "w") as f:
        json.dump(dict(meta=meta, results=results), f, indent=2)

    with open(base + "_latencies.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["test", "baud", "rtt_ms"])
        w.writerows(lat_rows)

    lines = [f"# Informe estres RS-485 - {meta['label']}", ""]
    wires = meta.get("wires", 2)
    lines += [f"- **Data (UTC):** {meta['timestamp_utc']}",
              f"- **Port / baud base:** {meta['port']} @ {meta['base_baud']} "
              f"({meta['parity']},{meta['stopbits']})",
              f"- **Cablejat:** {wires} fils "
              f"({'full-duplex' if wires == 4 else 'half-duplex'})",
              f"- **Perfil:** {meta['profile']} | **Seed:** {meta['seed']} "
              f"| **Durada:** {meta['elapsed_s']} s"
              + (" | **INTERROMPUT**" if meta.get("aborted") else ""),
              f"- **Entorn:** {meta['platform']}, Python {meta['python']}, "
              f"pyserial {meta['pyserial']}",
              f"- **Criteris:** FER <= {meta['max_fer']}, junk == 0"
              + (f", p99 <= {meta['max_p99_ms']} ms" if meta['max_p99_ms'] else ""), ""]
    if meta.get("operator_notes"):
        lines += [f"- **Notes operador:** {meta['operator_notes']}", ""]

    lines += ["| # | Test | Baud | TX | OK | CRC | Mism | Seq | TO | Junk(B) "
              "| p50/p99 (ms) | BER | Veredicte |",
              "|---|------|------|----|----|-----|------|-----|----|---------"
              "|--------------|-----|-----------|"]
    for i, r in enumerate(results, 1):
        lat = r.get("lat") or {}
        latstr = f"{lat.get('p50', '-')}/{lat.get('p99', '-')}" if lat else "-"
        lines.append(f"| {i} | {r['name']} | {r.get('baud', '-')} | {r.get('tx', 0)} "
                     f"| {r.get('ok', 0)} | {r.get('crc_err', 0)} | {r.get('mismatch', 0)} "
                     f"| {r.get('seq_err', 0)} | {r.get('timeout', 0)} "
                     f"| {r.get('junk_bytes', r.get('raw_bytes', 0))} | {latstr} "
                     f"| {r.get('ber', '-')} | **{r['verdict']}** |")
    fails = [r for r in results if r["verdict"] == "FAIL"]
    lines += ["", "## Motius de FAIL" if fails else "## Sense fallades", ""]
    for r in fails:
        for reason in r["reasons"]:
            lines.append(f"- **{r['name']}**: {reason}")
    lines += ["", "## Guia d'interpretacio", "",
              "- **Junk amb bus en repos / idle_monitor FAIL** -> bias de failsafe insuficient; "
              "mirar diferencial A-B en idle amb sonda (ha de ser > +200 mV).",
              "- **Timeouts amb gap=0** -> el driver enable (auto-direccio) es queda actiu "
              "massa temps i trepitja la resposta.",
              "- **Mismatch (payload corrupte amb framing valid)** -> marge de bit degradat: "
              "jitter, slew-rate o reflexions.",
              "- **p99 >> p50** -> turnaround no determinista (auto-baud o buffers).",
              "- **post_collision FAIL** -> latch-up: un transceptor es queda en TX.", ""]
    with open(base + ".md", "w") as f:
        f.write("\n".join(lines))

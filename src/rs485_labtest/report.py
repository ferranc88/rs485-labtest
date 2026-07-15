"""Escriptura d'informes: JSON estructurat, Markdown llegible i CSV de latencies."""

from __future__ import annotations

import csv
import json
from typing import Any

from .interfaces import DEFAULT_INTERFACE, describe_interface, interface_hints


def write_reports(base: str, meta: dict[str, Any], results: list[dict[str, Any]],
                  lat_rows: list[tuple[str, int, float]]) -> None:
    """Genera ``base.json``, ``base.md`` i ``base_latencies.csv``.

    Sempre en UTF-8: els informes es generen en un PC i es llegeixen en un
    altre (el banc es Linux, l'escriptori pot ser Windows), i sense fixar-ho
    la codificacio per defecte de cada plataforma els faria il.legibles.
    """
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(dict(meta=meta, results=results), f, indent=2)

    with open(base + "_latencies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test", "baud", "rtt_ms"])
        w.writerows(lat_rows)

    lines = [f"# Informe estres RS-485 - {meta['label']}", ""]
    iface_info = describe_interface(meta.get("interface", DEFAULT_INTERFACE))
    lines += [f"- **Data (UTC):** {meta['timestamp_utc']}",
              f"- **Interficie:** {iface_info['title'] if iface_info else '?'}"
              + (f" — {iface_info['wiring']}" if iface_info else ""),
              f"- **Port / baud base:** {meta['port']} @ {meta['base_baud']} "
              f"({meta['parity']},{meta['stopbits']})",
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
    # la guia depen de la interficie: parlar de bias o de diferencial A-B no
    # te cap sentit en RS-232 (single-ended)
    iface = meta.get("interface", DEFAULT_INTERFACE)
    info = describe_interface(iface)
    lines += ["", "## Guia d'interpretacio", ""]
    if info:
        lines.append(f"Interficie sota prova: **{info['title']}** — {info['what']}")
        lines.append("")
    lines += [f"- {h}" for h in interface_hints(iface)]
    lines.append("")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

"""Assistent interactiu de llançament.

Fa preguntes (mode, ports, bauds, quins tests, etiquetes, criteris) i en
treu un ``argparse.Namespace`` equivalent al que hi hauria posat la CLI, de
manera que despres es despatxa pel mateix cami que ``battery`` / ``duo`` /
``slave``.

La logica de construccio (``build_namespace``) i el parseig
(``parse_baud_list`` / ``parse_test_selection``) son purs i testejables;
``run_wizard`` nomes hi posa la interaccio (rich.prompt).
"""

from __future__ import annotations

import argparse
from typing import Any

from .catalog import TEST_ORDER, describe

_MODES = ("duo", "battery", "slave")
_LIVE = ("auto", "rich", "plain")
_PROFILES = ("smoke", "standard", "soak")


def parse_baud_list(text: str) -> list[int]:
    """'9600, 307200 921600' -> [9600, 307200, 921600] (dedupe, ordre conservat)."""
    out: list[int] = []
    for tok in text.replace(",", " ").split():
        v = int(tok)
        if v <= 0:
            raise ValueError(f"baud invàlid: {tok}")
        if v not in out:
            out.append(v)
    return out


def parse_test_selection(text: str) -> list[str]:
    """Accepta noms o índexs 1-based (segons TEST_ORDER) separats per coma/espai.

    '1 3 idle_monitor' -> ['sanity', 'min_frames', 'idle_monitor'].
    Retorna els noms en l'ordre canònic, sense duplicats. Llença ValueError
    amb el token dolent si algun no és vàlid.
    """
    picked: set[str] = set()
    for tok in text.replace(",", " ").split():
        if tok.isdigit():
            i = int(tok)
            if not (1 <= i <= len(TEST_ORDER)):
                raise ValueError(f"índex fora de rang: {tok}")
            picked.add(TEST_ORDER[i - 1])
        elif tok in TEST_ORDER:
            picked.add(tok)
        else:
            raise ValueError(f"test desconegut: {tok}")
    return [n for n in TEST_ORDER if n in picked]


def build_namespace(answers: dict[str, Any]) -> tuple[str, argparse.Namespace]:
    """Construeix (mode, Namespace) a partir de les respostes de l'assistent."""
    mode = answers["mode"]
    ns = argparse.Namespace(
        mode=mode,
        port=answers["port"],
        baud=int(answers.get("baud", 115200)),
        parity=answers.get("parity", "N"),
        stopbits=float(answers.get("stopbits", 1)),
        profile=answers.get("profile", "standard"),
        bauds=list(answers.get("bauds", []) or []),
        tests=answers.get("tests") or None,
        label=answers.get("label", ""),
        notes=answers.get("notes", ""),
        outdir=answers.get("outdir", "results"),
        seed=answers.get("seed"),
        max_fer=float(answers.get("max_fer", 0.0)),
        max_p99=float(answers.get("max_p99", 0.0)),
        live=answers.get("live", "auto"),
        turnaround_us=int(answers.get("turnaround_us", 0)),
        verbose=False,
        quiet=False,
    )
    if mode == "duo":
        ns.slave_port = answers["slave_port"]
    return mode, ns


# --------------------------------------------------------------- interactiu
def _discover_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError:  # pragma: no cover
        return []
    return [(p.device, (p.description or "").strip()) for p in list_ports.comports()]


def _ask_port(console: Any, prompt: str) -> str:
    from rich.prompt import Prompt

    ports = _discover_ports()
    if ports:
        console.print(f"[dim]{prompt} — ports detectats:[/]")
        for i, (dev, desc) in enumerate(ports, 1):
            console.print(f"  [cyan]{i}[/] {dev}  [dim]{desc}[/]")
        console.print("  [dim]…o escriu una ruta (recomanat /dev/serial/by-id/…)[/]")
        ans = Prompt.ask(f"[bold]{prompt}[/]")
        if ans.isdigit() and 1 <= int(ans) <= len(ports):
            return ports[int(ans) - 1][0]
        return ans
    return Prompt.ask(f"[bold]{prompt}[/] [dim](p.ex. /dev/serial/by-id/…)[/]")


def _ask_tests(console: Any) -> list[str] | None:
    from rich.prompt import Confirm, Prompt

    if Confirm.ask("Corro [bold]tots[/] els tests?", default=True):
        return None
    console.print("[dim]Tests disponibles:[/]")
    for i, name in enumerate(TEST_ORDER, 1):
        info = describe(name)
        icon = f"{info['icon']} " if info else ""
        title = info["title"] if info else ""
        console.print(f"  [cyan]{i:>2}[/] {icon}{name}  [dim]{title}[/]")
    while True:
        raw = Prompt.ask("Quins? [dim](números o noms, separats per espai)[/]")
        try:
            sel = parse_test_selection(raw)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            continue
        if sel:
            return sel
        console.print("[red]cap test seleccionat[/]")


def run_wizard() -> tuple[str, argparse.Namespace]:  # pragma: no cover - interactiu
    from rich.console import Console
    from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt

    console = Console()
    console.rule("[bold bright_cyan]⚡ rs485-labtest · assistent[/]")

    answers: dict[str, Any] = {}
    answers["mode"] = Prompt.ask(
        "Mode", choices=list(_MODES), default="duo")

    answers["port"] = _ask_port(console, "Port màster (A)")
    if answers["mode"] == "duo":
        answers["slave_port"] = _ask_port(console, "Port slave (B)")

    answers["baud"] = IntPrompt.ask("Baud base", default=115200)
    answers["parity"] = Prompt.ask("Paritat", choices=["N", "E", "O"], default="N")

    if answers["mode"] == "slave":
        answers["turnaround_us"] = IntPrompt.ask(
            "Retard artificial abans de l'eco (µs)", default=0)
        return build_namespace(answers)

    extra = Prompt.ask(
        "Bauds addicionals per al barrido [dim](buit = cap; p.ex. 307200 921600)[/]",
        default="")
    try:
        answers["bauds"] = parse_baud_list(extra)
    except ValueError:
        console.print("[red]bauds ignorats (format invàlid)[/]")
        answers["bauds"] = []

    answers["profile"] = Prompt.ask(
        "Perfil [dim](smoke ~2min · standard ~15min · soak ~2h)[/]",
        choices=list(_PROFILES), default="standard")
    answers["tests"] = _ask_tests(console)

    answers["label"] = Prompt.ask(
        "Etiqueta [dim](DUT/condició, p.ex. NDR6_Vcm+7V)[/]", default="")
    answers["notes"] = Prompt.ask("Notes de l'operador", default="")
    answers["max_fer"] = FloatPrompt.ask(
        "Llindar FER [dim](0 = cap error tolerat)[/]", default=0.0)
    answers["max_p99"] = FloatPrompt.ask(
        "Llindar p99 latència en ms [dim](0 = sense llindar)[/]", default=0.0)
    answers["live"] = Prompt.ask(
        "Vista en directe", choices=list(_LIVE), default="rich")

    mode, ns = build_namespace(answers)
    _print_summary(console, mode, ns)
    if not Confirm.ask("[bold]Llenço?[/]", default=True):
        raise SystemExit("cancel·lat per l'usuari")
    return mode, ns


def _print_summary(console: Any, mode: str, ns: argparse.Namespace) -> None:  # pragma: no cover
    from rich.panel import Panel

    lines = [f"[bold]mode[/] {mode}", f"[bold]port[/] {ns.port}"]
    if mode == "duo":
        lines.append(f"[bold]slave[/] {ns.slave_port}")
    lines.append(f"[bold]baud[/] {ns.baud}"
                 + (f"  +{ns.bauds}" if ns.bauds else ""))
    lines.append(f"[bold]perfil[/] {ns.profile}")
    lines.append("[bold]tests[/] " + ("tots" if ns.tests is None
                                        else ", ".join(ns.tests)))
    lines.append(f"[bold]label[/] {ns.label or '—'}   "
                 f"[bold]FER≤[/] {ns.max_fer}   [bold]live[/] {ns.live}")
    console.print(Panel("\n".join(lines), title="[bright_cyan]resum[/]",
                        border_style="bright_cyan", title_align="left"))

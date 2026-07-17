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
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .catalog import TEST_ORDER, describe
from .interfaces import DEFAULT_INTERFACE, INTERFACES, interface_for_wires

_MODES = ("duo", "battery", "slave")
_LIVE = ("auto", "rich", "plain")
_PROFILES = ("smoke", "standard", "soak")

# on es desen les configuracions de l'assistent (JSON: nom -> respostes)
PRESETS_PATH = Path.home() / ".config" / "rs485-labtest" / "presets.json"


def load_presets(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Carrega les configuracions desades; fitxer absent o corrupte = cap."""
    p = Path(path) if path is not None else PRESETS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_preset(name: str, answers: dict[str, Any],
                path: Path | str | None = None) -> Path:
    """Desa (o sobreescriu) una configuracio amb el nom donat."""
    p = Path(path) if path is not None else PRESETS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_presets(p)
    entry = {k: v for k, v in answers.items() if not k.startswith("_")}
    entry["_saved_at"] = datetime.now().isoformat(timespec="seconds")
    data[name] = entry
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def preset_answers(entry: dict[str, Any]) -> dict[str, Any]:
    """Neteja les claus internes (_saved_at...) abans de reconstruir la config."""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def preset_summary(name: str, entry: dict[str, Any]) -> str:
    """Una linia descriptiva d'un preset per al llistat del wizard."""
    parts = [entry.get("mode", "?"), str(entry.get("port", "?")),
             f"{entry.get('baud', 115200)}bps", str(entry.get("profile", "-"))]
    if entry.get("label"):
        parts.append(str(entry["label"]))
    when = entry.get("_saved_at", "")
    date = when.split("T")[0] if when else ""
    return f"{name}: " + " · ".join(parts) + (f"  ({date})" if date else "")


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


def resolve_interface(answers: dict[str, Any]) -> str:
    """Interficie de les respostes, migrant els presets antics amb ``wires``."""
    iface = answers.get("interface")
    if iface in INTERFACES:
        return str(iface)
    if answers.get("wires") is not None:          # preset desat abans de --interface
        return interface_for_wires(int(answers["wires"]))
    return DEFAULT_INTERFACE


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
        interface=resolve_interface(answers),
        wires=None,                    # ja resolt a interface; l'alias no aplica
        bauds=list(answers.get("bauds", []) or []),
        tests=answers.get("tests") or None,
        label=answers.get("label", ""),
        notes=answers.get("notes", ""),
        outdir=answers.get("outdir", "results"),
        seed=answers.get("seed"),
        max_fer=float(answers.get("max_fer", 0.0)),
        max_p99=float(answers.get("max_p99", 0.0)),
        baud_margin=float(answers.get("baud_margin", 1.0)),
        notify=answers.get("notify", "auto"),
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


def _explain(console: Any, *lines: str) -> None:  # pragma: no cover - nomes UI
    """Comentari breu abans d'una pregunta: que es i que conve respondre."""
    console.print()
    for line in lines:
        console.print(f"[dim]💬 {line}[/]")


def _ask_interface(console: Any) -> str:  # pragma: no cover - interactiu
    """Primera pregunta de totes: que anem a testejar."""
    from rich.prompt import Prompt

    console.print()
    console.print("[bold bright_white]Què anem a testejar?[/]")
    keys = list(INTERFACES)
    for i, key in enumerate(keys, 1):
        info = INTERFACES[key]
        console.print(f"  [cyan]{i}[/] {info['icon']} [bold]{key}[/] — "
                      f"{info['title']}")
        console.print(f"      [dim]{info['what']}[/]")
        console.print(f"      [dim]cablejat: {info['wiring']}[/]")
    _explain(console,
             "Determina quins tests apliquen (en half-duplex hi ha colisions; "
             "en full-duplex, carrega simultania) i com s'interpreten els "
             "errors a l'informe.")
    while True:
        raw = Prompt.ask("Interfície (número o nom)", default=DEFAULT_INTERFACE)
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        if raw in INTERFACES:
            return raw
        console.print("[red]no existeix[/]")


def _ask_notify(console: Any, answers: dict[str, Any]) -> None:  # pragma: no cover
    import os

    from rich.prompt import Confirm

    from .notify import ENV_CHAT, ENV_TOKEN

    have = bool(os.environ.get(ENV_TOKEN) and os.environ.get(ENV_CHAT))
    _explain(console,
             "Avisa per Telegram a cada FAIL i envia un resum en acabar; ideal "
             "per a corrides llargues (soak).",
             (f"Configuracio detectada ({ENV_TOKEN} i {ENV_CHAT} definits)."
              if have else
              f"Cal exportar {ENV_TOKEN} i {ENV_CHAT}; prova-ho amb "
              f"'rs485-labtest notify-test'. Sense aixo, no s'enviara res."))
    if have:
        answers["notify"] = "auto" if Confirm.ask(
            "Vols notificacions Telegram?", default=True) else "off"
    else:
        answers["notify"] = "auto"        # si mes tard hi son, funcionara sol


def _offer_presets(console: Any) -> dict[str, Any] | None:  # pragma: no cover
    """Si hi ha configuracions desades, ofereix-les. Retorna les respostes
    del preset triat, o None si l'operador vol una configuracio nova."""
    from rich.prompt import Prompt

    presets = load_presets()
    if not presets:
        return None
    names = list(presets)
    _explain(console,
             "Tens configuracions desades d'altres corrides. Tria'n una per "
             "llançar-la tal qual, o Enter per configurar-ne una de nova.")
    for i, name in enumerate(names, 1):
        console.print(f"  [cyan]{i}[/] {preset_summary(name, presets[name])}")
    raw = Prompt.ask("Configuració desada (número o nom; buit = nova)", default="")
    if not raw.strip():
        return None
    key = None
    if raw.strip().isdigit() and 1 <= int(raw) <= len(names):
        key = names[int(raw) - 1]
    elif raw.strip() in presets:
        key = raw.strip()
    if key is None:
        console.print("[red]no existeix; configuració nova[/]")
        return None
    return preset_answers(presets[key])


def _maybe_save(console: Any, answers: dict[str, Any]) -> None:  # pragma: no cover
    from rich.prompt import Confirm, Prompt

    _explain(console,
             "Si la deses, el proper cop el wizard te l'oferirà d'entrada "
             "(es guarda a ~/.config/rs485-labtest/presets.json).")
    if not Confirm.ask("Vols desar aquesta configuració?", default=True):
        return
    default_name = str(answers.get("label") or answers.get("mode") or "config")
    name = Prompt.ask("Nom del preset", default=default_name)
    path = save_preset(name, answers)
    console.print(f"[green]✓ desada com «{name}»[/] [dim]({path})[/]")


def run_wizard() -> tuple[str, argparse.Namespace]:  # pragma: no cover - interactiu
    from rich.console import Console
    from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt

    console = Console()
    console.rule("[bold bright_cyan]⚡ rs485-labtest · assistent[/]")

    saved = _offer_presets(console)
    if saved is not None:
        mode, ns = build_namespace(saved)
        _print_summary(console, mode, ns)
        if Confirm.ask("[bold]Llenço amb aquesta configuració?[/]", default=True):
            return mode, ns
        console.print("[dim]d'acord, configurem-ne una de nova…[/]")

    answers: dict[str, Any] = {}

    answers["interface"] = _ask_interface(console)

    _explain(console,
             "duo = tot des d'aquest PC (arrenca el slave sol i corre la bateria).",
             "battery = nomes el master (el slave ja corre en un altre PC).",
             "slave = nomes l'extrem que fa eco (per a l'altre PC).")
    answers["mode"] = Prompt.ask(
        "Mode", choices=list(_MODES), default="duo")

    _explain(console,
             "El port de l'adaptador USB-RS485 que orquestra el test.",
             "Millor una ruta /dev/serial/by-id/... : els ttyUSBn ballen entre "
             "replugs i pots acabar testejant el link al reves.")
    answers["port"] = _ask_port(console, "Port màster (A)")
    if answers["mode"] == "duo":
        _explain(console,
                 "El port de l'altre extrem del link (el que fara eco).",
                 "Ha de ser un adaptador diferent del master, connectat a "
                 "l'altra banda del DUT.")
        answers["slave_port"] = _ask_port(console, "Port slave (B)")

    _explain(console,
             "Velocitat de treball del test. S'accepta qualsevol valor, tambe "
             "no estandard (p.ex. 307200).",
             "Els dos extrems s'hi posaran; el barrido de bauds extra es "
             "pregunta despres.")
    answers["baud"] = IntPrompt.ask("Baud base", default=115200)

    _explain(console,
             "N (cap) es l'habitual en RS-485. Toca-ho nomes si el teu equip "
             "usa paritat parell (E) o senar (O).")
    answers["parity"] = Prompt.ask("Paritat", choices=["N", "E", "O"], default="N")

    if answers["mode"] == "slave":
        _explain(console,
                 "Retard afegit abans de cada eco, per simular un esclau lent.",
                 "0 = respondre tan rapid com es pugui (el normal).")
        answers["turnaround_us"] = IntPrompt.ask(
            "Retard artificial abans de l'eco (µs)", default=0)
        _maybe_save(console, answers)
        return build_namespace(answers)

    _explain(console,
             "A cada baud extra es repeteix un subconjunt representatiu de "
             "tests (canvi remot automatic al slave, no cal tocar res).",
             "Buit = nomes el baud base. Exemple: 9600 307200 921600")
    extra = Prompt.ask(
        "Bauds addicionals per al barrido", default="")
    try:
        answers["bauds"] = parse_baud_list(extra)
    except ValueError:
        console.print("[red]bauds ignorats (format invàlid)[/]")
        answers["bauds"] = []

    _explain(console,
             "smoke ~2 min: validar el muntatge. standard ~15 min: la corrida "
             "de qualificacio habitual. soak ~2 h: volum estadistic per a la "
             "BER i deriva termica.")
    answers["profile"] = Prompt.ask(
        "Perfil", choices=list(_PROFILES), default="standard")

    _explain(console,
             "Tots = la bateria completa (recomanat per qualificar).",
             "Un subconjunt es util per iterar rapid sobre un problema concret.")
    answers["tests"] = _ask_tests(console)

    _explain(console,
             "Identifica el DUT i la condicio de la corrida; surt al nom dels "
             "informes. Exemple: NDR6_protoB_Vcm+7V")
    answers["label"] = Prompt.ask("Etiqueta", default="")

    _explain(console,
             "Text lliure per a l'informe: font d'alimentacio, Vcm real "
             "mesurada, temperatura, terminacions...")
    answers["notes"] = Prompt.ask("Notes de l'operador", default="")

    _explain(console,
             "Fraccio de trames amb error tolerada (0.01 = 1%).",
             "0 = cap error tolerat: es el criteri de qualificacio per "
             "defecte, no el relaxis sense motiu.")
    answers["max_fer"] = FloatPrompt.ask("Llindar FER", default=0.0)

    _explain(console,
             "Si el 99% de les respostes han d'arribar dins d'un temps maxim "
             "(aplicacions amb timeout), posa'l aqui en ms.",
             "0 = no aplicar cap llindar de latencia.")
    answers["max_p99"] = FloatPrompt.ask("Llindar p99 latència en ms", default=0.0)

    _explain(console,
             "rich = quadre viu amb grafics al terminal. plain = linia a "
             "linia classica (millor per a logs). auto = decideix sol.")
    answers["live"] = Prompt.ask(
        "Vista en directe", choices=list(_LIVE), default="rich")

    _ask_notify(console, answers)

    mode, ns = build_namespace(answers)
    _print_summary(console, mode, ns)
    _maybe_save(console, answers)
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
    info = INTERFACES.get(ns.interface)
    lines.insert(0, f"[bold]interfície[/] {info['icon'] if info else ''} "
                    f"{info['title'] if info else ns.interface}")
    lines.append(f"[bold]perfil[/] {ns.profile}")
    lines.append("[bold]tests[/] " + ("tots" if ns.tests is None
                                        else ", ".join(ns.tests)))
    lines.append(f"[bold]label[/] {ns.label or '—'}   "
                 f"[bold]FER≤[/] {ns.max_fer}   [bold]live[/] {ns.live}")
    console.print(Panel("\n".join(lines), title="[bright_cyan]resum[/]",
                        border_style="bright_cyan", title_align="left"))

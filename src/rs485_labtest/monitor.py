"""Monitors de la bateria: on va el feedback mentre corre.

La bateria no imprimeix directament; notifica un ``Monitor``. Aixo separa
*que* passa de *com* es mostra:

- :class:`NullMonitor`  — silenci total (mode ``--quiet``; nomes fitxers).
- :class:`PlainMonitor` — sortida linia a linia identica a la de sempre
  (pipes, CI, logs). Es el fallback quan no hi ha TTY o falta ``rich``.
- :class:`RichMonitor`  — TUI en directe (``rich``): test en curs, comptadors,
  FER, p50/p99 i sparkline de latencies, actualitzat in-place.

Nomes el :class:`RichMonitor` consumeix progres en directe
(``wants_progress = True``); els altres el reben com a no-op, de manera que el
cami rapid del motor no paga res.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Protocol

from .catalog import describe

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ------------------------------------------------------------------ interficie
class Monitor(Protocol):
    wants_progress: bool

    def battery_start(self, meta: dict[str, Any], n_tests: int, base: str) -> None: ...
    def baud_change(self, baud: int, ok: bool) -> None: ...
    def test_start(self, idx: int, n_tests: int, name: str, kind: str) -> None: ...
    def test_progress(self, res: dict[str, Any]) -> None: ...
    def test_end(self, res: dict[str, Any]) -> None: ...
    def note(self, msg: str) -> None: ...
    def battery_end(self, results: list[dict[str, Any]], n_fail: int,
                    elapsed_s: float, base: str) -> None: ...


# ------------------------------------------------------------------- utilitats
_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 48) -> str:
    """Mini-grafic de barres unicode a partir d'una serie de valors."""
    if not values:
        return ""
    vals = values[-width:]
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return _BLOCKS[0] * len(vals)
    span = hi - lo
    return "".join(_BLOCKS[int((v - lo) / span * (len(_BLOCKS) - 1))] for v in vals)


def _pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(int(len(s) * p), len(s) - 1)]


def _fer(res: dict[str, Any]) -> float:
    tx = res.get("tx", 0)
    if not tx:
        return 0.0
    errs = res.get("crc_err", 0) + res.get("mismatch", 0) \
        + res.get("seq_err", 0) + res.get("timeout", 0)
    return errs / tx


# ------------------------------------------------------------------ NullMonitor
class NullMonitor:
    """No mostra res (mode --quiet). Els informes es generen igualment."""

    wants_progress = False

    def battery_start(self, meta: dict[str, Any], n_tests: int, base: str) -> None: ...
    def baud_change(self, baud: int, ok: bool) -> None: ...
    def test_start(self, idx: int, n_tests: int, name: str, kind: str) -> None: ...
    def test_progress(self, res: dict[str, Any]) -> None: ...
    def test_end(self, res: dict[str, Any]) -> None: ...
    def note(self, msg: str) -> None: ...
    def battery_end(self, results: list[dict[str, Any]], n_fail: int,
                    elapsed_s: float, base: str) -> None: ...


# ------------------------------------------------------------------ PlainMonitor
class PlainMonitor:
    """Sortida linia a linia: exactament la de l'script de sempre."""

    wants_progress = False

    def __init__(self, version: str) -> None:
        self.version = version

    def _p(self, msg: str, end: str = "\n") -> None:
        print(msg, end=end, flush=True)

    def battery_start(self, meta: dict[str, Any], n_tests: int, base: str) -> None:
        self._p(f"\n=== BATERIA RS-485 v{self.version} === label={meta['label']} "
                f"profile={meta['profile']} seed={meta['seed']}\n"
                f"    {n_tests} tests | resultats a {base}.* \n")

    def baud_change(self, baud: int, ok: bool) -> None:
        self._p(f"--- canvi de baud remot -> {baud} ...", end=" ")
        self._p("OK" if ok else
                "FALLIT (el slave no respon al nou baud); s'ometen els seus tests")

    def test_start(self, idx: int, n_tests: int, name: str, kind: str) -> None:
        d = describe(name)
        title = f" · {d['icon']} {d['title']}" if d else ""
        self._p(f"\n[{idx:>2}/{n_tests}] {name}{title}")
        if d:
            self._p(f"        què:     {d['what']}")
            self._p(f"        per què: {d['why']}")

    def test_progress(self, res: dict[str, Any]) -> None: ...

    def test_end(self, res: dict[str, Any]) -> None:
        reasons = res.get("reasons") or []
        extra = f" | {', '.join(reasons)}" if reasons else ""
        lat = res.get("lat") or {}
        lati = f" p50={lat.get('p50')}ms p99={lat.get('p99')}ms" if lat else ""
        self._p(f"        → {res['verdict']:<4} tx={res.get('tx', 0)} "
                f"ok={res.get('ok', 0)}{lati}{extra}")

    def note(self, msg: str) -> None:
        self._p(msg)

    def battery_end(self, results: list[dict[str, Any]], n_fail: int,
                    elapsed_s: float, base: str) -> None:
        self._p(f"\n=== RESULTAT GLOBAL: {'FAIL' if n_fail else 'PASS'} "
                f"({n_fail} FAIL / {len(results)} tests, {elapsed_s}s) ===")
        self._p(f"Informes: {base}.json  {base}.md  {base}_latencies.csv")


# ------------------------------------------------------------------ RichMonitor
_VERDICT_STYLE = {"PASS": "bold green", "FAIL": "bold red", "INFO": "yellow"}
_VERDICT_ICON = {"PASS": "✓", "FAIL": "✗", "INFO": "•"}


class RichMonitor:
    """TUI en directe amb ``rich``: refresca in-place mentre corre la bateria."""

    wants_progress = True

    def __init__(self, version: str) -> None:
        from rich.console import Console
        from rich.live import Live

        self.version = version
        self._Live = Live
        self.console = Console()
        self.live: Any = None

        self.meta: dict[str, Any] = {}
        self.n_tests = 0
        self.base = ""
        self.t_start = 0.0

        self.rows: list[dict[str, Any]] = []     # tests completats
        self.n_pass = 0
        self.n_fail = 0
        self.n_info = 0

        self.cur: dict[str, Any] | None = None    # {idx, name, kind, t0}
        self.cur_res: dict[str, Any] = {}
        self.notes: list[str] = []

    # ---- cicle de vida ----
    def battery_start(self, meta: dict[str, Any], n_tests: int, base: str) -> None:
        self.meta, self.n_tests, self.base = meta, n_tests, base
        self.t_start = time.monotonic()
        self.live = self._Live(self._render(), console=self.console,
                               refresh_per_second=12, screen=False)
        self.live.start()

    def baud_change(self, baud: int, ok: bool) -> None:
        self.notes.append(f"[cyan]baud -> {baud}[/]: "
                          + ("[green]OK[/]" if ok else "[red]FALLIT, s'ometen els seus tests[/]"))
        self._update()

    def test_start(self, idx: int, n_tests: int, name: str, kind: str) -> None:
        self.cur = dict(idx=idx, name=name, kind=kind, t0=time.monotonic())
        self.cur_res = {}
        self._update()

    def test_progress(self, res: dict[str, Any]) -> None:
        self.cur_res = res
        self._update()

    def test_end(self, res: dict[str, Any]) -> None:
        v = res.get("verdict", "?")
        self.n_pass += v == "PASS"
        self.n_fail += v == "FAIL"
        self.n_info += v == "INFO"
        self.rows.append(res)
        self.cur = None
        self.cur_res = {}
        self._update()

    def note(self, msg: str) -> None:
        self.notes.append(msg.strip())
        self._update()

    def battery_end(self, results: list[dict[str, Any]], n_fail: int,
                    elapsed_s: float, base: str) -> None:
        self._update()
        if self.live is not None:
            self.live.stop()
        glob = "[bold red]FAIL[/]" if n_fail else "[bold green]PASS[/]"
        self.console.print(f"\n=== RESULTAT GLOBAL: {glob} "
                           f"({n_fail} FAIL / {len(results)} tests, {elapsed_s}s) ===")
        self.console.print(f"Informes: {base}.json  {base}.md  {base}_latencies.csv")

    # ---- render ----
    def _update(self) -> None:
        if self.live is None:
            return
        try:
            self.live.update(self._render(), refresh=True)
        except Exception:
            pass    # un frame perdut no ha de tombar la corrida

    def _render(self) -> Any:
        from rich import box
        from rich.console import Group
        from rich.panel import Panel

        elapsed = time.monotonic() - self.t_start if self.t_start else 0.0
        done = len(self.rows)
        frac = done / self.n_tests if self.n_tests else 0.0
        cur_n = min(done + (self.cur is not None), self.n_tests)
        head = (
            f"[bold bright_white]⚡ RS-485 labtest[/] [dim]v{self.version}[/]   "
            f"[bright_white]{self.meta.get('label', '?')}[/]\n"
            f"[dim]profile[/] {self.meta.get('profile', '?')}   "
            f"[dim]seed[/] {self.meta.get('seed', '?')}   "
            f"[dim]bauds[/] {self._bauds_str()}\n"
            f"{self._bar(frac, 30)} [bold]{100 * frac:3.0f}%[/]  "
            f"[dim]test[/] {cur_n}/{self.n_tests}   "
            f"[green]✓ {self.n_pass}[/]  [red]✗ {self.n_fail}[/]  "
            f"[yellow]• {self.n_info}[/]   [dim]⏱[/] {elapsed:5.1f}s")
        header = Panel(head, box=box.HEAVY, border_style="bright_blue",
                       padding=(0, 1))

        group: list[Any] = [header, self._current_panel(), self._results_table()]
        if self.notes:
            group.append(Panel("\n".join(self.notes[-3:]), title="[dim]notes[/]",
                               box=box.ROUNDED, border_style="grey37",
                               padding=(0, 1), title_align="left"))
        group.append(self._legend())
        return Group(*group)

    def _current_panel(self) -> Any:
        from rich import box
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table

        if self.cur is None:
            return Panel("[grey50]preparant la seguent prova…[/]",
                         title="[dim]test en curs[/]", box=box.ROUNDED,
                         border_style="grey37", padding=(0, 1), title_align="left")

        res = self.cur_res
        name, kind = self.cur["name"], self.cur["kind"]
        info = describe(name)
        dur = res.get("duration_s")
        el = time.monotonic() - self.cur["t0"]
        frac = min(el / dur, 1.0) if dur else 0.0
        spin = _SPINNER[int(time.monotonic() * 12) % len(_SPINNER)]
        prog = (f"[bright_cyan]{spin}[/] {self._bar(frac, 22)} "
                f"{el:4.1f}s" + (f"[dim]/{dur:g}s[/]" if dur else ""))

        blocks: list[Any] = []
        if info:
            blocks.append(f"[italic]{info['what']}[/]")
            blocks.append(f"[dim]↳ per què:[/] [grey70]{info['why']}[/]")

        t = Table.grid(padding=(0, 2))
        t.add_column(justify="right", style="dim")
        t.add_column(justify="left")

        if res.get("idle_test"):
            raw = res.get("raw_bytes", 0)
            style = "bold red" if raw else "bold green"
            mark = "✗" if raw else "✓"
            t.add_row("bus en repòs", f"[{style}]{mark} {raw} B rebuts[/] "
                                      f"[dim](ha de ser 0)[/]")
            t.add_row("progrés", prog)
            spark = ""
        else:
            tx, ok = res.get("tx", 0), res.get("ok", 0)
            fer = _fer(res)
            fer_style = "green" if fer == 0 else "bold red"
            lat = res.get("latencies_ms") or []
            p50 = f"{_pct(lat, .5):.2f}" if lat else "-"
            p99 = f"{_pct(lat, .99):.2f}" if lat else "-"
            t.add_row("tx / ok", f"{tx} / [green]{ok}[/]")
            t.add_row("errors",
                      f"crc [red]{res.get('crc_err', 0)}[/]  "
                      f"mism [red]{res.get('mismatch', 0)}[/]  "
                      f"seq [red]{res.get('seq_err', 0)}[/]  "
                      f"to [red]{res.get('timeout', 0)}[/]  "
                      f"junk [red]{res.get('junk_bytes', 0)}[/]B")
            t.add_row("FER", f"[{fer_style}]{100 * fer:.4f} %[/]")
            t.add_row("latència", f"p50 [cyan]{p50}[/] ms   p99 [cyan]{p99}[/] ms")
            t.add_row("progrés", prog)
            spark = sparkline(lat)

        blocks.append(t)
        if spark:
            blocks.append(f"[dim]latències[/] [cyan]{spark}[/]")

        icon = f"{info['icon']} " if info else ""
        human = f" — [bright_white]{info['title']}[/]" if info else ""
        title = f"[bold cyan]▶ {icon}{name}[/]{human}  [dim]({kind})[/]"
        return Panel(Group(*blocks), title=title, box=box.ROUNDED,
                     border_style="cyan", padding=(0, 1), title_align="left")

    def _results_table(self) -> Any:
        from rich import box
        from rich.table import Table

        t = Table(expand=True, box=box.SIMPLE_HEAD, border_style="grey37",
                  pad_edge=False, header_style="bold dim")
        t.add_column("#", justify="right", width=3, style="grey50")
        t.add_column("test", ratio=3)
        t.add_column("baud", justify="right")
        t.add_column("tx", justify="right")
        t.add_column("ok", justify="right")
        t.add_column("junk", justify="right")
        t.add_column("p50/p99 ms", justify="right")
        t.add_column("veredicte", justify="center")

        visible = self.rows[-12:]
        first = len(self.rows) - len(visible) + 1
        if first > 1:
            t.add_row("…", f"[grey50]{first - 1} tests anteriors[/]",
                      "", "", "", "", "", "")
        for i, r in enumerate(visible, first):
            lat = r.get("lat") or {}
            latstr = f"{lat.get('p50', '-')}/{lat.get('p99', '-')}" if lat else "[dim]-[/]"
            v = r.get("verdict", "?")
            junk = r.get("junk_bytes", r.get("raw_bytes", 0))
            junk_txt = f"[red]{junk}[/]" if junk else "0"
            info = describe(r.get("name", ""))
            label = (f"{info['icon']} " if info else "") + r.get("name", "?")
            t.add_row(str(i), label, str(r.get("baud", "-")),
                      str(r.get("tx", 0)), str(r.get("ok", 0)), junk_txt, latstr,
                      f"[{_VERDICT_STYLE.get(v, 'white')}]{_VERDICT_ICON.get(v, '')} {v}[/]")
        return t

    def _legend(self) -> Any:
        return (
            "[dim]  llegenda:[/] [green]✓ PASS[/]  [red]✗ FAIL[/]  "
            "[yellow]• INFO[/]   "
            "[dim]FER=frame error rate · junk=bytes fora de trama · "
            "Ctrl-C atura i desa informe parcial[/]")

    def _bauds_str(self) -> str:
        base = self.meta.get("base_baud", "?")
        extra = self.meta.get("bauds") or []
        return str(base) + ("  +[" + " ".join(map(str, extra)) + "]" if extra else "")

    @staticmethod
    def _bar(frac: float, width: int) -> str:
        frac = max(0.0, min(1.0, frac))
        full = int(round(frac * width))
        color = "green" if frac >= 0.999 else "bright_cyan"
        return (f"[{color}]" + "█" * full + "[/][grey30]"
                + "░" * (width - full) + "[/]")


# ------------------------------------------------------------------- seleccio
def rich_available() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


def make_monitor(mode: str, quiet: bool, version: str,
                 stream: Any = None) -> Monitor:
    """Tria el monitor segons ``--live`` (auto|rich|plain), TTY i disponibilitat.

    ``auto`` fa servir la TUI si hi ha terminal interactiu i ``rich`` instal.lat;
    si no, cau a la sortida linia a linia. ``--quiet`` mana per sobre de tot.
    """
    if quiet:
        return NullMonitor()
    stream = stream if stream is not None else sys.stdout
    is_tty = bool(getattr(stream, "isatty", lambda: False)())

    if mode == "plain":
        return PlainMonitor(version)
    if mode == "rich":
        if rich_available():
            return RichMonitor(version)
        print("[avis] 'rich' no esta instal.lat; caic a sortida plana "
              "(pip install rich)", file=sys.stderr)
        return PlainMonitor(version)
    # auto
    if is_tty and rich_available():
        return RichMonitor(version)
    return PlainMonitor(version)

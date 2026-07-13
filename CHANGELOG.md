# Changelog

Format basat en [Keep a Changelog](https://keepachangelog.com/ca/1.1.0/);
versions segons [SemVer](https://semver.org/lang/ca/).

La numeracio arrenca a 0.3.0: les "versions" 1.x/2.x eren l'script monolitic
`rs485_labtest.py` previ al paquet (conservat a `legacy/`).

## [Unreleased]

### Added
- **Suport explícit a baud rates alts i no estàndard** (p.ex. 307200): ja
  s'acceptaven, però ara si l'adaptador no pot amb un baud es llença
  `BaudNotSupported` amb el valor i pistes, en lloc d'un traceback; dins d'un
  barrido, aquell baud es marca FAIL i la resta continua. Documentats els
  sostres per xip i la tolerància de desajust a `docs/SETUP.md`.
- **Feedback en directe (TUI)** amb `rich`: vista que s'actualitza in-place
  amb barra de progres global, panell del test en curs (tx/ok, FER, p50/p99,
  progres i sparkline de latencies) i taula de tests completats amb veredicte
  de color. Nou flag `--live {auto,rich,plain}` a `battery` i `duo`.
- Capa de `Monitor` (`NullMonitor` / `PlainMonitor` / `RichMonitor`) que
  desacobla la logica de la bateria de la seva presentacio; la sortida
  `plain` es identica a la de sempre (pipes, CI, logs).
- Callback de progres opcional al `TestEngine`, invocat *despres* de cada RTT
  (no en contamina la latencia) i escanyat en el temps.

## [0.3.0] - 2026-07-13

### Added
- Empaquetat com a paquet Python instal.lable (`pip install -e .`) amb entry
  point de consola `rs485-labtest`.
- Abstraccio de transport (`rs485_labtest.transport.Transport`) perque el
  motor no depengui de `serial.Serial`: permet tests sense hardware i DUTs
  simulats injectables.
- Suite de tests: unitat (protocol, veredictes, informes) + DUTs simulats
  (`PerfectDUT`, `NoisyIdleDUT`, `SlowTurnaroundDUT`, `BitFlipDUT`,
  `LatchUpDUT`) + bateria completa d'integracio sobre ptys (Linux).
- CI a GitHub Actions: ruff + mypy + pytest sobre Python 3.9 / 3.11 / 3.13.
- Flags globals `--verbose` / `--quiet` i `--version`.
- Documentacio: `docs/SETUP.md`, `docs/TESTPLAN.md`, `docs/NDR6_MATRIX.md`.

### Changed
- Refactor del script monolitic v2.0 en moduls (`protocol`, `patterns`,
  `transport`, `engine`, `battery`, `slave`, `report`, `cli`). **Cap canvi**
  de format de trama, criteris PASS/FAIL per defecte ni format d'informes:
  els informes antics segueixen sent comparables amb els nous.
- El mode `duo` arrenca el slave amb `python -m rs485_labtest` en lloc de
  referenciar el fitxer de l'script.

### Notes
- L'script original es conserva a `legacy/rs485_labtest_v2.py` fins que la
  paritat quedi demostrada amb els tests d'integracio en CI; despres
  s'eliminara.

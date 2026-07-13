# Changelog

Format basat en [Keep a Changelog](https://keepachangelog.com/ca/1.1.0/);
versions segons [SemVer](https://semver.org/lang/ca/).

La numeracio arrenca a 0.3.0: les "versions" 1.x/2.x eren l'script monolitic
`rs485_labtest.py` previ al paquet (conservat a `legacy/`).

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

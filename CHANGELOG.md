# Changelog

Format basat en [Keep a Changelog](https://keepachangelog.com/ca/1.1.0/);
versions segons [SemVer](https://semver.org/lang/ca/).

La numeracio arrenca a 0.3.0: les "versions" 1.x/2.x eren l'script monolitic
`rs485_labtest.py` previ al paquet (conservat a `legacy/`).

## [Unreleased]

### Added
- **Perfil `endurance` (~24 h) i `--stress-first`** per a burn-in intensiu.
  L'`endurance` dedica el gruix del temps als tests de càrrega sostinguda
  (BER i `failsafe_paused` ~7,5 h cadascun). `--stress-first` reordena la
  bateria perquè comenci pels tests de càrrega (full-duplex, saturació, BER)
  just després del `sanity` (que sempre va primer per validar el banc).
  L'assistent l'ofereix i el proposa per defecte en endurance o full-duplex.
- **Notificacions per Telegram** (`--notify {auto,telegram,off}`, per defecte
  auto): alerta a cada FAIL i resum en acabar (o si s'interromp), enviat al
  mòbil. Pensat per a soak sense vigilància. Només stdlib (`urllib`), i
  resilient: si no hi ha xarxa, no envia i **mai atura ni bloqueja la
  bateria**. Config per `RS485_TELEGRAM_TOKEN` / `RS485_TELEGRAM_CHAT_ID` (el
  token no va mai per flag). Nou subcomandament `notify-test` que valida la
  config i, si falta el chat_id, el descobreix via getUpdates. Capa
  `MultiMonitor` que reparteix a la UI i a Telegram alhora; l'assistent ho
  pregunta.
- **Selecció d'interfície** (`--interface {rs485-half,rs485-full,rs422,rs232}`,
  per defecte `rs485-half`; és també la **primera pregunta de l'assistent**).
  Determina el pla de tests (via el duplex) i, sobretot, la **guia
  d'interpretació de l'informe**: en RS-232 (single-ended) no es parla de bias
  de failsafe ni de diferencial A-B perquè no existeixen, i en RS-422 s'avisa
  que l'emissor va sempre habilitat. La interfície consta a l'informe per a
  traçabilitat. `--wires` es manté com a àlies (2 → rs485-half, 4 →
  rs485-full) i els presets desats amb `wires` es migren sols.
- **Mode full-duplex**. Amb una interfície full-duplex (485 de 4 fils, RS-422
  o RS-232) cada sentit té el seu camí, així que la bateria s'hi adapta:
  - treu `collision_blind` i `post_collision` (no hi ha bus compartit on
    col·lisionar en punt a punt);
  - afegeix `fullduplex_load` (64 B) i `fullduplex_sat250` (250 B), que
    carreguen **les dues direccions alhora** mitjançant una finestra de
    trames en vol (el master no espera cada eco) — impossible en 2 fils, on
    seria una col·lisió. Detecta convertidors que ofeguen un sentit quan
    l'altre va carregat (fibra multiplexada, buffers compartits);
  - manté el failsafe (`idle_monitor`, `failsafe_paused`), que aplica a cada
    parell.
  Sense canvis al protocol ni al slave: només canvia que el master no
  serialitza els intercanvis. El cablejat consta a l'informe i la CLI rebutja
  demanar tests d'un cablejat que no toca.

### Fixed
- **Informes sempre en UTF-8**: `write_reports` no fixava la codificació, així
  que els fitxers sortien en la codificació per defecte de cada plataforma
  (cp1252 a Windows, UTF-8 a Linux) i no eren portables entre el PC del banc i
  l'escriptori.
- **Fals timeout amb trames grans a baud baix**: el timeout per intercanvi
  era fix (0,5 s) i una trama de 250 B a 9600 bps triga ~0,54 s d'anada i
  tornada, cosa que donava FER 100% fals a `failsafe_paused@9600`. Ara el
  timeout **escala amb el baud i la mida de trama** (`min_exchange_timeout`),
  de manera que mai és més curt que el temps físic de la trama. No afecta els
  casos ràpids (a 307200 es manté el 0,5 s).

### Added
- **Test nou `baud_offset` (marge de tolerància de baud)**: el master es
  desplaça ±1/2/3% respecte del slave i es mesura el FER a cada desajust.
  ±1% ha de passar (`--baud-margin`, per defecte 1.0); ±2/3% són
  caracterització (INFO) del marge restant. Motivat per la regla del sector
  de ~2% de desajust acumulat tolerable en UART async: cada re-clock (com la
  conversió a fibra del NDR6) consumeix part d'aquest pressupost i cap dels
  12 tests existents ho podia detectar. La bateria passa de 12 a 13 tests
  (18 corrides al baud base).
- **Assistent interactiu** (`rs485-labtest wizard`): pregunta mode, ports
  (amb detecció automàtica via `serial.tools.list_ports`), bauds, quins
  tests, etiqueta i criteris, ensenya un resum i llança. Lògica de
  construcció i parseig separades i testejades.
- **Descripció de cada test en directe** (què fa i per què), tant a la TUI
  com en mode pla, a partir d'un catàleg únic (`catalog.py`).
- **Selecció de tests** amb `--tests` a `battery`/`duo` (per defecte, tots);
  validació de noms amb missatge clar.
- **TUI més polida**: capçalera amb barra de progrés i %, panell del test en
  curs amb descripció, spinner, icones per test i veredicte, i llegenda.
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

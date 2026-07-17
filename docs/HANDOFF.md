---
title: rs485-labtest — Handoff
aliases: [rs485-labtest, banc RS-485, NDR6 test]
tags: [projecte/rs485-labtest, adilec, ndr6, hardware-testing, serial]
created: 2026-07-17
status: actiu
repo: https://github.com/ferranc88/rs485-labtest
---

# rs485-labtest — Handoff

> [!info] Què és
> Bateria d'estres **laboratory-grade** per a links sèrie, en un paquet Python
> instal·lable amb CLI. Neix per validar el convertidor **NDR6** d'Adilec
> (RS-485 ↔ fibra òptica) arran d'una incidència de camp d'integritat de
> senyal (tensió de mode comú i bias de failsafe), i serveix també per a
> control de qualitat d'entrada. Diu **què** falla i sota quines condicions;
> el **per què** es diagnostica amb sonda diferencial a l'oscil·loscopi.

## On és

| | |
|---|---|
| **GitHub** | `ferranc88/rs485-labtest` (privat) — https://github.com/ferranc88/rs485-labtest |
| **Local (Windows, dev)** | `C:\Users\ferra\OneDrive\Escriptori\CLAUDE CODE\rs485-labtest` |
| **Lab (execució real)** | PC Linux (usuari `root`, **bash**), repo a `~/rs485-labtest` |
| **CI** | GitHub Actions: ruff + mypy + pytest a Python 3.9/3.11/3.13 (verda) |
| **Tests** | ~169, inclosa la bateria completa sobre ptys virtuals |

> [!note] Desenvolupament vs execució
> El desenvolupament, tests i WSL són a la màquina Windows. L'**execució contra
> hardware real** es fa al **PC del lab**, que no és aquesta màquina. WSL serveix
> per validar sense hardware (ptys); no toca res del lab.

## Què fa

- **Interfícies** (`--interface`, o 1a pregunta de l'assistent): `rs485-half`,
  `rs485-full`, `rs422`, `rs232`. El *duplex* determina el pla; la interfície
  determina la **guia d'interpretació** de l'informe (en RS-232, single-ended,
  no es parla de bias ni de diferencial A-B).
- **13 tests de nucli** + variants segons duplex:
  `sanity`, `turnaround_gap0`, `min_frames`, `pattern_0x55`, `pattern_0x00_DC`,
  `pattern_0xFF_DC`, `saturation_250B`, `failsafe_paused`, `idle_monitor`,
  `collision_blind`+`post_collision` (half-duplex), `ber_random_long`,
  `baud_offset` (marge de tolerància de baud ±1/2/3%),
  `fullduplex_load`+`fullduplex_sat250` (full-duplex: càrrega simultània).
- **Perfils**: `smoke` (~2 min) · `standard` (~15 min) · `soak` (~2 h).
- **Barrido de bauds** (`--bauds`) amb canvi remot al slave; bauds alts i no
  estàndard (p.ex. 307200) suportats.
- **TUI en directe** (`rich`): progrés, test en curs amb descripció, FER,
  p50/p99, sparkline; taula amb veredictes de color.
- **Assistent** (`rs485-labtest wizard`): pregunta interfície, mode, ports
  (detectats), bauds, tests, criteris; **presets desables/reutilitzables**.
- **Notificacions Telegram**: alerta a cada FAIL + resum al final (i si
  s'interromp). Multi-destinatari (chat_id per coma) o grup.
- **Informes**: `.json` + `.md` + `_latencies.csv`, sempre UTF-8, amb seed i
  entorn per a reproduïbilitat.

## Executar al lab (ràpid)

```bash
cd ~/rs485-labtest
source .venv/bin/activate
rs485-labtest wizard                 # o directament:
rs485-labtest duo --port /dev/ttyACM0 --slave-port /dev/ttyACM1 \
    --interface rs485-half --profile soak --label "NDR6_Vcm+0V" --live rich
```

Guies: [[GUIA_LINUX]] (instal·lar/actualitzar/executar) ·
[[NOTES_SUPORT_REMOT]] (comandes de diagnòstic) ·
`docs/SETUP.md` (banc, cablejat) · `docs/TESTPLAN.md` (què vol dir cada FAIL).

## Arquitectura (mòduls a `src/rs485_labtest/`)

| Mòdul | Responsabilitat |
|---|---|
| `protocol.py` | trama (SOF·tipus·seq·len·payload·CRC16-CCITT), `FrameReader` |
| `transport.py` | interfície `Transport`, `open_port`, errors clars (baud/port) |
| `engine.py` | `TestEngine`: intercanvis, tràfic, idle, baud_offset, full-duplex |
| `battery.py` | pla de tests, criteris PASS/FAIL, orquestració |
| `catalog.py` | descripció de cada test (què/per què) — font única |
| `interfaces.py` | les 4 interfícies: duplex + guia d'interpretació |
| `monitor.py` | capa Monitor (Null/Plain/Rich/Multi/Telegram) |
| `notify.py` | Telegram (stdlib, resilient) |
| `wizard.py` | assistent + presets |
| `report.py` | JSON/MD/CSV |
| `cli.py` | subcomandes slave / master / battery / duo / wizard / notify-test |

## Decisions i restriccions (no trencar)

> [!warning] Contracte
> - **No canviar el format de trama** ni el comportament del slave: els informes
>   antics han de seguir sent comparables.
> - **Criteris per defecte FER = 0 i junk = 0** són intencionals (eina de
>   qualificació, no de monitorització).
> - **BER amb 0 errors** = cota superior al 95% CL (`< 3/n_bits`), mai "0".
> - **Ports sempre per `/dev/serial/by-id/`** a la documentació.

## Gotchas apresos (importants)

> [!tip] Coses que ens han fet perdre temps — no repetir
> - **Env vars al lab: el shell és BASH, no zsh** → van a `~/.bashrc`
>   (`echo "$0"` per confirmar). Bash no llegeix mai fitxers de zsh.
> - **Els adaptadors del lab surten com `/dev/ttyACM*`, no `ttyUSB*`.**
> - **Informes en UTF-8** (abans depenien de la plataforma; no eren portables).
> - **Timeout escala amb baud i mida de trama**: a 9600 amb 250 B, l'anada i
>   tornada (~0,54 s) superava el timeout fix de 0,5 s → fals FAIL. Corregit.
> - **Token Telegram 401** = token invàlid a la env var (no xarxa/chat_id).

## Resultats de camp (fins ara)

- **A 307200 (aplicació objectiu): validat** — soak 3 h, ~500k trames, 0
  errors, 0 junk, i marge de baud amb 0 errors fins a ±3%.
- **A 921600: FAIL reals** (timeouts + junk durant tràfic, idle net) → sostre
  d'alta velocitat **a aïllar amb hardware** (adaptador ttyACM? link?), no
  necessàriament defecte del NDR6.

## Pendent / roadmap

- [ ] **Aïllar el sostre de 921600** (provar un altre adaptador, sonda).
- [ ] Esborrar `legacy/` (la condició del handoff —CI verda + paritat— ja es
      compleix).
- [ ] **Timestamps d'errors** per correlacionar amb ràfegues EFT (IEC 61000-4-4).
- [ ] **Mode Modbus RTU** (FC03/FC16) per validar amb el protocol dels clients.
- [ ] `--matrix` (YAML de condicions Vcm/temp/baud) + informe consolidat.
- [ ] Export PDF amb branding Adilec (skill `adilec-reports`).

## Enllaços

- Repo: https://github.com/ferranc88/rs485-labtest
- Investigació de contrast del sector (BER/failsafe/UART tolerance): al fil de
  la sessió i a `docs/TESTPLAN.md`.

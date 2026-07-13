# rs485-labtest

Bateria d'estres *laboratory-grade* per a links **RS-485 half-duplex** — pensada
per validar convertidors RS-485 ↔ fibra optica (NDR6) i per a control de
qualitat d'entrada d'altres equips. Criteris PASS/FAIL explicits i informes
reproduibles (JSON + Markdown + CSV de latencies).

## El banc

```
[PC] --USB--> [adaptador A] --RS485--> [NDR6 #1] ==fibra==> [NDR6 #2] --RS485--> [adaptador B] --USB--> [PC]
                (master)                                                              (slave, fa eco)
```

Els dos extrems poden penjar del mateix PC: el mode `duo` ho orquestra tot sol.
Muntatge detallat del banc: [docs/SETUP.md](docs/SETUP.md).

## Instal·lacio

```bash
git clone <repo> && cd rs485-labtest
pip install -e .
rs485-labtest --help
```

Requereix Python ≥ 3.9. L'unica dependencia es `pyserial`.

## Quickstart (mode `duo`, tot des d'un PC)

```bash
rs485-labtest duo \
    --port /dev/serial/by-id/usb-FTDI_ADAPTADOR_A-if00-port0 \
    --slave-port /dev/serial/by-id/usb-FTDI_ADAPTADOR_B-if00-port0 \
    --profile smoke --label "NDR6_protoB_Vcm+0V" --outdir results/
```

> Feu servir sempre noms `/dev/serial/by-id/`: els `ttyUSBn` ballen entre
> replugs i podeu acabar testejant el link al reves.

Sortida tipica:

```
=== BATERIA RS-485 v0.3.0 === label=NDR6_protoB_Vcm+0V profile=smoke seed=1830294821
    12 tests | resultats a results/rs485_NDR6_protoB_Vcm+0V_20260713T083000Z.*

[ 1/12] sanity@115200                PASS tx=210 ok=210 p50=1.8ms p99=2.4ms
[ 2/12] turnaround_gap0@115200       PASS tx=1893 ok=1893 p50=1.7ms p99=2.2ms
...
[ 9/12] idle_monitor@115200          PASS tx=0 ok=0
[10/12] collision_blind@115200       INFO tx=1420 ok=0 | test de colisio: vegeu post_collision
[11/12] post_collision@115200        PASS tx=5 ok=5 p50=1.9ms p99=2.1ms
[12/12] ber_random_long@115200       PASS tx=641 ok=641 p50=13.2ms p99=14.0ms

=== RESULTAT GLOBAL: PASS (0 FAIL / 12 tests, 94.2s) ===
```

Codi de sortida: `0` si tot PASS, `1` si hi ha cap FAIL o la corrida
s'interromp (Ctrl-C genera igualment l'informe parcial).

## Modes

| Mode | Funcio |
|---|---|
| `slave` | escolta i fa eco; obeeix el canvi de baud remot (CMD_BAUD) |
| `master` | test individual manual amb parametres lliures |
| `battery` | bateria automatitzada de 12 tests + informes |
| `duo` | arrenca el `slave` com a subproces i corre la `battery` des d'un sol PC |

## Flags principals (`battery` / `duo`)

| Flag | Per defecte | Que fa |
|---|---|---|
| `--profile` | `standard` | `smoke` (~2 min) · `standard` (~15 min) · `soak` (~2 h) |
| `--bauds` | — | bauds addicionals per al barrido (canvi remot al slave) |
| `--label` | `unlabeled` | identificador del DUT/condicio (Vcm, temperatura...) |
| `--notes` | — | notes de l'operador per a l'informe |
| `--outdir` | `results` | carpeta de sortida |
| `--seed` | aleatori | llavor RNG per a corrides reproduibles |
| `--max-fer` | `0.0` | llindar de Frame Error Rate (0 = cap error tolerat) |
| `--max-p99` | `0.0` | llindar p99 de latencia en ms (0 = sense llindar) |

Els criteris per defecte (FER = 0, junk = 0) son intencionals: aixo es una
eina de **qualificacio**, no de monitoritzacio.

## Llegir l'informe

Cada corrida genera tres fitxers amb timestamp UTC i el `--label`:

- **`.json`** — resultats estructurats + metadades (seed, entorn, versio, criteris)
- **`.md`** — taula de resultats, motius de FAIL i guia d'interpretacio
- **`_latencies.csv`** — cada RTT individual

Claus rapides (la guia completa es a [docs/TESTPLAN.md](docs/TESTPLAN.md)):

- **junk > 0 o `idle_monitor` FAIL** → bias de failsafe insuficient
- **timeouts amb gap=0** → auto-direccio que trepitja la resposta
- **mismatch** → marge de bit degradat (jitter, slew-rate, reflexions)
- **`post_collision` FAIL** → latch-up d'un transceptor
- La **BER amb 0 errors** es reporta com a cota superior al 95% CL
  (`< 3/n_bits`), mai com a "BER = 0"

L'eina diu **que** falla; el diagnostic del **per que** es fa amb sonda
diferencial a l'oscil·loscopi.

## Documentacio

- [docs/SETUP.md](docs/SETUP.md) — muntatge del banc, `latency_timer`, permisos, noms by-id
- [docs/TESTPLAN.md](docs/TESTPLAN.md) — els 12 tests: que estressa cadascun i que significa un FAIL
- [docs/NDR6_MATRIX.md](docs/NDR6_MATRIX.md) — matriu de mode comu per al cas NDR6

## Desenvolupament

```bash
pip install -e ".[dev]"
ruff check src tests && mypy src
pytest                       # els tests d'integracio pty nomes corren a POSIX
pytest -m "not integration"  # nomes unitat (rapid, tambe a Windows)
```

Llicencia: [MIT](LICENSE)

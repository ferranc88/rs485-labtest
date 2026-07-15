# Muntatge del banc de proves

## Material

- 2 adaptadors USB ↔ RS-485 amb auto-direccio (FTDI recomanat)
- El link sota prova (DUT): p.ex. `[NDR6 #1] ==fibra== [NDR6 #2]`
- Cable de parell trenat per als trams RS-485 (A-A, B-B; no creuar)
- Opcional: font d'alimentacio flotant per injectar tensio de mode comu
  (vegeu [NDR6_MATRIX.md](NDR6_MATRIX.md))

## Topologia

```
[PC] --USB--> [adaptador A] --RS485--> [NDR6 #1] ==fibra==> [NDR6 #2] --RS485--> [adaptador B] --USB--> [PC]
                (master)                                                              (slave, fa eco)
```

Els dos adaptadors poden anar al mateix PC (mode `duo`) o a dos PCs diferents
(`battery` a un costat, `slave` a l'altre).

## Noms de port: sempre `/dev/serial/by-id/`

Els `ttyUSBn` **ballen entre replugs**: si els adaptadors s'intercanvien els
numeros, acabes testejant el link al reves sense adonar-te'n. Feu servir
sempre els enllacos estables:

```bash
ls -l /dev/serial/by-id/
# usb-FTDI_USB-RS485_Cable_FTXXXXXX-if00-port0 -> ../../ttyUSB0
```

Etiqueteu fisicament els dos adaptadors (A = master, B = slave) i apunteu els
seus `by-id` al full de la corrida.

## Permisos

```bash
sudo usermod -aG dialout $USER   # tanca sessio i torna a entrar
```

## `latency_timer` (adaptadors FTDI)

El driver FTDI agrupa bytes cada 16 ms per defecte, cosa que infla i
distorsiona les latencies mesurades. Baixeu-lo a 1 ms:

```bash
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB0/latency_timer
echo 1 | sudo tee /sys/bus/usb-serial/devices/ttyUSB1/latency_timer
```

(S'ha de repetir despres de cada replug, o fixar-ho amb una regla udev.)

## Terminacio i bias

- Terminacio de 120 Ω als dos extrems fisics del bus RS-485 si els trams son
  llargs; en trams curts de banc pot ometre's.
- **No afegiu bias extern al DUT sense apuntar-ho**: el que es vol
  caracteritzar es precisament el failsafe del DUT. Si l'adaptador USB porta
  bias propi commutable, documenteu-ne l'estat a `--notes`.

## Interfícies i cablejat

Tria què proves amb `--interface` (o a la primera pregunta de l'assistent):
`rs485-half` (per defecte), `rs485-full`, `rs422` o `rs232`.

### RS-485 half-duplex (`rs485-half`) — un parell compartit
```
[A]  A/B  ──────────┬──────────  A/B  [B]
                (mateix parell; els dos extrems s'alternen)
```
Els dos extrems comparteixen el parell i s'han de torn (turnaround). Aquí
apliquen els tests de **col·lisió** (`collision_blind`, `post_collision`) i el
turnaround és crític.

### RS-485 full-duplex (`rs485-full`) i RS-422 (`rs422`) — un parell per sentit
```
[A] TX+/TX- ─────────────────────► RX+/RX- [B]
[A] RX+/RX- ◄───────────────────── TX+/TX- [B]
```
El TX de cada extrem va al RX de l'altre (**creuat**). Cada sentit té el seu
parell, així que:

- **No hi ha col·lisions** en punt a punt → `collision_blind` i
  `post_collision` no apliquen i l'eina els treu del pla.
- **Es pot transmetre en les dues direccions alhora** → s'afegeixen
  `fullduplex_load` i `fullduplex_sat250`, que carreguen els dos parells
  simultàniament (impossible en 2 fils).
- El **failsafe segueix aplicant a cada parell**: `idle_monitor` i
  `failsafe_paused` es mantenen.

```bash
rs485-labtest duo \
    --port /dev/serial/by-id/<A> --slave-port /dev/serial/by-id/<B> \
    --interface rs485-full --profile standard --label "NDR6_4fils" --live rich
```

> Comprova el creuament: si connectes TX amb TX no rebràs res i el `sanity`
> fallarà de cop. Terminació de 120 Ω a l'extrem receptor de **cada** parell.

**RS-422 vs RS-485 de 4 fils**: elèctricament el banc és el mateix; la
diferència és que en RS-422 l'emissor va **sempre habilitat** (no hi ha
tri-state ni contesa possible). Per això la guia de l'informe canvia: junk en
repòs no és bias de failsafe sinó soroll o terminació. Si el teu DUT exigeix
tri-state de l'emissor, no és RS-422 pur — prova'l com a `rs485-full`.

### RS-232 (`rs232`) — single-ended
```
[A] TX ──────────────────────────► RX [B]
[A] RX ◄────────────────────────── TX [B]
[A] GND ─────────────────────────  GND [B]
```
Creuat (null-modem) i amb **massa comuna**. Diferències importants:

- Senyal **referit a massa**, no diferencial: no hi ha A/B, ni bias de
  failsafe, ni rebuig de mode comú. Aquests conceptes no apliquen i la guia de
  l'informe no els menciona.
- El punt dèbil és la **massa i la longitud**: RS-232 degrada amb la capacitat
  del cable (límit clàssic ~15 m, molt menys a baud alt). Si veus errors que
  creixen amb el baud, prova un cable més curt abans d'acusar el DUT.
- L'eina **no toca el control de flux per maquinari** (RTS/CTS): si el DUT en
  depèn, cablega'l o desactiva'l.

```bash
rs485-labtest duo --port ... --slave-port ... --interface rs232
```

## Baud rates alts i no estàndard

L'eina accepta **qualsevol** valor de baud, tant a `--baud` com al barrido
`--bauds` (canvi remot al slave). No hi ha cap topall al programari; el límit
real és l'adaptador i el driver.

### Valors no estàndard (p.ex. 307200)
Un baud que no és a la taula clàssica (com **307200** = 300 × 1024) es genera
amb el **divisor fraccionari** del xip. Conseqüències pràctiques:

- A Linux, pyserial el fixa via `termios2`/`BOTHER` sense cap pas extra:
  `--baud 307200` funciona directament.
- El divisor pot no donar el valor **exacte**: el baud real queda a poques
  dècimes de %. RS-485 (UART async) tolera un desajust total emissor-receptor
  de **~2-3%** abans de mostrejar malament, així que 307200 real vs. nominal
  no és problema — però si sospites, mira'l amb l'oscil·loscopi (període de
  bit) i compara amb l'altre extrem.
- Els dos extrems han d'anar al **mateix** baud. El barrido ja ho garanteix
  (canvi remot via CMD_BAUD); si els poses a mà, posa el mateix nombre a
  `slave` i a `battery`.

### Sostres típics per xip
| Xip de l'adaptador | Baud màxim pràctic |
|---|---|
| FTDI FT232R | ~3 Mbaud |
| FTDI FT2232H / FT232H | fins a 12 Mbaud |
| Silicon Labs CP210x | ~2 Mbaud (models nous) |
| WCH CH340 / CH341 | ~2 Mbaud |

Si demanes un baud per sobre del que l'adaptador pot generar, l'eina
ara ho diu clar (`BaudNotSupported`, amb el valor i pistes) en lloc de petar
amb un traceback. Dins d'un barrido, aquell baud es marca FAIL i la resta
continua.

### A tenir en compte a baud alt
- Baixa el **`latency_timer` a 1 ms** (secció anterior): a 2-3 Mbaud, els 16 ms
  per defecte del FTDI dominen completament la latència mesurada.
- El coll d'ampolla passa a ser el **turnaround** i el USB, no el fil: veuràs
  la latència plana i el throughput pujar amb el baud.
- Fils curts i terminació correcta són més crítics com més amunt vas
  (reflexions i slew-rate).

Exemple amb l'aplicació de 307200 i un barrido cap amunt:
```bash
rs485-labtest duo \
    --port /dev/serial/by-id/<A> --slave-port /dev/serial/by-id/<B> \
    --baud 307200 --bauds 921600 2000000 \
    --profile standard --label "NDR6_app307k2" --live rich
```

## Primera corrida

```bash
# fum rapid (~2 min) per validar el muntatge
rs485-labtest duo \
    --port /dev/serial/by-id/<ADAPTADOR_A> \
    --slave-port /dev/serial/by-id/<ADAPTADOR_B> \
    --profile smoke --label "muntatge_inicial"
```

Si `sanity` falla de cop: reviseu polaritat A/B, baud i que el slave
realment escolta el port B.

## Que NO fa aquesta eina

L'eina diu **que** falla (FER, junk, timeouts, latencies) i sota quines
condicions. El diagnostic del **per que** — nivells diferencials, flancs,
reflexions — es fa amb sonda diferencial a l'oscil·loscopi.

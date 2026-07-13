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

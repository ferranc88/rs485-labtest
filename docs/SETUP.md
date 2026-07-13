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

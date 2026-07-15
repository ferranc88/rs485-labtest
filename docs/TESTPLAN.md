# Pla de tests: els 13 tests de la bateria

Cada corrida executa aquests tests al baud base (i un subconjunt
representatiu a cada baud extra de `--bauds`). Els parametres de durada
depenen del perfil (`smoke` / `standard` / `soak`). El test 13 (marge de
baud) es desplega en 6 subcorrides (±1/2/3%).

| # | Test | Que fa | Que estressa |
|---|------|--------|--------------|
| 1 | `sanity` | trames curtes amb gap de 20 ms | que el banc esta ben muntat abans de res |
| 2 | `turnaround_gap0` | trames curtes sense cap gap | el turnaround del DUT: auto-direccio, temps de canvi TX/RX |
| 3 | `min_frames` | payload d'1 byte, sense gap | la trama minima: framing i overhead per trama |
| 4 | `pattern_0x55` | payload 0x55 (alternanca maxima) | maxim de transicions: jitter, slew-rate, amplada de banda |
| 5 | `pattern_0x00_DC` | payload 0x00 | contingut DC baix: llargues estones a nivell dominant |
| 6 | `pattern_0xFF_DC` | payload 0xFF | contingut DC alt: llargues estones prop del nivell d'idle |
| 7 | `saturation_250B` | trames de 250 B sense gap | throughput sostingut: buffers, FIFO, control de flux intern |
| 8 | `failsafe_paused` | trames grans amb pauses de 500 ms | les transicions bus actiu ↔ bus en repos: el moment critic del failsafe |
| 9 | `idle_monitor` | escolta amb el bus mut | el failsafe pur: amb el bus en repos NO ha d'arribar cap byte |
| 10 | `collision_blind` | transmissio cega sense esperar resposta | solapaments deliberats: com es comporta el DUT sota colisions |
| 11 | `post_collision` | 5 pings de sanitat despres de les colisions | recuperacio: que cap transceptor s'hagi quedat encallat en TX |
| 12 | `ber_random_long` | trafic aleatori llarg | estimacio/cota de BER amb volum estadistic |
| 13 | `baud_offset` | el master es desplaça ±1/2/3% del baud nominal (el slave no es toca) | el pressupost de tolerancia de baud del link sencer |

Nomes amb `--wires 4` (full-duplex); en 2 fils no apliquen:

| # | Test | Que fa | Que estressa |
|---|------|--------|--------------|
| 14 | `fullduplex_load` | finestra de 8 trames de 64 B en vol, sense esperar l'eco | les dues direccions actives alhora |
| 15 | `fullduplex_sat250` | igual amb trames de 250 B | buffers del convertidor en els dos sentits a la vegada |

Nomes amb `--wires 2` (half-duplex): `collision_blind` i `post_collision` —
en 4 fils cada sentit te el seu parell i no hi ha bus compartit on colisionar.

## Que significa cada FAIL

### `idle_monitor` FAIL o junk > 0 a qualsevol test
Bytes fantasma amb el bus en repos → **bias de failsafe insuficient**. El
receptor interpreta soroll com a dades quan ningu no transmet. Verificacio:
sonda diferencial A-B en idle; ha de ser > +200 mV.

### Timeouts concentrats a `turnaround_gap0` / `min_frames`
El **driver enable (auto-direccio) es queda actiu massa temps** i trepitja
el primer tros de la resposta del slave. Tipic d'auto-direccio per timeout
fixe dimensionada per a un baud diferent.

### Mismatch (payload corrupte amb framing i CRC valids del parser)
El cas mes perillos: la trama "sembla" bona pero el contingut no ho es.
**Marge de bit degradat**: jitter, slew-rate insuficient o reflexions.

### FAILs nomes a `pattern_0x00_DC` / `pattern_0xFF_DC`
Sensibilitat al **contingut DC**: acoblament AC en algun punt del cami
(tipic en conversio a fibra) o wander del llindar de decisio.

### FAILs nomes a `saturation_250B`
Perdues per **desbordament de buffers** interns del convertidor, no pas per
integritat de senyal.

### `failsafe_paused` FAIL amb la resta neta
El problema es a la **transicio** actiu→repos (glitch del failsafe en
alliberar el bus), no en regim continu.

### `post_collision` FAIL
**Latch-up**: despres d'una colisio, un transceptor es queda engegat en TX i
el bus no torna. `collision_blind` es sempre INFO; el veredicte el dona
aquest test.

### p99 >> p50 a les latencies
Turnaround **no determinista**: auto-baud, buffers d'emmagatzematge i
reenviament o timers interns del convertidor.

### `fullduplex_*` FAIL amb la resta neta (4 fils)
Les dues direccions per separat van bé, però alhora no. Apunta al **camí de
tornada compartit**: un convertidor que multiplexa els dos sentits sobre una
fibra, o que comparteix buffers entre direccions. Si només falla
`fullduplex_sat250` (250 B) i no `fullduplex_load` (64 B), és **memòria**, no
ample de banda. Compara el throughput de cada sentit per separat abans
d'acusar el DUT.

### Timeouts NOMES a baud baix amb trames grans
Si veus timeouts concentrats en tests de trama gran (`saturation_250B`,
`failsafe_paused`) **només a baud baix** (p.ex. 9600) i el link va fi a la
resta, no és el DUT: és que la trama triga a anar i tornar més que el timeout.
L'eina ja escala el timeout amb el baud i la mida (`min_exchange_timeout`),
però si toques els timeouts a mà, recorda que a 9600 una trama de 250 B són
~0,54 s d'anada i tornada.

### `baud_offset`: com llegir el marge
Un link UART asincron tolera **~2% de desajust de baud acumulat** entre
emissor i receptor (limit teoric ~3,3% amb mostreig 16x). Cada re-clock pel
cami — i una conversio a fibra en sol fer — **consumeix part d'aquest
pressupost**. El test desplaça nomes el baud del master:

- **±1% ha de passar** (llindar `--baud-margin`, per defecte 1.0): si falla,
  el pressupost del link ja esta esgotat per la propia cadena i qualsevol
  client amb un oscil.lador mediocre patira.
- **±2% i ±3% son caracteritzacio** (INFO): el punt on comença el FER es el
  marge real que queda. Un redisseny sa hauria de mantenir o millorar aquest
  punt respecte del prototip anterior — compareu-lo entre corrides.

## La BER

Amb 0 errors observats, la BER **no es reporta com a zero** sino com a cota
superior al 95% de confianca per la regla de tres: `BER < 3/n_bits`. Amb
errors, es reporta `>= errors/n_bits` (cota inferior: cada trama dolenta
tenia com a minim 1 bit dolent). Per estrenyer la cota, allargueu la corrida
(perfil `soak`).

## Reproduibilitat

Cada corrida apunta la `seed` del RNG a l'informe. Repetir amb `--seed N`
regenera exactament les mateixes sequencies de payload.

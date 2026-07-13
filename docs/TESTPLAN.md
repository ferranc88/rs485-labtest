# Pla de tests: els 12 tests de la bateria

Cada corrida executa aquests 12 tests al baud base (i un subconjunt
representatiu a cada baud extra de `--bauds`). Els parametres de durada
depenen del perfil (`smoke` / `standard` / `soak`).

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

## La BER

Amb 0 errors observats, la BER **no es reporta com a zero** sino com a cota
superior al 95% de confianca per la regla de tres: `BER < 3/n_bits`. Amb
errors, es reporta `>= errors/n_bits` (cota inferior: cada trama dolenta
tenia com a minim 1 bit dolent). Per estrenyer la cota, allargueu la corrida
(perfil `soak`).

## Reproduibilitat

Cada corrida apunta la `seed` del RNG a l'informe. Repetir amb `--seed N`
regenera exactament les mateixes sequencies de payload.

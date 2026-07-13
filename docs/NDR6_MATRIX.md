# Matriu de mode comu — cas NDR6

## Context

El NDR6 (convertidor RS-485 ↔ fibra optica) s'esta redissenyant arran d'una
incidencia de camp d'integritat de senyal relacionada amb **tensio de mode
comu (Vcm)** i **bias de failsafe**. Aquesta matriu defineix les condicions
sota les quals cal passar la bateria per trobar el punt de trencament i
validar el redisseny.

## Muntatge d'injeccio de Vcm

S'injecta una tensio continua entre la referencia (GND RS-485) de l'extrem A
i la del DUT amb una font flotant, desplacant el mode comu que veu el
transceptor del NDR6. La norma RS-485 exigeix operacio amb Vcm dins de
**-7 V ... +12 V**; el marge real del DUT es el que volem mesurar, aixi que
el barrido surt d'aquest rang fins a trobar el trencament.

> Pujeu la Vcm **gradualment** i conegueu els limits absoluts del transceptor
> abans de sortir del rang normatiu: mes enlla hi ha risc de dany permanent.

## Matriu de condicions

Per a cada condicio, una corrida completa amb `--label` que la codifiqui:

| Dimensio | Valors |
|---|---|
| Vcm | 0, +3, +5, +7, +9, +12, -3, -5, -7 V (i mes enlla, amb compte, fins al trencament) |
| Baud | 9600, 115200, 921600 (via `--bauds`, canvi remot automatic) |
| Temperatura | ambient; si la incidencia ho suggereix, extrems de la cambra |
| Perfil | `standard` per al barrido; `soak` a les condicions critiques |

```bash
# exemple: una cel.la de la matriu
rs485-labtest battery \
    --port /dev/serial/by-id/<ADAPTADOR_A> \
    --profile standard --bauds 9600 921600 \
    --label "NDR6_protoB_Vcm+7V_Tamb" \
    --notes "font flotant XYZ, injeccio a extrem A, terminacio 120R als 2 extrems"
```

Entre corrida i corrida: ajustar la font, esperar l'estabilitzacio i apuntar
la Vcm real mesurada (no la consigna) a `--notes`.

## Que buscar

1. **`junk_bytes` i `idle_monitor` vs. Vcm** — el primer que sol cedir es el
   failsafe: apareixen bytes fantasma en repos abans que el trafic falli.
   La Vcm on `junk` deixa de ser 0 es el marge real de failsafe.
2. **FER vs. Vcm** — el segon llindar: el trafic comenca a perdre trames.
3. **Asimetria** — comparar el comportament a Vcm positiva i negativa; una
   asimetria marcada apunta al circuit de bias, no al transceptor.
4. **Dependencia del baud** — si el trencament arriba abans a 921600,
   el problema te component de marge de temps, no nomes de nivell.

El criteri d'acceptacio del redisseny es defineix sobre aquesta matriu:
**cap FAIL dins de -7 V ... +12 V a tots els bauds de servei**.

## Consolidacio

De moment, la comparativa entre condicions es fa a ma a partir dels `.json`
(un per corrida, el `label` porta la condicio). Hi ha previstes dues millores
que ho automatitzaran: un mode `--matrix` (fitxer YAML de condicions amb
pausa entre corrides) i una subcomanda `report consolidate` (taula + grafic
FER/junk vs. Vcm). Vegeu el CHANGELOG/issues del repo.

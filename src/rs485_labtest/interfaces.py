"""Interficies serie que es poden posar a prova, i que vol dir cada fallada.

El pla de tests nomes depen del *duplex* (half vs full): en half hi ha bus
compartit -> colisions i turnaround; en full cada sentit te el seu cami ->
carrega simultania. Pero la **interpretacio** dels errors si que depen de la
interficie: parlar de "bias de failsafe" o de "diferencial A-B" no te cap
sentit en RS-232, que es single-ended.

Aquest modul es la font unica d'aquesta distincio.
"""

from __future__ import annotations

from typing import TypedDict


class InterfaceInfo(TypedDict):
    title: str          # nom llegible, tal com ha de sortir a l'informe
    icon: str
    duplex: str         # "half" | "full" -> es l'unic que canvia el pla
    wiring: str         # cablejat esperat al banc
    what: str           # que es, en una frase
    hints: list[str]    # guia d'interpretacio especifica d'aquesta interficie


DEFAULT_INTERFACE = "rs485-half"

INTERFACES: dict[str, InterfaceInfo] = {
    "rs485-half": {
        "title": "RS-485 half-duplex (2 fils)",
        "icon": "🔁",
        "duplex": "half",
        "wiring": "un parell diferencial compartit (A/B als dos extrems)",
        "what": "Un sol parell; els dos extrems s'alternen per transmetre.",
        "hints": [
            "**Junk amb bus en repos / idle_monitor FAIL** -> bias de failsafe "
            "insuficient; mirar diferencial A-B en idle amb sonda "
            "(ha de ser > +200 mV).",
            "**Timeouts amb gap=0** -> el driver enable (auto-direccio) es queda "
            "actiu massa temps i trepitja la resposta.",
            "**post_collision FAIL** -> latch-up: un transceptor es queda en TX.",
        ],
    },
    "rs485-full": {
        "title": "RS-485 full-duplex (4 fils)",
        "icon": "🔀",
        "duplex": "full",
        "wiring": "dos parells diferencials creuats (TX d'un extrem al RX de l'altre)",
        "what": "Un parell per sentit; es pot transmetre en les dues direccions "
                "alhora. En punt a punt no hi ha bus compartit.",
        "hints": [
            "**Junk amb bus en repos / idle_monitor FAIL** -> bias de failsafe "
            "insuficient al parell de tornada; mirar-hi el diferencial en idle "
            "(> +200 mV).",
            "**fullduplex_* FAIL amb la resta neta** -> el convertidor ofega un "
            "sentit quan l'altre va carregat: fibra multiplexada o buffers "
            "compartits entre direccions.",
            "**Nomes fullduplex_sat250 FAIL (i load no)** -> falta de memoria, "
            "no d'ample de banda.",
        ],
    },
    "rs422": {
        "title": "RS-422 (4 fils, un sol emissor)",
        "icon": "➡️",
        "duplex": "full",
        "wiring": "dos parells diferencials creuats; un unic emissor per parell",
        "what": "Com el RS-485 de 4 fils pero amb un sol emissor per linia, "
                "sempre habilitat: no hi ha mai contesa de bus.",
        "hints": [
            "L'emissor va **sempre habilitat**: si veus junk en repos NO es bias "
            "de failsafe (aqui no aplica) sino soroll acoblat, terminacio "
            "incorrecta o reflexions.",
            "**fullduplex_* FAIL amb la resta neta** -> el convertidor ofega un "
            "sentit quan l'altre va carregat (buffers o cami de tornada compartit).",
            "Si el DUT exigeix tri-state de l'emissor, no es RS-422 pur: "
            "prova'l com a rs485-full.",
        ],
    },
    "rs232": {
        "title": "RS-232 (single-ended, full-duplex)",
        "icon": "🔌",
        "duplex": "full",
        "wiring": "TX, RX i massa comuna (creuat: TX d'un extrem al RX de l'altre)",
        "what": "Senyal single-ended referit a massa, punt a punt, amb linies "
                "separades per a cada sentit.",
        "hints": [
            "Senyal **single-ended**: els conceptes de bias de failsafe i de "
            "rebuig de mode comu diferencial NO apliquen. No busquis A/B ni "
            "els +200 mV amb la sonda.",
            "**Junk en repos** -> soroll acoblat, bucle de massa o cable massa "
            "llarg: RS-232 no te rebuig de mode comu i la massa comuna es el "
            "punt debil.",
            "**Errors que creixen amb el baud** -> RS-232 degrada amb la "
            "longitud i la capacitat del cable (limit classic ~15 m; molt menys "
            "a baud alt). Prova amb un cable mes curt abans d'acusar el DUT.",
            "**Nota:** l'eina no toca ni comprova el control de flux per "
            "maquinari (RTS/CTS); si el DUT en depen, cablega'l o desactiva'l.",
        ],
    },
}

# Guia que aplica a qualsevol interficie (el nivell UART es comu a totes).
COMMON_HINTS: list[str] = [
    "**Mismatch (payload corrupte amb framing valid)** -> marge de bit "
    "degradat: jitter, slew-rate o reflexions.",
    "**p99 >> p50** -> turnaround no determinista (auto-baud o buffers).",
    "**baud_offset**: ±1% ha de passar; on comença el FER es el marge real de "
    "tolerancia de baud que li queda al link.",
]


def describe_interface(name: str) -> InterfaceInfo | None:
    """Fitxa d'una interficie pel seu identificador."""
    return INTERFACES.get(name)


def interface_duplex(name: str) -> str:
    """``half`` o ``full``: l'unic que fa variar el pla de tests."""
    info = INTERFACES.get(name)
    return info["duplex"] if info else "half"


def interface_hints(name: str) -> list[str]:
    """Guia d'interpretacio: la comuna mes l'especifica de la interficie."""
    info = INTERFACES.get(name)
    return (info["hints"] if info else []) + COMMON_HINTS


def interface_for_wires(wires: int) -> str:
    """Compatibilitat amb l'antic ``--wires`` (2 = half, 4 = full)."""
    return "rs485-full" if int(wires) == 4 else "rs485-half"

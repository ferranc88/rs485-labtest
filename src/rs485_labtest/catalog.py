"""Cataleg dels tests: descripcio de que fa cadascun i per que.

Font unica de veritat per a la descripcio dels tests. La consumeixen:
- els monitors (mostren que s'esta fent i per que, en directe);
- l'assistent interactiu (per triar quins tests corre);
- la validacio de ``--tests``.

Les durades i parametres viuen a ``battery.battery_plan``; aqui nomes hi ha
el *significat* de cada test.
"""

from __future__ import annotations

from typing import TypedDict


class TestInfo(TypedDict):
    title: str      # nom llegible
    icon: str       # emoji per a la UI
    what: str       # que fa (una frase)
    why: str        # per que / que estressa / que vol dir un FAIL


# Ordre canonic de la bateria (el mateix que battery_plan).
TEST_ORDER: list[str] = [
    "sanity", "turnaround_gap0", "min_frames", "pattern_0x55",
    "pattern_0x00_DC", "pattern_0xFF_DC", "saturation_250B", "failsafe_paused",
    "idle_monitor", "collision_blind", "post_collision", "ber_random_long",
    "baud_offset",
]

TEST_CATALOG: dict[str, TestInfo] = {
    "sanity": {
        "title": "Sanejament del link",
        "icon": "🩺",
        "what": "Trames curtes amb un gap de 20 ms entre elles.",
        "why": "Confirma que el banc esta ben muntat abans de res. Si falla, "
               "revisa polaritat A/B, baud i que el slave escolti el port.",
    },
    "turnaround_gap0": {
        "title": "Turnaround sense pausa",
        "icon": "🔁",
        "what": "Trames curtes encadenades sense cap gap.",
        "why": "Estressa el temps de canvi TX->RX (auto-direccio). Timeouts aqui "
               "= el driver enable es queda actiu massa i trepitja la resposta.",
    },
    "min_frames": {
        "title": "Trama minima",
        "icon": "🔬",
        "what": "Payload d'1 sol byte, sense gap.",
        "why": "Aïlla el framing i l'overhead per trama del cos de dades.",
    },
    "pattern_0x55": {
        "title": "Alternança maxima (0x55)",
        "icon": "🌊",
        "what": "Payload 0x55 = 01010101, transicions a cada bit.",
        "why": "Marge de banda i slew-rate al maxim de transicions. Mismatch "
               "aqui = jitter o flancs degradats.",
    },
    "pattern_0x00_DC": {
        "title": "DC baix (0x00)",
        "icon": "⬇️",
        "what": "Payload tot zeros.",
        "why": "Estones llargues a nivell dominant. Sensibilitat al contingut DC "
               "(acoblament AC, wander del llindar), tipic en conversio a fibra.",
    },
    "pattern_0xFF_DC": {
        "title": "DC alt (0xFF)",
        "icon": "⬆️",
        "what": "Payload tot uns.",
        "why": "Estones llargues prop del nivell d'idle. L'altra cara del DC: "
               "confirma simetria del receptor.",
    },
    "saturation_250B": {
        "title": "Saturacio (250 B)",
        "icon": "🌊",
        "what": "Trames grans de 250 bytes sense gap.",
        "why": "Throughput sostingut: buffers, FIFO i control de flux intern. "
               "FAIL nomes aqui = desbordament, no integritat de senyal.",
    },
    "failsafe_paused": {
        "title": "Failsafe amb pauses",
        "icon": "⏸️",
        "what": "Trames grans amb pauses de 500 ms entremig.",
        "why": "El moment critic del failsafe: la transicio bus actiu<->repos. "
               "FAIL aqui i la resta neta = glitch en alliberar el bus.",
    },
    "idle_monitor": {
        "title": "Monitor de repos",
        "icon": "🤫",
        "what": "Escolta amb el bus totalment mut (no transmet res).",
        "why": "El failsafe pur: en repos NO ha d'arribar cap byte. Qualsevol "
               "byte = bias de failsafe insuficient (mira A-B > +200 mV).",
    },
    "collision_blind": {
        "title": "Col·lisions cegues",
        "icon": "💥",
        "what": "Transmissio cega sense esperar resposta, forçant solapaments.",
        "why": "Sotmet el DUT a col·lisions. Sempre INFO; el veredicte real el "
               "dona el test seguent (post_collision).",
    },
    "post_collision": {
        "title": "Recuperacio post-col·lisio",
        "icon": "🚑",
        "what": "5 pings de sanitat just despres de les col·lisions.",
        "why": "Comprova que cap transceptor s'ha quedat encallat en TX "
               "(latch-up). FAIL = el bus no torna despres del cop.",
    },
    "ber_random_long": {
        "title": "BER (aleatori llarg)",
        "icon": "🎲",
        "what": "Trafic pseudoaleatori llarg amb volum estadistic.",
        "why": "Estima/acota la BER. Amb 0 errors es reporta com a cota superior "
               "al 95% CL (< 3/n_bits), mai com a zero.",
    },
    "baud_offset": {
        "title": "Marge de tolerancia de baud",
        "icon": "🎯",
        "what": "Desplaça el baud del master ±1/2/3% respecte del slave "
                "(que queda al nominal) i mesura el FER a cada desajust.",
        "why": "Un link UART tolera ~2% de desajust acumulat entre extrems; "
               "cada re-clock pel cami (conversio a fibra) en consumeix. "
               "±1% ha de passar; on comença el FER es el marge real que queda.",
    },
}


def base_name(name: str) -> str:
    """Treu el sufix ``@baud`` del nom d'un test (``sanity@115200`` -> ``sanity``)."""
    return name.split("@", 1)[0]


def describe(name: str) -> TestInfo | None:
    """Descripcio d'un test pel seu nom (amb o sense sufixos).

    Accepta ``sanity``, ``sanity@115200`` i variants amb parametres al nom
    com ``baud_offset+2%@115200``.
    """
    base = base_name(name)
    info = TEST_CATALOG.get(base)
    if info is not None:
        return info
    for key, val in TEST_CATALOG.items():
        if base.startswith(key):
            return val
    return None


def unknown_tests(names: list[str]) -> list[str]:
    """Retorna els noms que no son tests valids (per validar ``--tests``)."""
    return [n for n in names if n not in TEST_CATALOG]

"""Notificacions per Telegram: alerta a cada FAIL i resum en acabar.

Pensat per a corrides llargues (soak) on no estas mirant el terminal. Fa
servir nomes la stdlib (``urllib``) contra la Bot API de Telegram, i es
**resilient**: si no hi ha xarxa, l'enviament falla en silenci i mai atura ni
bloqueja la bateria (timeout curt + captura d'excepcions).

Configuracio per variables d'entorn (el token no ha d'anar mai a la linia
d'ordres, que queda a l'historial del shell):

    export RS485_TELEGRAM_TOKEN="123456:ABC-..."
    export RS485_TELEGRAM_CHAT_ID="987654321"

El token el dona @BotFather; el chat_id es descobreix amb ``notify-test``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib import parse as urlparse
from urllib import request as urlrequest

from .interfaces import DEFAULT_INTERFACE, describe_interface

log = logging.getLogger(__name__)

ENV_TOKEN = "RS485_TELEGRAM_TOKEN"
ENV_CHAT = "RS485_TELEGRAM_CHAT_ID"
_API = "https://api.telegram.org/bot{token}/{method}"


# ------------------------------------------------------------------ format
def human_duration(seconds: float) -> str:
    """3661 s -> '1h 1m 1s'."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if h or m:                    # si hi ha hores, mostra els minuts encara que 0
        parts.append(f"{m}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


def format_start(meta: dict[str, Any], n_tests: int) -> str:
    iface = describe_interface(meta.get("interface", DEFAULT_INTERFACE))
    return (f"🚀 rs485-labtest — inici\n"
            f"DUT: {meta.get('label', '?')}\n"
            f"Interfície: {iface['title'] if iface else '?'}\n"
            f"Perfil: {meta.get('profile', '?')} · baud {meta.get('base_baud', '?')}\n"
            f"{n_tests} tests")


def format_fail(res: dict[str, Any], meta: dict[str, Any]) -> str:
    reasons = res.get("reasons") or []
    detail = "; ".join(reasons[:3]) if reasons else "veure informe"
    return (f"⚠️ FAIL — {res.get('name', '?')}\n"
            f"{detail}\n"
            f"(DUT {meta.get('label', '?')})")


def format_summary(meta: dict[str, Any], results: list[dict[str, Any]],
                   n_fail: int, elapsed_s: float, base: str) -> str:
    iface = describe_interface(meta.get("interface", DEFAULT_INTERFACE))
    n = len(results)
    aborted = meta.get("aborted")
    if aborted:
        head = "🟠 rs485-labtest — INTERROMPUT"
    elif n_fail:
        head = "❌ rs485-labtest — FAIL"
    else:
        head = "✅ rs485-labtest — PASS"

    lines = [
        head,
        f"DUT: {meta.get('label', '?')}",
        f"Interfície: {iface['title'] if iface else '?'}",
        f"Perfil: {meta.get('profile', '?')} · baud {meta.get('base_baud', '?')}",
        f"Durada: {human_duration(elapsed_s)}",
        f"Resultat: {n - n_fail}/{n} PASS · {n_fail} FAIL",
    ]
    fails = [r for r in results if r.get("verdict") == "FAIL"]
    if fails:
        lines.append("")
        lines.append("Tests fallits:")
        for r in fails[:10]:
            reason = (r.get("reasons") or ["-"])[0]
            lines.append(f"✗ {r.get('name', '?')} — {reason}")
        if len(fails) > 10:
            lines.append(f"…i {len(fails) - 10} més")
    lines.append("")
    lines.append(f"Informes: {os.path.basename(base)}.{{json,md,csv}}")
    return "\n".join(lines)


# ------------------------------------------------------------------ transport
class TelegramNotifier:
    """Enviament de missatges a un chat de Telegram. Mai llença cap excepcio."""

    def __init__(self, token: str, chat_id: str, timeout: float = 10.0) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> TelegramNotifier | None:
        e = env if env is not None else os.environ
        token, chat = e.get(ENV_TOKEN), e.get(ENV_CHAT)
        if token and chat:
            return cls(token, chat)
        return None

    def send(self, text: str) -> bool:
        """Envia un missatge de text pla. Retorna True si Telegram l'accepta.

        Sense ``parse_mode``: els noms de test porten ``_`` i ``@``, que en
        Markdown de Telegram es menjarien o donarien error.
        """
        url = _API.format(token=self.token, method="sendMessage")
        data = urlparse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        try:
            req = urlrequest.Request(url, data=data)
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                log.warning("[telegram] rebutjat: %s", body.get("description"))
                return False
            return True
        except Exception as exc:                  # xarxa, timeout, JSON, el que sigui
            log.warning("[telegram] no s'ha pogut enviar: %s", exc)
            return False


def discover_chat_ids(token: str, timeout: float = 10.0) -> list[tuple[str, str]]:
    """Chats que han escrit al bot (via getUpdates), per trobar el chat_id."""
    url = _API.format(token=token, method="getUpdates")
    try:
        with urlrequest.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log.warning("[telegram] getUpdates ha fallat: %s", exc)
        return []
    seen: dict[str, str] = {}
    for upd in body.get("result", []):
        chat = (upd.get("message") or upd.get("channel_post") or {}).get("chat", {})
        cid = chat.get("id")
        if cid is not None:
            name = chat.get("title") or chat.get("username") \
                or " ".join(filter(None, [chat.get("first_name"),
                                          chat.get("last_name")])) or "?"
            seen[str(cid)] = name
    return list(seen.items())


def build_notifier(args: Any) -> TelegramNotifier | None:
    """Crea el notifier segons ``--notify`` (auto|telegram|off) i l'entorn."""
    mode = getattr(args, "notify", "auto")
    if mode == "off":
        return None
    notifier = TelegramNotifier.from_env()
    if notifier is None and mode == "telegram":
        log.warning("[telegram] --notify telegram pero falten %s / %s; "
                    "notificacions desactivades", ENV_TOKEN, ENV_CHAT)
    return notifier

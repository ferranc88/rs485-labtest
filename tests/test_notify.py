"""Tests de notificacions Telegram: format, transport robust i integracio."""

import io
import json
import types

from rs485_labtest import notify
from rs485_labtest.monitor import MultiMonitor, TelegramMonitor
from rs485_labtest.notify import (
    ENV_CHAT,
    ENV_TOKEN,
    TelegramNotifier,
    build_notifier,
    format_fail,
    format_start,
    format_summary,
    human_duration,
)


# ------------------------------------------------------------------- format
def test_human_duration():
    assert human_duration(0) == "0s"
    assert human_duration(59) == "59s"
    assert human_duration(61) == "1m 1s"
    assert human_duration(3661) == "1h 1m 1s"
    assert human_duration(10804.5) == "3h 0m 4s"    # els minuts a 0 s'hi mostren


def _meta(**over):
    m = dict(label="NDR6_Vcm+7V", interface="rs485-half", profile="soak",
             base_baud=307200, aborted=False)
    m.update(over)
    return m


def test_format_summary_pass():
    results = [dict(name="sanity@307200", verdict="PASS", reasons=[])] * 3
    txt = format_summary(_meta(), results, 0, 900.0, "results/rs485_x_Z")
    assert txt.startswith("✅")
    assert "PASS" in txt
    assert "3/3 PASS · 0 FAIL" in txt
    assert "NDR6_Vcm+7V" in txt
    assert "rs485_x_Z.{json,md,csv}" in txt


def test_format_summary_lists_failures():
    results = [
        dict(name="sanity@307200", verdict="PASS", reasons=[]),
        dict(name="failsafe_paused@9600", verdict="FAIL",
             reasons=["FER 100.0000% > llindar 0.0000%", "96B de brossa"]),
    ]
    txt = format_summary(_meta(), results, 1, 900.0, "b")
    assert txt.startswith("❌")
    assert "1/2 PASS · 1 FAIL" in txt
    assert "✗ failsafe_paused@9600 — FER 100.0000% > llindar 0.0000%" in txt


def test_format_summary_marks_aborted():
    txt = format_summary(_meta(aborted=True), [], 0, 10.0, "b")
    assert "INTERROMPUT" in txt and txt.startswith("🟠")


def test_format_summary_truncates_long_fail_lists():
    results = [dict(name=f"t{i}@1", verdict="FAIL", reasons=["x"])
               for i in range(15)]
    txt = format_summary(_meta(), results, 15, 1.0, "b")
    assert "…i 5 més" in txt


def test_format_fail_is_short_and_named():
    res = dict(name="turnaround_gap0@921600", verdict="FAIL",
               reasons=["FER 10.43%", "299B de brossa", "x", "y"])
    txt = format_fail(res, _meta())
    assert "⚠️ FAIL" in txt
    assert "turnaround_gap0@921600" in txt
    assert "FER 10.43%" in txt
    assert "y" not in txt                 # nomes els 3 primers motius


def test_format_start_has_interface_title():
    txt = format_start(_meta(interface="rs422"), 18)
    assert "RS-422" in txt
    assert "18 tests" in txt


# ---------------------------------------------------------------- from_env
def test_from_env_needs_both_vars():
    assert TelegramNotifier.from_env({}) is None
    assert TelegramNotifier.from_env({ENV_TOKEN: "t"}) is None
    assert TelegramNotifier.from_env({ENV_CHAT: "c"}) is None
    n = TelegramNotifier.from_env({ENV_TOKEN: "t", ENV_CHAT: "c"})
    assert n is not None and n.token == "t" and n.chat_ids == ["c"]


def test_from_env_blank_chat_is_none():
    assert TelegramNotifier.from_env({ENV_TOKEN: "t", ENV_CHAT: "   "}) is None


def test_build_notifier_off_and_auto(monkeypatch):
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    monkeypatch.delenv(ENV_CHAT, raising=False)
    assert build_notifier(types.SimpleNamespace(notify="off")) is None
    assert build_notifier(types.SimpleNamespace(notify="auto")) is None
    monkeypatch.setenv(ENV_TOKEN, "t")
    monkeypatch.setenv(ENV_CHAT, "c")
    assert build_notifier(types.SimpleNamespace(notify="auto")) is not None
    assert build_notifier(types.SimpleNamespace(notify="off")) is None


# -------------------------------------------------------- transport robust
def _fake_urlopen(captured, *, ok=True, boom=None):
    def _open(req, timeout=None):
        if boom is not None:
            raise boom
        captured["url"] = req.full_url if hasattr(req, "full_url") else req
        captured["data"] = getattr(req, "data", None)
        return io.BytesIO(json.dumps({"ok": ok,
                                      "description": None if ok else "nope"}
                                     ).encode())
    return _open


def test_send_success(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(notify.urlrequest, "urlopen", _fake_urlopen(captured))
    assert TelegramNotifier("TOK", "CHAT").send("hola") is True
    assert "botTOK/sendMessage" in captured["url"]
    assert b"chat_id=CHAT" in captured["data"]
    assert b"hola" in captured["data"]


def test_send_telegram_rejects(monkeypatch):
    monkeypatch.setattr(notify.urlrequest, "urlopen",
                        _fake_urlopen({}, ok=False))
    assert TelegramNotifier("t", "c").send("x") is False


def test_send_never_raises_on_network_error(monkeypatch):
    monkeypatch.setattr(notify.urlrequest, "urlopen",
                        _fake_urlopen({}, boom=OSError("xarxa caiguda")))
    # el punt clau: una corrida de 3h no pot petar perque no hi ha xarxa
    assert TelegramNotifier("t", "c").send("x") is False


# ------------------------------------------------- diversos destinataris
def test_parse_chat_ids_separators_and_dedupe():
    from rs485_labtest.notify import parse_chat_ids
    assert parse_chat_ids("123, 456 789 123") == ["123", "456", "789"]
    assert parse_chat_ids("  ") == []


def test_from_env_parses_multiple_chat_ids():
    n = TelegramNotifier.from_env({ENV_TOKEN: "t", ENV_CHAT: "111,222"})
    assert n is not None and n.chat_ids == ["111", "222"]


def test_send_delivers_to_every_recipient(monkeypatch):
    sent: list = []

    def _open(req, timeout=None):
        sent.append(getattr(req, "data", b""))
        return io.BytesIO(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(notify.urlrequest, "urlopen", _open)
    assert TelegramNotifier("t", "111,222,333").send("hola") is True
    assert len(sent) == 3
    joined = b"".join(sent)
    assert b"chat_id=111" in joined
    assert b"chat_id=222" in joined
    assert b"chat_id=333" in joined


def test_send_one_bad_recipient_does_not_block_others(monkeypatch):
    # 222 es rebutjat (p.ex. no ha premut Start); 111 i 333 han de rebre igual
    reached: list = []

    def _open(req, timeout=None):
        data = getattr(req, "data", b"")
        reached.append(data)
        ok = b"chat_id=222" not in data
        return io.BytesIO(json.dumps(
            {"ok": ok, "description": None if ok else "chat not found"}).encode())

    monkeypatch.setattr(notify.urlrequest, "urlopen", _open)
    n = TelegramNotifier("t", "111,222,333")
    assert n.send("x") is False              # no tots han anat be
    assert len(reached) == 3                  # pero s'ha intentat a tots tres
    assert n._send_one("111", "x") is True    # els bons segueixen funcionant


# ------------------------------------------------------ monitor integracio
class _RecordingNotifier:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def test_telegram_monitor_alerts_on_fail_and_summarises():
    n = _RecordingNotifier()
    m = TelegramMonitor(n)
    m.battery_start(_meta(), 2, "b")
    m.test_start(1, 2, "sanity@307200", "traffic")
    m.test_end(dict(name="sanity@307200", verdict="PASS", reasons=[]))
    m.test_end(dict(name="failsafe_paused@9600", verdict="FAIL",
                    reasons=["FER 100%"]))
    m.battery_end([{"verdict": "PASS"}, {"verdict": "FAIL",
                                         "name": "failsafe_paused@9600",
                                         "reasons": ["FER 100%"]}], 1, 900.0, "b")
    assert any(t.startswith("🚀") for t in n.sent)      # inici
    assert any("⚠️ FAIL" in t for t in n.sent)          # alerta del fail
    assert any(t.startswith("❌") for t in n.sent)       # resum
    # el PASS no genera alerta
    assert sum("⚠️ FAIL" in t for t in n.sent) == 1


def test_telegram_monitor_wants_no_progress():
    assert TelegramMonitor(_RecordingNotifier()).wants_progress is False


def test_multimonitor_fans_out_and_ors_progress():
    class Rec:
        wants_progress = True

        def __init__(self):
            self.calls = []

        def battery_start(self, *a):
            self.calls.append("start")

        def baud_change(self, *a): ...
        def test_start(self, *a): ...
        def test_progress(self, *a):
            self.calls.append("prog")

        def test_end(self, *a):
            self.calls.append("end")

        def note(self, *a): ...
        def battery_end(self, *a):
            self.calls.append("done")

    a, b = Rec(), Rec()
    b.wants_progress = False
    multi = MultiMonitor([a, b])
    assert multi.wants_progress is True        # OR: algun en vol
    multi.battery_start({}, 1, "x")
    multi.test_progress({})
    multi.test_end({})
    multi.battery_end([], 0, 1.0, "x")
    assert a.calls == b.calls == ["start", "prog", "end", "done"]

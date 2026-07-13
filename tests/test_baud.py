"""Tests de baud rates alts i no estandard (p.ex. 307200) i del seu maneig."""

import struct
import types

import pytest

import rs485_labtest.transport as transport
from fakes import FakeTransport, PerfectDUT
from rs485_labtest.battery import battery_plan
from rs485_labtest.engine import TestEngine
from rs485_labtest.protocol import T_CMD_BAUD, FrameReader
from rs485_labtest.transport import BaudNotSupported, open_port


# --------------------------------------------------- el valor passa pel pipeline
def test_cmd_baud_payload_roundtrips_nonstandard_value():
    # 307200 (no estandard) ha de cabre net al camp uint32 de CMD_BAUD
    payload = struct.pack("<I", 307200)
    assert struct.unpack("<I", payload)[0] == 307200


def test_battery_plan_accepts_high_and_nonstandard_bauds():
    plan = battery_plan("smoke", [307200, 2000000], 115200)
    names = [n for n, _, _ in plan]
    assert "__setbaud__307200" in names
    assert "turnaround_gap0@307200" in names
    assert "idle_monitor@2000000" in names


# ------------------------------------------------- canvi remot a baud no estandard
def test_set_remote_baud_to_nonstandard_value():
    tp = FakeTransport(PerfectDUT())
    eng = TestEngine(tp, seed=1)
    assert eng.set_remote_baud(307200) is True
    assert tp.baudrate == 307200


def test_engine_reports_running_baud_in_results():
    tp = FakeTransport(PerfectDUT(), baudrate=307200)
    eng = TestEngine(tp, seed=1)
    res = eng.run_traffic_test("sanity", "counter", 8, 0, duration_s=0.2)
    assert res["baud"] == 307200


# ------------------------------------------- sostre de l'adaptador: fallo net
def test_set_remote_baud_above_ceiling_returns_false_not_crash():
    # El slave accepta el CMD_BAUD, pero el nostre extrem no pot amb aquest baud:
    # ha de retornar False (aquell baud es salta) sense tombar la bateria.
    tp = FakeTransport(PerfectDUT(), max_baud=1_000_000)
    eng = TestEngine(tp, seed=1)
    assert eng.set_remote_baud(3_000_000) is False


# ------------------------------------------------ open_port tradueix l'error
def _fake_serial_module(raise_exc):
    ns = types.SimpleNamespace(
        PARITY_NONE="N", PARITY_EVEN="E", PARITY_ODD="O",
        STOPBITS_ONE=1, STOPBITS_ONE_POINT_FIVE=1.5, STOPBITS_TWO=2,
        SerialTimeoutException=transport.WriteTimeout)

    def _serial(**kwargs):
        raise raise_exc
    ns.Serial = _serial
    return ns


def test_open_port_translates_baud_valueerror(monkeypatch):
    monkeypatch.setattr(transport, "serial",
                        _fake_serial_module(ValueError("invalid baudrate")))
    with pytest.raises(BaudNotSupported) as ei:
        open_port("/dev/ttyUSB0", 5_000_000)
    assert "5000000" in str(ei.value)


def test_open_port_non_baud_oserror_propagates(monkeypatch):
    monkeypatch.setattr(transport, "serial",
                        _fake_serial_module(OSError("No such file or directory")))
    with pytest.raises(OSError):
        open_port("/dev/ttyUSB9", 115200)


def test_serial_transport_baud_setter_translates_error():
    class _Ser:
        baudrate = 115200

        def __setattr__(self, k, v):
            if k == "baudrate":
                raise OSError("device busy")
            object.__setattr__(self, k, v)

    st = transport.SerialTransport.__new__(transport.SerialTransport)
    st._ser = _Ser()
    with pytest.raises(BaudNotSupported):
        st.baudrate = 921600


def test_slave_obeys_nonstandard_remote_baud():
    # El costat slave: en rebre CMD_BAUD a 307200, ha de fixar-lo al seu port.
    from rs485_labtest.slave import run_slave

    class OneShot(FakeTransport):
        """Slave que atura el bucle despres del primer canvi de baud."""

        def __init__(self):
            super().__init__(PerfectDUT())
            self._cmds = FrameReader()

        def read(self, size=1):
            data = super().read(size)
            if self.baudrate == 307200:
                raise KeyboardInterrupt
            return data

    tp = OneShot()
    from rs485_labtest.protocol import build_frame
    tp.rx.extend(build_frame(T_CMD_BAUD, 0, struct.pack("<I", 307200)))
    run_slave("fake", 115200, transport=tp)
    assert tp.baudrate == 307200

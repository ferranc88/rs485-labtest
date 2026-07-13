"""Tests del protocol de trama: CRC, construccio i parser resincronitzable."""

from rs485_labtest.protocol import (
    HDR,
    HDR_LEN,
    MAX_PAYLOAD,
    SOF,
    T_ACK,
    T_CMD_BAUD,
    T_DATA,
    FrameReader,
    build_frame,
    crc16,
)


def test_crc16_check_value():
    # Vector de referencia del CRC-16/CCITT-FALSE
    assert crc16(b"123456789") == 0x29B1


def test_crc16_empty():
    assert crc16(b"") == 0xFFFF


def test_build_frame_layout():
    frame = build_frame(T_DATA, 7, b"ab")
    assert frame[0] == SOF
    assert len(frame) == HDR_LEN + 2 + 2
    _, ftype, seq, length = HDR.unpack(frame[:HDR_LEN])
    assert (ftype, seq, length) == (T_DATA, 7, 2)


def test_roundtrip_single_frame():
    reader = FrameReader()
    frames = reader.feed(build_frame(T_DATA, 42, b"hola"))
    assert frames == [(T_DATA, 42, b"hola")]
    assert reader.junk == 0
    assert reader.crc_errors == 0


def test_roundtrip_all_types_and_empty_payload():
    reader = FrameReader()
    data = build_frame(T_DATA, 1) + build_frame(T_CMD_BAUD, 2, b"\x00\xc2\x01\x00") \
        + build_frame(T_ACK, 3, b"x")
    frames = reader.feed(data)
    assert [f[0] for f in frames] == [T_DATA, T_CMD_BAUD, T_ACK]
    assert reader.junk == 0


def test_fragmented_feed_byte_by_byte():
    reader = FrameReader()
    frame = build_frame(T_DATA, 5, b"fragmentat")
    collected = []
    for i in range(len(frame)):
        collected += reader.feed(frame[i:i + 1])
    assert collected == [(T_DATA, 5, b"fragmentat")]
    assert reader.junk == 0


def test_junk_before_frame_is_counted():
    reader = FrameReader()
    garbage = b"\x01\x02\x03\x04"
    frames = reader.feed(garbage + build_frame(T_DATA, 9, b"z"))
    assert frames == [(T_DATA, 9, b"z")]
    assert reader.junk == len(garbage)


def test_junk_without_sof_clears_buffer():
    reader = FrameReader()
    assert reader.feed(b"\x00\x01\x02") == []
    assert reader.junk == 3
    assert len(reader.buf) == 0


def test_crc_error_resync_recovers_next_frame():
    reader = FrameReader()
    bad = bytearray(build_frame(T_DATA, 1, b"abc"))
    bad[-1] ^= 0xFF                      # CRC corrupte
    frames = reader.feed(bytes(bad) + build_frame(T_DATA, 2, b"xyz"))
    assert [(f[0], f[1]) for f in frames] == [(T_DATA, 2)]
    assert reader.crc_errors == 1
    assert reader.junk > 0


def test_oversize_length_treated_as_junk():
    reader = FrameReader()
    fake_hdr = HDR.pack(SOF, T_DATA, 1, MAX_PAYLOAD + 1)
    frames = reader.feed(fake_hdr + b"\x00" * 16)
    assert frames == []
    assert reader.junk > 0


def test_bad_type_treated_as_junk():
    reader = FrameReader()
    fake_hdr = HDR.pack(SOF, 0x7F, 1, 4)
    frames = reader.feed(fake_hdr + b"\x00" * 16)
    assert frames == []
    assert reader.junk > 0

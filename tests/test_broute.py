"""Tests for pure functions in j11_meter.broute — no serial hardware required."""

from __future__ import annotations

import struct

import pytest

from j11_meter.broute import (
    REQ_UNIQUE,
    RESP_UNIQUE,
    build_echonet_get_frame,
    build_request,
    checksum16_header,
    checksum16_sum_bytes,
    mac_to_j11_link_local_ipv6,
    parse_echonet_props,
    parse_frame,
    validate_broute,
)


# ── checksum16_sum_bytes ──────────────────────────────────────────────────────


def test_checksum16_sum_bytes_zero():
    assert checksum16_sum_bytes(b"\x00") == 0


def test_checksum16_sum_bytes_small():
    assert checksum16_sum_bytes(b"\x01\x02") == 3


def test_checksum16_sum_bytes_overflow():
    assert checksum16_sum_bytes(b"\xff\xff\x01") == 0x01FF


# ── checksum16_header ─────────────────────────────────────────────────────────


def test_checksum16_header_returns_int():
    result = checksum16_header(REQ_UNIQUE, 0x006B, 4)
    assert isinstance(result, int)


def test_checksum16_header_deterministic():
    a = checksum16_header(REQ_UNIQUE, 0x006B, 4)
    b = checksum16_header(REQ_UNIQUE, 0x006B, 4)
    assert a == b


# ── build_request ─────────────────────────────────────────────────────────────


def test_build_request_minimal():
    req = build_request(0x006B)
    assert len(req) == 12  # 8 header + 4 (dcs=2 + data empty, msg_len=4 → 8+4=12)


def test_build_request_with_data():
    req = build_request(0x006B, b"\xaa\xbb")
    assert len(req) == 14  # 12 + 2 data bytes


def test_build_request_starts_with_unique():
    req = build_request(0x006B)
    unique = struct.unpack(">I", req[:4])[0]
    assert unique == REQ_UNIQUE


# ── parse_frame ───────────────────────────────────────────────────────────────


def test_parse_frame_round_trip():
    req = build_request(0x006B)
    frame = parse_frame(req)
    assert frame.unique == REQ_UNIQUE
    assert frame.cmd == 0x006B


def test_parse_frame_with_data():
    data = b"\xde\xad"
    req = build_request(0x0005, data)
    frame = parse_frame(req)
    assert frame.data == data


def test_parse_frame_short():
    with pytest.raises(ValueError, match="short frame"):
        parse_frame(b"\x00\x01\x02")


def test_parse_frame_length_mismatch():
    req = build_request(0x006B)
    with pytest.raises(ValueError, match="length mismatch"):
        parse_frame(req + b"\x00")


# ── parse_echonet_props ───────────────────────────────────────────────────────


def test_parse_echonet_props_positive_power():
    data = bytes(
        [
            0x10,
            0x81,
            0x00,
            0x01,
            0x05,
            0xFF,
            0x01,
            0x02,
            0x88,
            0x01,
            0x62,
            0x01,
            0xE7,
            0x04,
            0x00,
            0x00,
            0x02,
            0x7C,
        ]
    )
    result = parse_echonet_props(data)
    assert result is not None
    power = int.from_bytes(result["props"][0xE7], "big", signed=True)
    assert power == 636


def test_parse_echonet_props_negative_power():
    data = bytes(
        [
            0x10,
            0x81,
            0x00,
            0x01,
            0x05,
            0xFF,
            0x01,
            0x02,
            0x88,
            0x01,
            0x62,
            0x01,
            0xE7,
            0x04,
            0xFF,
            0xFF,
            0xFE,
            0x0C,
        ]
    )
    result = parse_echonet_props(data)
    assert result is not None
    power = int.from_bytes(result["props"][0xE7], "big", signed=True)
    assert power == -500


def test_parse_echonet_props_current():
    data = bytes(
        [
            0x10,
            0x81,
            0x00,
            0x01,
            0x05,
            0xFF,
            0x01,
            0x02,
            0x88,
            0x01,
            0x62,
            0x01,
            0xE8,
            0x04,
            0x00,
            0x3C,
            0x00,
            0x0A,
        ]
    )
    result = parse_echonet_props(data)
    assert result is not None
    r = int.from_bytes(result["props"][0xE8][0:2], "big") / 10.0
    t = int.from_bytes(result["props"][0xE8][2:4], "big") / 10.0
    assert r == 6.0
    assert t == 1.0


def test_parse_echonet_props_empty():
    assert parse_echonet_props(b"") is None


def test_parse_echonet_props_short():
    assert parse_echonet_props(b"\x10\x81\x00") is None


def test_parse_echonet_props_wrong_header():
    assert parse_echonet_props(b"\x10\x80" + b"\x00" * 10) is None


# ── build_echonet_get_frame ───────────────────────────────────────────────────


def test_build_echonet_get_frame():
    frame = build_echonet_get_frame(1, [0xE7, 0xE8])
    assert frame[0:2] == b"\x10\x81"  # EHD
    assert frame[4:7] == b"\x05\xff\x01"  # SEOJ
    assert frame[7:10] == b"\x02\x88\x01"  # DEOJ
    assert frame[10] == 0x62  # ESV Get
    assert frame[11] == 2  # OPC


def test_build_echonet_get_frame_single_epc():
    frame = build_echonet_get_frame(1, [0xE7])
    assert frame[11] == 1  # OPC = 1


# ── validate_broute ───────────────────────────────────────────────────────────


def test_validate_broute_valid():
    validate_broute("0123456789abcdef0123456789ABCDEF", "ABCDEFGHIJKL")


def test_validate_broute_invalid_rbid():
    with pytest.raises(ValueError, match="RBID"):
        validate_broute("short", "ABCDEFGHIJKL")


def test_validate_broute_invalid_password():
    with pytest.raises(ValueError, match="Password"):
        validate_broute("0123456789abcdef0123456789ABCDEF", "short")


def test_validate_broute_rbid_non_hex():
    with pytest.raises(ValueError, match="RBID"):
        validate_broute("0123456789abcdef0123456789XXXXXX", "ABCDEFGHIJKL")


# ── mac_to_j11_link_local_ipv6 ────────────────────────────────────────────────


def test_mac_to_ipv6():
    mac = bytes.fromhex("0123456789ABCDEF")
    ipv6 = mac_to_j11_link_local_ipv6(mac)
    assert ipv6[0:8] == bytes.fromhex("fe80000000000000")
    assert ipv6[8:16] == bytes([0x01 ^ 0x02, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF])


def test_mac_to_ipv6_wrong_length():
    with pytest.raises(ValueError, match="8-byte"):
        mac_to_j11_link_local_ipv6(b"\x00" * 7)


def test_mac_to_ipv6_full_length():
    mac = bytes.fromhex("0123456789ABCDEF")
    ipv6 = mac_to_j11_link_local_ipv6(mac)
    assert len(ipv6) == 16

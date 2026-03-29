"""J11 B-route protocol implementation for RS-WSUHA-J11 smart meter module."""

from __future__ import annotations

import ipaddress
import logging
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import serial

logger = logging.getLogger(__name__)

# ── Unique codes ──────────────────────────────────────────────────────────────
REQ_UNIQUE = 0xD0EA83FC
RESP_UNIQUE = 0xD0F9EE5D

# ── Command IDs ───────────────────────────────────────────────────────────────
CMD_GET_STATUS = 0x0001
CMD_OPEN_UDP = 0x0005
CMD_SEND_UDP = 0x0008
CMD_EXEC_ACTIVE_SCAN = 0x0051
CMD_START_BROUTE = 0x0053
CMD_SET_BROUTE_PANA = 0x0054
CMD_START_BROUTE_PANA = 0x0056
CMD_SET_INITIAL = 0x005F
CMD_GET_VERSION = 0x006B
CMD_GET_INITIAL = 0x0107
CMD_END_BROUTE_PANA = 0x0057
CMD_STOP_BROUTE = 0x0058

# ── Response command IDs ─────────────────────────────────────────────────────
RESP_GET_STATUS = 0x2001
RESP_OPEN_UDP = 0x2005
RESP_SEND_UDP = 0x2008
RESP_EXEC_ACTIVE_SCAN = 0x2051
RESP_START_BROUTE = 0x2053
RESP_SET_BROUTE_PANA = 0x2054
RESP_START_BROUTE_PANA = 0x2056
RESP_SET_INITIAL = 0x205F
RESP_GET_VERSION = 0x206B
RESP_GET_INITIAL = 0x2107
RESP_END_BROUTE_PANA = 0x2057
RESP_STOP_BROUTE = 0x2058

# ── Notification command IDs ─────────────────────────────────────────────────
NOTIFY_ACTIVE_SCAN = 0x4051
NOTIFY_RECV_UDP = 0x6018
NOTIFY_PANA_RESULT = 0x6028


# ── Dataclass ─────────────────────────────────────────────────────────────────
@dataclass
class J11Frame:
    unique: int
    cmd: int
    msg_len: int
    header_checksum: int
    data_checksum: int
    data: bytes


# ── Pure functions ────────────────────────────────────────────────────────────
def checksum16_sum_bytes(data: bytes) -> int:
    return sum(data) & 0xFFFF


def checksum16_header(unique: int, cmd: int, msg_len: int) -> int:
    return checksum16_sum_bytes(struct.pack(">IHH", unique, cmd, msg_len))


def build_request(cmd: int, data: bytes = b"") -> bytes:
    msg_len = 4 + len(data)
    hcs = checksum16_header(REQ_UNIQUE, cmd, msg_len)
    dcs = checksum16_sum_bytes(data)
    req = (
        struct.pack(">IHHH", REQ_UNIQUE, cmd, msg_len, hcs)
        + struct.pack(">H", dcs)
        + data
    )
    logger.debug("build_request cmd=0x%04X", cmd)
    logger.debug("send_cmd req=%s", req.hex())
    return req


def parse_frame(raw: bytes) -> J11Frame:
    if len(raw) < 12:
        raise ValueError("short frame")
    unique, cmd, msg_len, hcs = struct.unpack(">IHHH", raw[:10])
    expected_total = 8 + msg_len
    if len(raw) != expected_total:
        raise ValueError(
            f"length mismatch: got {len(raw)} bytes, expected {expected_total}"
        )
    dcs = struct.unpack(">H", raw[10:12])[0]
    data = raw[12:]
    return J11Frame(unique, cmd, msg_len, hcs, dcs, data)


def read_exact(ser: serial.Serial, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            raise TimeoutError("serial read timeout")
        buf += chunk
    return buf


def read_frame(ser: serial.Serial) -> J11Frame:
    header = read_exact(ser, 12)
    unique, cmd, msg_len, hcs = struct.unpack(">IHHH", header[:10])
    remaining = msg_len - 4
    if remaining < 0:
        raise ValueError(f"invalid msg_len: {msg_len}")
    rest = read_exact(ser, remaining)
    raw = header + rest

    logger.debug("raw frame=%s", raw.hex())

    frame = parse_frame(raw)

    expected_hcs = checksum16_header(frame.unique, frame.cmd, frame.msg_len)
    if frame.header_checksum != expected_hcs:
        raise ValueError(
            f"header checksum mismatch: got 0x{frame.header_checksum:04X}, "
            f"expected 0x{expected_hcs:04X}"
        )

    expected_dcs = checksum16_sum_bytes(frame.data)
    if frame.data_checksum != expected_dcs:
        raise ValueError(
            f"data checksum mismatch: got 0x{frame.data_checksum:04X}, "
            f"expected 0x{expected_dcs:04X}"
        )

    return frame


def send_cmd(ser: serial.Serial, cmd: int, data: bytes = b"") -> J11Frame:
    req = build_request(cmd, data)
    ser.write(req)
    ser.flush()
    return read_frame(ser)


def ensure_response(frame: J11Frame, expected_cmd: int) -> None:
    if frame.unique != RESP_UNIQUE:
        raise RuntimeError(f"unexpected unique code: 0x{frame.unique:08X}")
    if frame.cmd != expected_cmd:
        raise RuntimeError(
            f"unexpected response cmd: 0x{frame.cmd:04X}, expected 0x{expected_cmd:04X}"
        )


def expect_success(frame: J11Frame, expected_cmd: int) -> bytes:
    ensure_response(frame, expected_cmd)
    if len(frame.data) < 1:
        raise RuntimeError("response data too short")
    result = frame.data[0]
    if result != 0x01:
        raise RuntimeError(f"module returned error result: 0x{result:02X}")
    return frame.data


def validate_broute(rbid: str, password: str) -> None:
    if len(rbid) != 32 or any(c not in "0123456789abcdefABCDEF" for c in rbid):
        raise ValueError("RBID must be a 32-character hex string")
    if len(password) != 12:
        raise ValueError("Password must be exactly 12 characters")


def parse_echonet_props(echonet: bytes) -> dict | None:
    if len(echonet) < 12:
        return None
    if echonet[0:2] != b"\x10\x81":
        return None

    esv = echonet[10]
    opc = echonet[11]
    i = 12
    props: dict[int, bytes] = {}

    for _ in range(opc):
        if i + 2 > len(echonet):
            return None
        epc = echonet[i]
        pdc = echonet[i + 1]
        i += 2
        if i + pdc > len(echonet):
            return None
        edt = echonet[i : i + pdc]
        i += pdc
        props[epc] = edt

    return {
        "tid": int.from_bytes(echonet[2:4], "big"),
        "seoj": echonet[4:7],
        "deoj": echonet[7:10],
        "esv": esv,
        "props": props,
    }


def build_echonet_get_frame(tid: int, epcs: list[int]) -> bytes:
    payload = bytearray()
    payload += b"\x10\x81"
    payload += tid.to_bytes(2, "big")
    payload += b"\x05\xff\x01"
    payload += b"\x02\x88\x01"
    payload += b"\x62"
    payload += bytes([len(epcs)])
    for epc in epcs:
        payload += bytes([epc, 0x00])
    return bytes(payload)


def mac_to_j11_link_local_ipv6(mac: bytes) -> bytes:
    if len(mac) != 8:
        raise ValueError("expected 8-byte MAC")
    iid = bytearray(mac)
    iid[0] ^= 0x02
    return bytes.fromhex("fe80000000000000") + bytes(iid)


def ipv6_text(addr: bytes) -> str:
    return str(ipaddress.IPv6Address(addr))


# ── Internal helpers (state persistence) ──────────────────────────────────────


def _load_saved_channel(state_dir: Path) -> int | None:
    path = state_dir / ".j11_broute_channel"
    if path.exists():
        return int(path.read_text().strip(), 16)
    return None


def _save_channel(state_dir: Path, ch: int) -> None:
    (state_dir / ".j11_broute_channel").write_text(f"{ch:02X}\n")


def _load_saved_mac(state_dir: Path) -> bytes | None:
    path = state_dir / ".j11_broute_mac"
    if path.exists():
        s = path.read_text().strip()
        if len(s) == 16:
            return bytes.fromhex(s)
    return None


def _save_mac(state_dir: Path, mac: bytes) -> None:
    (state_dir / ".j11_broute_mac").write_text(mac.hex() + "\n")


# ── Internal protocol helpers ─────────────────────────────────────────────────


def _get_version(ser: serial.Serial) -> bytes:
    resp = send_cmd(ser, CMD_GET_VERSION, b"")
    ensure_response(resp, RESP_GET_VERSION)
    logger.info("version resp cmd=0x%04X data=%s", resp.cmd, resp.data.hex())
    return resp.data


def _get_status(ser: serial.Serial) -> tuple[int, int, int, bytes]:
    resp = send_cmd(ser, CMD_GET_STATUS, b"")
    data = expect_success(resp, RESP_GET_STATUS)
    logger.debug("status raw=%s", data.hex())
    if len(data) < 4:
        raise RuntimeError(f"short status response: {data.hex()}")
    return data[1], data[2], data[3], data


def _get_initial(ser: serial.Serial) -> tuple[int, int, int, int]:
    resp = send_cmd(ser, CMD_GET_INITIAL, b"")
    data = expect_success(resp, RESP_GET_INITIAL)
    if len(data) < 5:
        raise RuntimeError(f"initial response too short: {data.hex()}")
    mode, sleep, channel, tx_power = data[1], data[2], data[3], data[4]
    logger.info(
        "initial mode=0x%02X sleep=0x%02X channel=0x%02X tx=0x%02X",
        mode,
        sleep,
        channel,
        tx_power,
    )
    return mode, sleep, channel, tx_power


def _set_initial_dual(
    ser: serial.Serial,
    channel: int,
    sleep: int = 0x00,
    tx_power: int = 0x00,
) -> None:
    payload = bytes([0x05, sleep, channel, tx_power])
    resp = send_cmd(ser, CMD_SET_INITIAL, payload)
    expect_success(resp, RESP_SET_INITIAL)
    logger.info("initial set ok: payload=%s", payload.hex())


def _active_scan_collect(
    ser: serial.Serial,
    pairing_id_ascii8: str,
    channel_mask: int = 0x0003FFF0,
    duration: int = 6,
    timeout: float = 120.0,
) -> list[int]:
    payload = (
        bytes([duration])
        + channel_mask.to_bytes(4, "big")
        + b"\x01"
        + pairing_id_ascii8.encode("ascii")
    )

    req = build_request(CMD_EXEC_ACTIVE_SCAN, payload)
    ser.write(req)
    ser.flush()

    found_channels: list[int] = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        frame = read_frame(ser)

        if frame.unique != RESP_UNIQUE:
            continue

        if frame.cmd == NOTIFY_ACTIVE_SCAN:
            data = frame.data
            logger.info("active scan notify raw=%s", data.hex())
            if len(data) >= 2:
                scan_result = data[0]
                ch = data[1]
                if scan_result == 0x00:
                    logger.info("responded on channel 0x%02X", ch)
                    found_channels.append(ch)
                elif scan_result == 0x01:
                    logger.debug("no response on channel 0x%02X", ch)
                else:
                    logger.warning(
                        "unknown scan result 0x%02X on channel 0x%02X",
                        scan_result,
                        ch,
                    )
            continue

        if frame.cmd == RESP_EXEC_ACTIVE_SCAN:
            _ = expect_success(frame, RESP_EXEC_ACTIVE_SCAN)
            logger.info("active scan complete: raw=%s", frame.data.hex())
            return sorted(set(found_channels))

        logger.debug("ignore cmd=0x%04X data=%s", frame.cmd, frame.data.hex())

    raise TimeoutError("timed out waiting for active scan completion")


def _open_udp_3610(ser: serial.Serial) -> None:
    resp = send_cmd(ser, CMD_OPEN_UDP, (3610).to_bytes(2, "big"))
    ensure_response(resp, RESP_OPEN_UDP)

    if len(resp.data) < 1:
        raise RuntimeError("response data too short")

    result = resp.data[0]
    if result == 0x01:
        logger.info("UDP 3610 open ok")
        return

    # 0x0A = already open
    if result == 0x0A:
        logger.info("UDP 3610 is already open")
        return

    raise RuntimeError(f"module returned error result: 0x{result:02X}")


def _set_broute_credentials(
    ser: serial.Serial,
    rbid: str,
    password: str,
) -> None:
    payload = rbid.encode("ascii") + password.encode("ascii")
    resp = send_cmd(ser, CMD_SET_BROUTE_PANA, payload)
    expect_success(resp, RESP_SET_BROUTE_PANA)
    logger.info("B-route credentials accepted")


def _start_broute(ser: serial.Serial) -> bytes:
    resp = send_cmd(ser, CMD_START_BROUTE, b"")
    data = expect_success(resp, RESP_START_BROUTE)
    logger.info("B-route started: raw=%s", data.hex())
    return data


def _start_broute_with_retry(
    ser: serial.Serial,
    rbid: str,
    state_dir: Path,
) -> bytes:
    try:
        return _start_broute(ser)
    except RuntimeError as e:
        msg = str(e)
        if "0x0E" not in msg:
            raise

        logger.info(
            "B-route start failed with 0x0E. Re-scanning channel and retrying once..."
        )
        _ensure_channel_ready(ser, rbid, state_dir, force_scan=True)
        return _start_broute(ser)


def _start_pana(ser: serial.Serial) -> None:
    resp = send_cmd(ser, CMD_START_BROUTE_PANA, b"")
    expect_success(resp, RESP_START_BROUTE_PANA)
    logger.info("PANA start command accepted")


def _wait_for_pana_success(
    ser: serial.Serial,
    timeout: float = 60.0,
) -> bytes:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            frame = read_frame(ser)
        except TimeoutError:
            continue

        if frame.unique != RESP_UNIQUE:
            continue
        if frame.cmd != NOTIFY_PANA_RESULT:
            logger.debug(
                "ignore notify cmd=0x%04X data=%s",
                frame.cmd,
                frame.data.hex(),
            )
            continue

        logger.info("pana notify raw=%s", frame.data.hex())
        if len(frame.data) < 9:
            raise RuntimeError(f"short 0x6028 data: {frame.data.hex()}")

        result = frame.data[0]
        mac = frame.data[1:9]
        if result != 0x01:
            raise RuntimeError(f"PANA failed: result=0x{result:02X}")
        return mac

    raise TimeoutError("timed out waiting for PANA result 0x6028")


def _send_udp_echonet(
    ser: serial.Serial,
    meter_ipv6: bytes,
    echonet_payload: bytes,
) -> int:
    src_port = 0x0E1A
    dst_port = 0x0E1A

    payload = (
        meter_ipv6
        + src_port.to_bytes(2, "big")
        + dst_port.to_bytes(2, "big")
        + len(echonet_payload).to_bytes(2, "big")
        + echonet_payload
    )

    resp = send_cmd(ser, CMD_SEND_UDP, payload)
    ensure_response(resp, RESP_SEND_UDP)
    if len(resp.data) < 2:
        raise RuntimeError(f"short 0x2008 response: {resp.data.hex()}")

    accept = resp.data[0]
    send_result = resp.data[1]
    if accept != 0x01:
        raise RuntimeError(f"0x0008 rejected: 0x{accept:02X}")

    logger.info("udp send accepted, send_result=0x%02X", send_result)
    return send_result


def _wait_for_udp_recv(
    ser: serial.Serial,
    timeout: float = 30.0,
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            frame = read_frame(ser)
        except TimeoutError:
            continue

        if frame.unique != RESP_UNIQUE:
            continue
        if frame.cmd != NOTIFY_RECV_UDP:
            logger.debug(
                "ignore notify cmd=0x%04X data=%s",
                frame.cmd,
                frame.data.hex(),
            )
            continue

        logger.info("udp recv notify raw=%s", frame.data.hex())

        if len(frame.data) < 27:
            continue

        echonet = frame.data[27:]
        parsed = parse_echonet_props(echonet)
        if parsed is None:
            continue

        if parsed["seoj"] != b"\x02\x88\x01":
            logger.debug(
                "ignore ECHONET SEOJ=%s DEOJ=%s ESV=0x%02X",
                parsed["seoj"].hex(),
                parsed["deoj"].hex(),
                parsed["esv"],
            )
            continue

        return parsed

    raise TimeoutError("timed out waiting for UDP receive notify 0x6018")


def _ensure_global_started(
    ser: serial.Serial,
    fallback_channel: int,
) -> None:
    global_state, _, _, _ = _get_status(ser)
    if global_state == 0x03:
        return

    logger.info(
        "Global block is not started. Restoring Dual mode on channel 0x%02X...",
        fallback_channel,
    )
    _set_initial_dual(ser, channel=fallback_channel, sleep=0x00, tx_power=0x00)
    _get_initial(ser)


def _ensure_channel_ready(
    ser: serial.Serial,
    rbid: str,
    state_dir: Path,
    force_scan: bool = False,
) -> int:
    saved_channel = _load_saved_channel(state_dir) or 0x0E

    _ensure_global_started(ser, saved_channel)

    mode, _, channel, _ = _get_initial(ser)

    if not force_scan and mode == 0x05 and channel != 0xFF:
        _save_channel(state_dir, channel)
        return channel

    pairing_id = rbid[-8:].upper()
    logger.info("Pairing ID: %s", pairing_id)

    found_channels = _active_scan_collect(
        ser,
        pairing_id_ascii8=pairing_id,
        channel_mask=0x0003FFF0,
        duration=6,
        timeout=180.0,
    )

    logger.info(
        "found_channels=%s",
        [f"0x{ch:02X}" for ch in found_channels],
    )
    if not found_channels:
        raise RuntimeError("No smart meter beacon was found on any scanned channel")

    found_channel = found_channels[0]
    logger.info("Using channel 0x%02X", found_channel)
    _set_initial_dual(ser, channel=found_channel, sleep=0x00, tx_power=0x00)
    _save_channel(state_dir, found_channel)
    _get_initial(ser)
    return found_channel


def _drain_notifications(ser: serial.Serial, seconds: float = 1.5) -> None:
    deadline = time.time() + seconds
    old_timeout = ser.timeout
    ser.timeout = 0.2
    try:
        while time.time() < deadline:
            try:
                frame = read_frame(ser)
                logger.debug(
                    "drain notify cmd=0x%04X data=%s",
                    frame.cmd,
                    frame.data.hex(),
                )
            except TimeoutError:
                pass
    finally:
        ser.timeout = old_timeout


def _end_broute_pana(ser: serial.Serial) -> None:
    resp = send_cmd(ser, CMD_END_BROUTE_PANA, b"")
    expect_success(resp, RESP_END_BROUTE_PANA)
    logger.info("B-route PANA ended")


def _stop_broute(ser: serial.Serial) -> None:
    resp = send_cmd(ser, CMD_STOP_BROUTE, b"")
    expect_success(resp, RESP_STOP_BROUTE)
    logger.info("B-route stopped")


# ── Public class ──────────────────────────────────────────────────────────────


class J11Bridge:
    """High-level interface to the RS-WSUHA-J11 B-route smart meter module."""

    def __init__(
        self,
        serial_device: str,
        rbid: str,
        password: str,
        state_dir: str,
    ) -> None:
        validate_broute(rbid, password)
        self._rbid = rbid
        self._password = password
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self._ser = serial.Serial(
            port=serial_device,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=3,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self._meter_mac: bytes | None = None

    def connect(self) -> None:
        """Full connection flow: channel scan → credentials → PANA handshake."""
        _get_version(self._ser)
        _ensure_channel_ready(self._ser, self._rbid, self._state_dir)
        _set_broute_credentials(self._ser, self._rbid, self._password)
        _start_broute_with_retry(self._ser, self._rbid, self._state_dir)
        _open_udp_3610(self._ser)
        _start_pana(self._ser)
        self._meter_mac = _wait_for_pana_success(self._ser, timeout=60.0)
        _save_mac(self._state_dir, self._meter_mac)
        logger.info("PANA success, meter MAC=%s", self._meter_mac.hex())

        _drain_notifications(self._ser, seconds=1.5)

    def reconnect(self) -> None:
        """Full reconnection: teardown then connect again."""
        try:
            _end_broute_pana(self._ser)
        except Exception:
            logger.exception("Failed to end B-route PANA during reconnect")
        try:
            _stop_broute(self._ser)
        except Exception:
            logger.exception("Failed to stop B-route during reconnect")
        self.connect()

    def read_meter(self) -> tuple[int, float, float]:
        """Read instantaneous power (W), current R (A), current T (A)."""
        if self._meter_mac is None:
            raise RuntimeError("Not connected — call connect() first")

        meter_ipv6 = mac_to_j11_link_local_ipv6(self._meter_mac)
        logger.info("meter IPv6=%s", ipv6_text(meter_ipv6))

        echonet_get = build_echonet_get_frame(1, [0xE7, 0xE8])

        parsed: dict | None = None
        for attempt in range(3):
            logger.info("Sending ECHONET Get attempt %d", attempt + 1)
            _send_udp_echonet(self._ser, meter_ipv6, echonet_get)
            try:
                parsed = _wait_for_udp_recv(self._ser, timeout=5.0)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
        else:
            raise RuntimeError("No smart meter Get_Res received")

        if parsed is None:
            raise RuntimeError("No valid ECHONET response")

        logger.info(
            "ECHONET parsed: esv=0x%02X props=%s",
            parsed["esv"],
            [hex(k) for k in parsed["props"].keys()],
        )

        if 0xE7 not in parsed["props"] or len(parsed["props"][0xE7]) != 4:
            raise RuntimeError("No valid ECHONET response: missing E7 property")
        if 0xE8 not in parsed["props"] or len(parsed["props"][0xE8]) != 4:
            raise RuntimeError("No valid ECHONET response: missing E8 property")

        power_w = int.from_bytes(parsed["props"][0xE7], "big", signed=True)
        r_raw = int.from_bytes(parsed["props"][0xE8][0:2], "big")
        t_raw = int.from_bytes(parsed["props"][0xE8][2:4], "big")
        current_r_a = r_raw * 0.1
        current_t_a = t_raw * 0.1

        return power_w, current_r_a, current_t_a

    def close(self) -> None:
        """Teardown: end PANA, stop B-route, close serial."""
        try:
            _end_broute_pana(self._ser)
        except Exception:
            logger.exception("Failed to end B-route PANA")
        try:
            _stop_broute(self._ser)
        except Exception:
            logger.exception("Failed to stop B-route")
        try:
            self._ser.close()
        except Exception:
            logger.exception("Failed to close serial port")

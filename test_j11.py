#!/usr/bin/env python3
import ipaddress
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import serial

REQ_UNIQUE = 0xD0EA83FC
RESP_UNIQUE = 0xD0F9EE5D

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

NOTIFY_ACTIVE_SCAN = 0x4051
NOTIFY_RECV_UDP = 0x6018
NOTIFY_PANA_RESULT = 0x6028

CHANNEL_FILE = Path.home() / ".j11_broute_channel"


@dataclass
class J11Frame:
    unique: int
    cmd: int
    msg_len: int
    header_checksum: int
    data_checksum: int
    data: bytes


def checksum16_sum_bytes(data: bytes) -> int:
    return sum(data) & 0xFFFF


def checksum16_header(unique: int, cmd: int, msg_len: int) -> int:
    return checksum16_sum_bytes(struct.pack(">IHH", unique, cmd, msg_len))


def build_request(cmd: int, data: bytes = b"", debug: bool = False) -> bytes:
    msg_len = 4 + len(data)
    hcs = checksum16_header(REQ_UNIQUE, cmd, msg_len)
    dcs = checksum16_sum_bytes(data)
    req = (
        struct.pack(">IHHH", REQ_UNIQUE, cmd, msg_len, hcs)
        + struct.pack(">H", dcs)
        + data
    )
    if debug:
        print(f"build_request cmd=0x{cmd:04X}")
        print(f"send_cmd req={req.hex()}")
    return req


def parse_frame(raw: bytes) -> J11Frame:
    if len(raw) < 12:
        raise ValueError("short frame")
    unique, cmd, msg_len, hcs = struct.unpack(">IHHH", raw[:10])
    expected_total = 8 + msg_len
    if len(raw) != expected_total:
        raise ValueError(f"length mismatch: got {len(raw)} bytes, expected {expected_total}")
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


def read_frame(ser: serial.Serial, debug: bool = False) -> J11Frame:
    header = read_exact(ser, 12)
    unique, cmd, msg_len, hcs = struct.unpack(">IHHH", header[:10])
    remaining = msg_len - 4
    if remaining < 0:
        raise ValueError(f"invalid msg_len: {msg_len}")
    rest = read_exact(ser, remaining)
    raw = header + rest

    if debug:
        print(f"raw frame={raw.hex()}")

    frame = parse_frame(raw)

    expected_hcs = checksum16_header(frame.unique, frame.cmd, frame.msg_len)
    if frame.header_checksum != expected_hcs:
        raise ValueError(
            f"header checksum mismatch: got 0x{frame.header_checksum:04X}, expected 0x{expected_hcs:04X}"
        )

    expected_dcs = checksum16_sum_bytes(frame.data)
    if frame.data_checksum != expected_dcs:
        raise ValueError(
            f"data checksum mismatch: got 0x{frame.data_checksum:04X}, expected 0x{expected_dcs:04X}"
        )

    return frame


def send_cmd(ser: serial.Serial, cmd: int, data: bytes = b"", debug: bool = False) -> J11Frame:
    req = build_request(cmd, data, debug=debug)
    ser.write(req)
    ser.flush()
    return read_frame(ser, debug=debug)


def ensure_response(frame: J11Frame, expected_cmd: int) -> None:
    if frame.unique != RESP_UNIQUE:
        raise RuntimeError(f"unexpected unique code: 0x{frame.unique:08X}")
    if frame.cmd != expected_cmd:
        raise RuntimeError(f"unexpected response cmd: 0x{frame.cmd:04X}, expected 0x{expected_cmd:04X}")


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


def load_saved_channel() -> int | None:
    if CHANNEL_FILE.exists():
        return int(CHANNEL_FILE.read_text().strip(), 16)
    return None


def save_channel(ch: int) -> None:
    CHANNEL_FILE.write_text(f"{ch:02X}\n")


def get_version(ser: serial.Serial, debug: bool = False) -> bytes:
    resp = send_cmd(ser, CMD_GET_VERSION, b"", debug=debug)
    ensure_response(resp, RESP_GET_VERSION)
    print(f"version resp cmd=0x{resp.cmd:04X} data={resp.data.hex()}")
    return resp.data


def get_status(ser: serial.Serial, debug: bool = False) -> tuple[int, int, int, bytes]:
    resp = send_cmd(ser, CMD_GET_STATUS, b"", debug=debug)
    data = expect_success(resp, RESP_GET_STATUS)
    print(f"status raw={data.hex()}")
    if len(data) < 4:
        raise RuntimeError(f"short status response: {data.hex()}")
    return data[1], data[2], data[3], data


def get_initial(ser: serial.Serial, debug: bool = False) -> tuple[int, int, int, int]:
    resp = send_cmd(ser, CMD_GET_INITIAL, b"", debug=debug)
    data = expect_success(resp, RESP_GET_INITIAL)
    if len(data) < 5:
        raise RuntimeError(f"initial response too short: {data.hex()}")
    mode, sleep, channel, tx_power = data[1], data[2], data[3], data[4]
    print(
        f"initial mode=0x{mode:02X} sleep=0x{sleep:02X} "
        f"channel=0x{channel:02X} tx=0x{tx_power:02X}"
    )
    return mode, sleep, channel, tx_power


def set_initial_dual(
    ser: serial.Serial,
    channel: int,
    sleep: int = 0x00,
    tx_power: int = 0x00,
    debug: bool = False,
) -> None:
    payload = bytes([0x05, sleep, channel, tx_power])
    resp = send_cmd(ser, CMD_SET_INITIAL, payload, debug=debug)
    expect_success(resp, RESP_SET_INITIAL)
    print(f"initial set ok: payload={payload.hex()}")


def active_scan_collect(
    ser: serial.Serial,
    pairing_id_ascii8: str,
    channel_mask: int = 0x0003FFF0,
    duration: int = 6,
    timeout: float = 120.0,
    debug: bool = False,
) -> list[int]:
    payload = (
        bytes([duration])
        + channel_mask.to_bytes(4, "big")
        + b"\x01"
        + pairing_id_ascii8.encode("ascii")
    )

    req = build_request(CMD_EXEC_ACTIVE_SCAN, payload, debug=debug)
    ser.write(req)
    ser.flush()

    found_channels: list[int] = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        frame = read_frame(ser, debug=debug)

        if frame.unique != RESP_UNIQUE:
            continue

        if frame.cmd == NOTIFY_ACTIVE_SCAN:
            data = frame.data
            print(f"active scan notify raw={data.hex()}")
            if len(data) >= 2:
                scan_result = data[0]
                channel = data[1]
                if scan_result == 0x00:
                    print(f"responded on channel 0x{channel:02X}")
                    found_channels.append(channel)
                elif scan_result == 0x01:
                    print(f"no response on channel 0x{channel:02X}")
                else:
                    print(f"unknown scan result 0x{scan_result:02X} on channel 0x{channel:02X}")
            continue

        if frame.cmd == RESP_EXEC_ACTIVE_SCAN:
            data = expect_success(frame, RESP_EXEC_ACTIVE_SCAN)
            print(f"active scan complete: raw={data.hex()}")
            return sorted(set(found_channels))

        print(f"ignore cmd=0x{frame.cmd:04X} data={frame.data.hex()}")

    raise TimeoutError("timed out waiting for active scan completion")


def open_udp_3610(ser: serial.Serial, debug: bool = False) -> None:
    resp = send_cmd(ser, CMD_OPEN_UDP, (3610).to_bytes(2, "big"), debug=debug)
    ensure_response(resp, RESP_OPEN_UDP)

    if len(resp.data) < 1:
        raise RuntimeError("response data too short")

    result = resp.data[0]
    if result == 0x01:
        print("UDP 3610 open ok")
        return

    # 0x0A = already open
    if result == 0x0A:
        print("UDP 3610 is already open")
        return

    raise RuntimeError(f"module returned error result: 0x{result:02X}")


def set_broute_credentials(ser: serial.Serial, rbid: str, password: str, debug: bool = False) -> None:
    payload = rbid.encode("ascii") + password.encode("ascii")
    resp = send_cmd(ser, CMD_SET_BROUTE_PANA, payload, debug=debug)
    expect_success(resp, RESP_SET_BROUTE_PANA)
    print("B-route credentials accepted")


def start_broute(ser: serial.Serial, debug: bool = False) -> bytes:
    resp = send_cmd(ser, CMD_START_BROUTE, b"", debug=debug)
    data = expect_success(resp, RESP_START_BROUTE)
    print(f"B-route started: raw={data.hex()}")
    return data


def start_broute_with_retry(
    ser: serial.Serial,
    rbid: str,
    debug: bool = False,
) -> bytes:
    try:
        return start_broute(ser, debug=debug)
    except RuntimeError as e:
        msg = str(e)
        if "0x0E" not in msg:
            raise

        print("B-route start failed with 0x0E. Re-scanning channel and retrying once...")
        ensure_channel_ready(ser, rbid, debug=debug, force_scan=True)
        return start_broute(ser, debug=debug)


def start_pana(ser: serial.Serial, debug: bool = False) -> None:
    resp = send_cmd(ser, CMD_START_BROUTE_PANA, b"", debug=debug)
    expect_success(resp, RESP_START_BROUTE_PANA)
    print("PANA start command accepted")


def wait_for_pana_success(ser: serial.Serial, timeout: float = 60.0, debug: bool = False) -> bytes:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            frame = read_frame(ser, debug=debug)
        except TimeoutError:
            continue

        if frame.unique != RESP_UNIQUE:
            continue
        if frame.cmd != NOTIFY_PANA_RESULT:
            print(f"ignore notify cmd=0x{frame.cmd:04X} data={frame.data.hex()}")
            continue

        print(f"pana notify raw={frame.data.hex()}")
        if len(frame.data) < 9:
            raise RuntimeError(f"short 0x6028 data: {frame.data.hex()}")

        result = frame.data[0]
        mac = frame.data[1:9]
        if result != 0x01:
            raise RuntimeError(f"PANA failed: result=0x{result:02X}")
        return mac

    raise TimeoutError("timed out waiting for PANA result 0x6028")


def mac_to_j11_link_local_ipv6(mac: bytes) -> bytes:
    if len(mac) != 8:
        raise ValueError("expected 8-byte MAC")
    iid = bytearray(mac)
    iid[0] ^= 0x02
    return bytes.fromhex("fe80000000000000") + bytes(iid)


def ipv6_text(addr: bytes) -> str:
    return str(ipaddress.IPv6Address(addr))


def build_echonet_get_frame(tid: int, epcs: list[int]) -> bytes:
    payload = bytearray()
    payload += b"\x10\x81"
    payload += tid.to_bytes(2, "big")
    payload += b"\x05\xFF\x01"
    payload += b"\x02\x88\x01"
    payload += b"\x62"
    payload += bytes([len(epcs)])
    for epc in epcs:
        payload += bytes([epc, 0x00])
    return bytes(payload)


def send_udp_echonet(
    ser: serial.Serial,
    meter_ipv6: bytes,
    echonet_payload: bytes,
    debug: bool = False,
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

    resp = send_cmd(ser, CMD_SEND_UDP, payload, debug=debug)
    ensure_response(resp, RESP_SEND_UDP)
    if len(resp.data) < 2:
        raise RuntimeError(f"short 0x2008 response: {resp.data.hex()}")

    accept = resp.data[0]
    send_result = resp.data[1]
    if accept != 0x01:
        raise RuntimeError(f"0x0008 rejected: 0x{accept:02X}")

    print(f"udp send accepted, send_result=0x{send_result:02X}")
    return send_result


def parse_echonet_props(echonet: bytes):
    if len(echonet) < 12:
        return None
    if echonet[0:2] != b"\x10\x81":
        return None

    esv = echonet[10]
    opc = echonet[11]
    i = 12
    props = {}

    for _ in range(opc):
        if i + 2 > len(echonet):
            return None
        epc = echonet[i]
        pdc = echonet[i + 1]
        i += 2
        if i + pdc > len(echonet):
            return None
        edt = echonet[i:i + pdc]
        i += pdc
        props[epc] = edt

    return {
        "tid": int.from_bytes(echonet[2:4], "big"),
        "seoj": echonet[4:7],
        "deoj": echonet[7:10],
        "esv": esv,
        "props": props,
    }


def wait_for_udp_recv(ser: serial.Serial, timeout: float = 30.0, debug: bool = False):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            frame = read_frame(ser, debug=debug)
        except TimeoutError:
            continue

        if frame.unique != RESP_UNIQUE:
            continue
        if frame.cmd != NOTIFY_RECV_UDP:
            print(f"ignore notify cmd=0x{frame.cmd:04X} data={frame.data.hex()}")
            continue

        print(f"udp recv notify raw={frame.data.hex()}")

        if len(frame.data) < 27:
            continue

        echonet = frame.data[27:]
        parsed = parse_echonet_props(echonet)
        if parsed is None:
            continue

        if parsed["seoj"] != b"\x02\x88\x01":
            print(
                f"ignore ECHONET SEOJ={parsed['seoj'].hex()} "
                f"DEOJ={parsed['deoj'].hex()} ESV=0x{parsed['esv']:02X}"
            )
            continue

        return parsed

    raise TimeoutError("timed out waiting for UDP receive notify 0x6018")


def ensure_global_started(
    ser: serial.Serial,
    fallback_channel: int,
    debug: bool = False,
) -> None:
    global_state, _, _, _ = get_status(ser, debug=debug)
    if global_state == 0x03:
        return

    print(f"Global block is not started. Restoring Dual mode on channel 0x{fallback_channel:02X}...")
    set_initial_dual(ser, channel=fallback_channel, sleep=0x00, tx_power=0x00, debug=debug)
    get_initial(ser, debug=debug)


def ensure_channel_ready(
    ser: serial.Serial,
    rbid: str,
    debug: bool = False,
    force_scan: bool = False,
) -> int:
    saved_channel = load_saved_channel() or 0x0E

    ensure_global_started(ser, saved_channel, debug=debug)

    mode, _, channel, _ = get_initial(ser, debug=debug)

    if not force_scan and mode == 0x05 and channel != 0xFF:
        save_channel(channel)
        return channel

    pairing_id = rbid[-8:].upper()
    print(f"Pairing ID: {pairing_id}")

    found_channels = active_scan_collect(
        ser,
        pairing_id_ascii8=pairing_id,
        channel_mask=0x0003FFF0,
        duration=6,
        timeout=180.0,
        debug=debug,
    )

    print(f"found_channels={[f'0x{ch:02X}' for ch in found_channels]}")
    if not found_channels:
        raise RuntimeError("No smart meter beacon was found on any scanned channel")

    found_channel = found_channels[0]
    print(f"Using channel 0x{found_channel:02X}")
    set_initial_dual(ser, channel=found_channel, sleep=0x00, tx_power=0x00, debug=debug)
    save_channel(found_channel)
    get_initial(ser, debug=debug)
    return found_channel


MAC_FILE = Path.home() / ".j11_broute_mac"

def load_saved_mac() -> bytes | None:
    if MAC_FILE.exists():
        s = MAC_FILE.read_text().strip()
        if len(s) == 16:
            return bytes.fromhex(s)
    return None


def save_mac(mac: bytes) -> None:
    MAC_FILE.write_text(mac.hex() + "\n")


def connect_fresh(
    ser: serial.Serial,
    rbid: str,
    password: str,
    debug: bool = False,
) -> bytes:
    ensure_channel_ready(ser, rbid, debug=debug)
    set_broute_credentials(ser, rbid, password, debug=debug)
    start_broute_with_retry(ser, rbid, debug=debug)
    open_udp_3610(ser, debug=debug)
    start_pana(ser, debug=debug)
    meter_mac = wait_for_pana_success(ser, timeout=60.0, debug=debug)
    save_mac(meter_mac)
    print(f"PANA success, meter MAC={meter_mac.hex()}")
    return meter_mac


def end_broute_pana(ser: serial.Serial, debug: bool = False) -> None:
    resp = send_cmd(ser, CMD_END_BROUTE_PANA, b"", debug=debug)
    expect_success(resp, RESP_END_BROUTE_PANA)
    print("B-route PANA ended")


def stop_broute(ser: serial.Serial, debug: bool = False) -> None:
    resp = send_cmd(ser, CMD_STOP_BROUTE, b"", debug=debug)
    expect_success(resp, RESP_STOP_BROUTE)
    print("B-route stopped")


def connect_if_needed(
    ser: serial.Serial,
    rbid: str,
    password: str,
    debug: bool = False,
) -> bytes:
    global_state, broute_state, _, _ = get_status(ser, debug=debug)

    if global_state == 0x02:
        return connect_fresh(ser, rbid, password, debug=debug)

    if global_state != 0x03:
        raise RuntimeError(f"unexpected global state: 0x{global_state:02X}")

    if broute_state == 0x01:
        return connect_fresh(ser, rbid, password, debug=debug)

    if broute_state in (0x02, 0x03):
        print("B-route session already exists. Reusing it.")
        open_udp_3610(ser, debug=debug)
        mac = load_saved_mac()
        if mac is None:
            raise RuntimeError("No saved meter MAC is available")
        return mac

    raise RuntimeError(f"unexpected B-route state: 0x{broute_state:02X}")


def drain_notifications(ser: serial.Serial, seconds: float = 1.5, debug: bool = False):
    deadline = time.time() + seconds
    old_timeout = ser.timeout
    ser.timeout = 0.2
    try:
        while time.time() < deadline:
            try:
                frame = read_frame(ser, debug=debug)
                print(f"drain notify cmd=0x{frame.cmd:04X} data={frame.data.hex()}")
            except TimeoutError:
                pass
    finally:
        ser.timeout = old_timeout


def main():
    if len(sys.argv) < 4:
        print(f"usage: {sys.argv[0]} /dev/ttyUSB0 RBID32 PASSWORD12 [--debug]", file=sys.stderr)
        sys.exit(2)

    port = sys.argv[1]
    rbid = sys.argv[2]
    password = sys.argv[3]
    debug = "--debug" in sys.argv[4:]

    validate_broute(rbid, password)

    with serial.Serial(
        port=port,
        baudrate=115200,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=3,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    ) as ser:
        get_version(ser, debug=debug)
        meter_mac = connect_if_needed(ser, rbid, password, debug=debug)

        drain_notifications(ser, seconds=1.5, debug=debug)

        meter_ipv6 = mac_to_j11_link_local_ipv6(meter_mac)
        print(f"meter IPv6={ipv6_text(meter_ipv6)}")

        echonet_get = build_echonet_get_frame(1, [0xE7, 0xE8])

        for attempt in range(3):
            print(f"Sending ECHONET Get attempt {attempt + 1}")
            send_udp_echonet(ser, meter_ipv6, echonet_get, debug=debug)
        
            try:
                parsed = wait_for_udp_recv(ser, timeout=5.0, debug=debug)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
        else:
            raise RuntimeError("No smart meter Get_Res received")

        print(f"ECHONET parsed: esv=0x{parsed['esv']:02X} props={[hex(k) for k in parsed['props'].keys()]}")

        if 0xE7 in parsed["props"] and len(parsed["props"][0xE7]) == 4:
            inst_power = int.from_bytes(parsed["props"][0xE7], "big", signed=True)
            print(f"Instantaneous power: {inst_power} W")

        if 0xE8 in parsed["props"] and len(parsed["props"][0xE8]) == 4:
            r = int.from_bytes(parsed["props"][0xE8][0:2], "big", signed=False)
            t = int.from_bytes(parsed["props"][0xE8][2:4], "big", signed=False)
            print(f"Instantaneous current: R={r * 0.1:.1f} A, T={t * 0.1:.1f} A")


if __name__ == "__main__":
    main()

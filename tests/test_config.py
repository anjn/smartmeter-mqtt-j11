"""Tests for config module."""

import os
import tempfile

import pytest
import yaml

from j11_meter.config import J11Config, load_config


def _write_yaml(data: dict, tmpdir: str) -> str:
    path = os.path.join(tmpdir, "config.yaml")
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


def _valid_config_data() -> dict:
    return {
        "mqtt": {
            "host": "192.168.1.100",
            "port": 1883,
            "username": "mqtt_user",
            "password": "mqtt_pass",
        },
        "broute": {
            "rbid": "0123456789abcdef0123456789ABCDEF",
            "password": "ABCDEFGHIJKL",
        },
        "serial": {
            "device": "/dev/ttyUSB0",
        },
    }


def test_load_valid_config(tmp_path):
    path = _write_yaml(_valid_config_data(), str(tmp_path))
    cfg = load_config(path)
    assert isinstance(cfg, J11Config)
    assert cfg.mqtt_host == "192.168.1.100"
    assert cfg.mqtt_port == 1883
    assert cfg.mqtt_username == "mqtt_user"
    assert cfg.mqtt_password == "mqtt_pass"
    assert cfg.rbid == "0123456789abcdef0123456789ABCDEF"
    assert cfg.broute_password == "ABCDEFGHIJKL"
    assert cfg.serial_device == "/dev/ttyUSB0"
    assert cfg.state_dir == "/var/lib/j11_meter"


def test_load_config_custom_state_dir(tmp_path):
    data = _valid_config_data()
    data["state_dir"] = "/opt/j11_state"
    path = _write_yaml(data, str(tmp_path))
    cfg = load_config(path)
    assert cfg.state_dir == "/opt/j11_state"


def test_load_config_missing_file():
    with pytest.raises(ValueError, match="Config file not found"):
        load_config("/nonexistent/path/config.yaml")


def test_missing_mqtt_section(tmp_path):
    data = _valid_config_data()
    del data["mqtt"]
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(ValueError, match="Missing required section"):
        load_config(path)


def test_missing_mqtt_field(tmp_path):
    data = _valid_config_data()
    del data["mqtt"]["host"]
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(ValueError, match="Missing required mqtt field: .+"):
        load_config(path)


def test_missing_broute_section(tmp_path):
    data = _valid_config_data()
    del data["broute"]
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(ValueError, match="Missing required section"):
        load_config(path)


def test_missing_serial_section(tmp_path):
    data = _valid_config_data()
    del data["serial"]
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(ValueError, match="Missing required section"):
        load_config(path)


def test_invalid_rbid_too_short(tmp_path):
    data = _valid_config_data()
    data["broute"]["rbid"] = "0123456789abcdef"
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(ValueError, match="RBID must be a 32-character hex string"):
        load_config(path)


def test_invalid_rbid_non_hex(tmp_path):
    data = _valid_config_data()
    data["broute"]["rbid"] = "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG"
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(ValueError, match="RBID must be a 32-character hex string"):
        load_config(path)


def test_invalid_broute_password_too_short(tmp_path):
    data = _valid_config_data()
    data["broute"]["password"] = "SHORT"
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(
        ValueError, match="B-route password must be exactly .+ characters"
    ):
        load_config(path)


def test_invalid_broute_password_too_long(tmp_path):
    data = _valid_config_data()
    data["broute"]["password"] = "TOOLONGPASSWORD12345"
    path = _write_yaml(data, str(tmp_path))
    with pytest.raises(
        ValueError, match="B-route password must be exactly .+ characters"
    ):
        load_config(path)


def test_empty_config_file(tmp_path):
    path = os.path.join(str(tmp_path), "empty.yaml")
    with open(path, "w") as f:
        f.write("")
    with pytest.raises(ValueError, match="Config file is empty"):
        load_config(path)

"""Configuration loading and validation for j11-meter."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class J11Config:
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    rbid: str
    broute_password: str
    serial_device: str
    state_dir: str = "/var/lib/j11_meter"


def _validate_rbid(rbid: str) -> None:
    if len(rbid) != 32 or any(c not in "0123456789abcdefABCDEF" for c in rbid):
        raise ValueError("RBID must be a 32-character hex string")


def _validate_broute_password(password: str) -> None:
    if len(password) != 12:
        raise ValueError("B-route password must be exactly 12 characters")


def load_config(path: str) -> J11Config:
    """Load and validate configuration from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"Config file not found: {path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError("Config file is empty")

    try:
        mqtt = data["mqtt"]
        broute = data["broute"]
        serial = data["serial"]
    except KeyError as e:
        raise ValueError(f"Missing required section: {e}") from e

    # Validate required string fields
    required_mqtt_fields = ["host", "port", "username", "password"]
    for field in required_mqtt_fields:
        if field not in mqtt:
            raise ValueError(f"Missing required mqtt field: {field}")

    required_broute_fields = ["rbid", "password"]
    for field in required_broute_fields:
        if field not in broute:
            raise ValueError(f"Missing required broute field: {field}")

    if "device" not in serial:
        raise ValueError("Missing required serial field: device")

    rbid = str(broute["rbid"])
    broute_password = str(broute["password"])

    _validate_rbid(rbid)
    _validate_broute_password(broute_password)

    state_dir = data.get("state_dir", "/var/lib/j11_meter")

    config = J11Config(
        mqtt_host=str(mqtt["host"]),
        mqtt_port=int(mqtt["port"]),
        mqtt_username=str(mqtt["username"]),
        mqtt_password=str(mqtt["password"]),
        rbid=rbid,
        broute_password=broute_password,
        serial_device=str(serial["device"]),
        state_dir=str(state_dir),
    )

    logger.info("Configuration loaded from %s", path)
    return config

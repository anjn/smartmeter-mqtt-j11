"""MQTT client for Home Assistant discovery and state publishing."""

import json
import logging
from typing import Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "j11_broute_meter"
AVAILABILITY_TOPIC = "home/j11_meter/availability"
HA_STATUS_TOPIC = "homeassistant/status"

STATE_TOPIC_POWER = "home/j11_meter/power_w"
STATE_TOPIC_CURRENT_R = "home/j11_meter/current_r_a"
STATE_TOPIC_CURRENT_T = "home/j11_meter/current_t_a"
STATE_TOPIC_STATUS = "home/j11_meter/status"

DISCOVERY_TOPIC_POWER = f"{DISCOVERY_PREFIX}/sensor/j11_meter_power/config"
DISCOVERY_TOPIC_CURRENT_R = f"{DISCOVERY_PREFIX}/sensor/j11_meter_current_r/config"
DISCOVERY_TOPIC_CURRENT_T = f"{DISCOVERY_PREFIX}/sensor/j11_meter_current_t/config"
DISCOVERY_TOPIC_STATUS = f"{DISCOVERY_PREFIX}/sensor/j11_meter_status/config"


def build_device_object() -> dict:
    """Return the common device object for all discovery payloads (spec 3.1)."""
    return {
        "identifiers": [DEVICE_ID],
        "name": "J11 Smart Meter",
        "manufacturer": "RATOC/ROHM",
        "model": "RS-WSUHA-J11",
    }


def build_discovery_payloads() -> dict[str, str]:
    """Return dict mapping discovery topic -> JSON string for all 4 sensors.

    Payloads match spec sections 3.2-3.5 exactly.
    """
    device = build_device_object()
    common_availability = {
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
    }

    power_payload = {
        "name": "Smart Meter Power",
        "unique_id": "j11_meter_power_w",
        "state_topic": STATE_TOPIC_POWER,
        **common_availability,
        "unit_of_measurement": "W",
        "device_class": "power",
        "state_class": "measurement",
        "device": device,
    }

    current_r_payload = {
        "name": "Smart Meter Current R",
        "unique_id": "j11_meter_current_r_a",
        "state_topic": STATE_TOPIC_CURRENT_R,
        **common_availability,
        "unit_of_measurement": "A",
        "state_class": "measurement",
        "device": device,
    }

    current_t_payload = {
        "name": "Smart Meter Current T",
        "unique_id": "j11_meter_current_t_a",
        "state_topic": STATE_TOPIC_CURRENT_T,
        **common_availability,
        "unit_of_measurement": "A",
        "state_class": "measurement",
        "device": device,
    }

    status_payload = {
        "name": "Smart Meter Link Status",
        "unique_id": "j11_meter_status",
        "state_topic": STATE_TOPIC_STATUS,
        **common_availability,
        "icon": "mdi:transmission-tower",
        "device": device,
    }

    return {
        DISCOVERY_TOPIC_POWER: json.dumps(power_payload),
        DISCOVERY_TOPIC_CURRENT_R: json.dumps(current_r_payload),
        DISCOVERY_TOPIC_CURRENT_T: json.dumps(current_t_payload),
        DISCOVERY_TOPIC_STATUS: json.dumps(status_payload),
    }


def build_state_payload(
    power_w: int, current_r_a: float, current_t_a: float, status: str
) -> dict[str, str]:
    """Return dict mapping state topic -> string value.

    Format: power_w as str(int), currents as f"{val:.1f}", status as-is.
    """
    return {
        STATE_TOPIC_POWER: str(int(power_w)),
        STATE_TOPIC_CURRENT_R: f"{current_r_a:.1f}",
        STATE_TOPIC_CURRENT_T: f"{current_t_a:.1f}",
        STATE_TOPIC_STATUS: status,
    }


class MQTTPublisher:
    """MQTT publisher with LWT, discovery, state, and HA birth handling."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._client = mqtt.Client()
        self._discovery_payloads = build_discovery_payloads()

        if username:
            self._client.username_pw_set(username, password)

        self._client.will_set(AVAILABILITY_TOPIC, payload="offline", qos=1, retain=True)
        self._client.message_callback_add(HA_STATUS_TOPIC, self._on_ha_status)

    def connect(self) -> None:
        """Connect to broker, start loop, publish availability + discovery, subscribe to HA status."""
        self._client.connect(self._host, self._port)
        self._client.loop_start()
        logger.info("MQTT connected to %s:%d", self._host, self._port)

        self._client.publish(AVAILABILITY_TOPIC, payload="online", qos=1, retain=True)
        logger.info("Published availability=online")

        for topic, payload in self._discovery_payloads.items():
            self._client.publish(topic, payload=payload, qos=1, retain=True)
            logger.debug("Published discovery to %s", topic)

        self._client.subscribe(HA_STATUS_TOPIC, qos=1)
        logger.info("Subscribed to %s", HA_STATUS_TOPIC)

    def publish_state(self, state: dict[str, str]) -> None:
        """Publish each state topic (qos=0, retain=True)."""
        for topic, value in state.items():
            self._client.publish(topic, payload=value, qos=0, retain=True)
        logger.debug("Published state: %s", state)

    def publish_availability(self, online: bool) -> None:
        """Publish 'online' or 'offline' to availability topic (qos=1, retain=True)."""
        payload = "online" if online else "offline"
        self._client.publish(AVAILABILITY_TOPIC, payload=payload, qos=1, retain=True)
        logger.info("Published availability=%s", payload)

    def _on_ha_status(
        self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage
    ) -> None:
        """Callback for homeassistant/status: resend discovery on HA online."""
        if msg.payload == b"online":
            logger.info("HA birth message received, resending discovery")
            for topic, payload in self._discovery_payloads.items():
                client.publish(topic, payload=payload, qos=1, retain=True)
            logger.info("Discovery payloads resent")

    def disconnect(self) -> None:
        """Graceful disconnect: publish offline, stop loop, disconnect."""
        self._client.publish(AVAILABILITY_TOPIC, payload="offline", qos=1, retain=True)
        logger.info("Published availability=offline")
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT disconnected")

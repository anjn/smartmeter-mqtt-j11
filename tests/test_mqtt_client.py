"""Tests for MQTT client payload construction."""

import json

from j11_meter.mqtt_client import (
    AVAILABILITY_TOPIC,
    DEVICE_ID,
    DISCOVERY_TOPIC_CURRENT_R,
    DISCOVERY_TOPIC_CURRENT_T,
    DISCOVERY_TOPIC_POWER,
    DISCOVERY_TOPIC_STATUS,
    HA_STATUS_TOPIC,
    STATE_TOPIC_CURRENT_R,
    STATE_TOPIC_CURRENT_T,
    STATE_TOPIC_POWER,
    STATE_TOPIC_STATUS,
    build_device_object,
    build_discovery_payloads,
    build_state_payload,
)


class TestBuildDeviceObject:
    def test_exact_fields(self):
        device = build_device_object()
        assert device == {
            "identifiers": ["j11_broute_meter"],
            "name": "J11 Smart Meter",
            "manufacturer": "RATOC/ROHM",
            "model": "RS-WSUHA-J11",
        }

    def test_identifiers_type(self):
        device = build_device_object()
        assert isinstance(device["identifiers"], list)
        assert device["identifiers"] == [DEVICE_ID]


class TestBuildDiscoveryPayloads:
    @classmethod
    def setup_class(cls):
        cls.payloads = build_discovery_payloads()
        cls.parsed = {k: json.loads(v) for k, v in cls.payloads.items()}

    def test_four_payloads(self):
        assert len(self.payloads) == 4

    def test_discovery_topics(self):
        expected_topics = {
            DISCOVERY_TOPIC_POWER,
            DISCOVERY_TOPIC_CURRENT_R,
            DISCOVERY_TOPIC_CURRENT_T,
            DISCOVERY_TOPIC_STATUS,
        }
        assert set(self.payloads.keys()) == expected_topics

    def test_power_discovery_payload(self):
        p = self.parsed[DISCOVERY_TOPIC_POWER]
        assert p["name"] == "Smart Meter Power"
        assert p["unique_id"] == "j11_meter_power_w"
        assert p["state_topic"] == STATE_TOPIC_POWER
        assert p["availability_topic"] == AVAILABILITY_TOPIC
        assert p["payload_available"] == "online"
        assert p["payload_not_available"] == "offline"
        assert p["unit_of_measurement"] == "W"
        assert p["device_class"] == "power"
        assert p["state_class"] == "measurement"
        assert p["device"] == build_device_object()

    def test_current_r_discovery_payload(self):
        p = self.parsed[DISCOVERY_TOPIC_CURRENT_R]
        assert p["name"] == "Smart Meter Current R"
        assert p["unique_id"] == "j11_meter_current_r_a"
        assert p["state_topic"] == STATE_TOPIC_CURRENT_R
        assert p["availability_topic"] == AVAILABILITY_TOPIC
        assert p["payload_available"] == "online"
        assert p["payload_not_available"] == "offline"
        assert p["unit_of_measurement"] == "A"
        assert p["state_class"] == "measurement"
        assert "device_class" not in p
        assert p["device"] == build_device_object()

    def test_current_t_discovery_payload(self):
        p = self.parsed[DISCOVERY_TOPIC_CURRENT_T]
        assert p["name"] == "Smart Meter Current T"
        assert p["unique_id"] == "j11_meter_current_t_a"
        assert p["state_topic"] == STATE_TOPIC_CURRENT_T
        assert p["availability_topic"] == AVAILABILITY_TOPIC
        assert p["payload_available"] == "online"
        assert p["payload_not_available"] == "offline"
        assert p["unit_of_measurement"] == "A"
        assert p["state_class"] == "measurement"
        assert "device_class" not in p
        assert p["device"] == build_device_object()

    def test_status_discovery_payload(self):
        p = self.parsed[DISCOVERY_TOPIC_STATUS]
        assert p["name"] == "Smart Meter Link Status"
        assert p["unique_id"] == "j11_meter_status"
        assert p["state_topic"] == STATE_TOPIC_STATUS
        assert p["availability_topic"] == AVAILABILITY_TOPIC
        assert p["payload_available"] == "online"
        assert p["payload_not_available"] == "offline"
        assert p["icon"] == "mdi:transmission-tower"
        assert "unit_of_measurement" not in p
        assert "device_class" not in p
        assert "state_class" not in p
        assert p["device"] == build_device_object()

    def test_all_payloads_valid_json(self):
        for topic, payload_str in self.payloads.items():
            parsed = json.loads(payload_str)
            assert isinstance(parsed, dict)

    def test_no_extra_fields_power(self):
        p = self.parsed[DISCOVERY_TOPIC_POWER]
        expected_keys = {
            "name",
            "unique_id",
            "state_topic",
            "availability_topic",
            "payload_available",
            "payload_not_available",
            "unit_of_measurement",
            "device_class",
            "state_class",
            "device",
        }
        assert set(p.keys()) == expected_keys

    def test_no_extra_fields_status(self):
        p = self.parsed[DISCOVERY_TOPIC_STATUS]
        expected_keys = {
            "name",
            "unique_id",
            "state_topic",
            "availability_topic",
            "payload_available",
            "payload_not_available",
            "icon",
            "device",
        }
        assert set(p.keys()) == expected_keys


class TestBuildStatePayload:
    def test_positive_power(self):
        state = build_state_payload(
            power_w=636, current_r_a=6.0, current_t_a=1.0, status="connected"
        )
        assert state[STATE_TOPIC_POWER] == "636"
        assert state[STATE_TOPIC_CURRENT_R] == "6.0"
        assert state[STATE_TOPIC_CURRENT_T] == "1.0"
        assert state[STATE_TOPIC_STATUS] == "connected"

    def test_negative_power(self):
        state = build_state_payload(
            power_w=-120, current_r_a=3.5, current_t_a=0.5, status="connected"
        )
        assert state[STATE_TOPIC_POWER] == "-120"
        assert state[STATE_TOPIC_CURRENT_R] == "3.5"
        assert state[STATE_TOPIC_CURRENT_T] == "0.5"

    def test_current_one_decimal(self):
        state = build_state_payload(
            power_w=0, current_r_a=6, current_t_a=1, status="connected"
        )
        assert state[STATE_TOPIC_CURRENT_R] == "6.0"
        assert state[STATE_TOPIC_CURRENT_T] == "1.0"

    def test_zero_power(self):
        state = build_state_payload(
            power_w=0, current_r_a=0.0, current_t_a=0.0, status="connected"
        )
        assert state[STATE_TOPIC_POWER] == "0"

    def test_status_values(self):
        for status in ("connected", "degraded", "disconnected", "error"):
            state = build_state_payload(
                power_w=100, current_r_a=1.0, current_t_a=1.0, status=status
            )
            assert state[STATE_TOPIC_STATUS] == status

    def test_returns_four_entries(self):
        state = build_state_payload(
            power_w=0, current_r_a=0.0, current_t_a=0.0, status="connected"
        )
        assert len(state) == 4
        assert set(state.keys()) == {
            STATE_TOPIC_POWER,
            STATE_TOPIC_CURRENT_R,
            STATE_TOPIC_CURRENT_T,
            STATE_TOPIC_STATUS,
        }

    def test_all_values_are_strings(self):
        state = build_state_payload(
            power_w=636, current_r_a=6.0, current_t_a=1.0, status="connected"
        )
        for v in state.values():
            assert isinstance(v, str)

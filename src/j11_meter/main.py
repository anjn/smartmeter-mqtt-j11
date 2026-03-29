"""Main orchestration for j11-meter service."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from typing import Optional

from j11_meter.broute import J11Bridge
from j11_meter.config import J11Config, load_config
from j11_meter.mqtt_client import MQTTPublisher, build_state_payload

logger = logging.getLogger(__name__)


class FailureTracker:
    """Tracks consecutive read failures and determines status."""

    def __init__(self, disconnect_threshold: int = 3) -> None:
        self._consecutive_failures = 0
        self._disconnect_threshold = disconnect_threshold
        self._status: str = "connected"

    @property
    def status(self) -> str:
        return self._status

    @property
    def failure_count(self) -> int:
        return self._consecutive_failures

    def record_failure(self) -> str:
        """Record a failure. Returns current status."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._disconnect_threshold:
            self._status = "disconnected"
        else:
            self._status = "degraded"
        return self._status

    def record_success(self) -> str:
        """Record a success. Resets failure count."""
        self._consecutive_failures = 0
        self._status = "connected"
        return self._status


def run_service(config: J11Config) -> None:
    """Main service orchestration."""
    stop_event = threading.Event()

    def _sigterm_handler(signum: int, frame: object) -> None:
        logger.info("Received SIGTERM, initiating graceful shutdown")
        stop_event.set()

    signal.signal(signal.SIGTERM, _sigterm_handler)

    # Ensure state_dir exists
    from pathlib import Path

    Path(config.state_dir).mkdir(parents=True, exist_ok=True)

    bridge: Optional[J11Bridge] = None
    publisher: Optional[MQTTPublisher] = None
    tracker = FailureTracker(disconnect_threshold=3)

    last_power: Optional[int] = None
    last_current_r: Optional[float] = None
    last_current_t: Optional[float] = None

    try:
        # 1. Connect B-route
        logger.info("Connecting to smart meter via B-route...")
        bridge = J11Bridge(
            serial_device=config.serial_device,
            rbid=config.rbid,
            password=config.broute_password,
            state_dir=config.state_dir,
        )
        bridge.connect()
        logger.info("B-route connected")

        # 2. Connect MQTT
        logger.info(
            "Connecting to MQTT broker %s:%d", config.mqtt_host, config.mqtt_port
        )
        publisher = MQTTPublisher(
            host=config.mqtt_host,
            port=config.mqtt_port,
            username=config.mqtt_username,
            password=config.mqtt_password,
        )
        publisher.connect()
        logger.info("MQTT connected, discovery published")

        # 3. Main loop
        while not stop_event.is_set():
            try:
                power_w, current_r_a, current_t_a = bridge.read_meter()
                last_power = power_w
                last_current_r = current_r_a
                last_current_t = current_t_a

                status = tracker.record_success()
                state = build_state_payload(
                    power_w=power_w,
                    current_r_a=current_r_a,
                    current_t_a=current_t_a,
                    status=status,
                )
                publisher.publish_state(state)
                logger.info(
                    "power=%dW, R=%.1fA, T=%.1fA", power_w, current_r_a, current_t_a
                )

            except Exception as e:
                status = tracker.record_failure()
                logger.warning(
                    "Read failure #%d: %s (status=%s)",
                    tracker.failure_count,
                    e,
                    status,
                )

                # Publish last-known values with degraded/disconnected status
                if last_power is not None:
                    state = build_state_payload(
                        power_w=last_power,
                        current_r_a=last_current_r or 0.0,
                        current_t_a=last_current_t or 0.0,
                        status=status,
                    )
                    try:
                        publisher.publish_state(state)
                    except Exception:
                        logger.error("Failed to publish state after read failure")

                # If disconnected, attempt full reconnection
                if status == "disconnected":
                    logger.info("Attempting B-route reconnection...")
                    try:
                        bridge.reconnect()
                        tracker.record_success()
                        logger.info("B-route reconnected")
                    except Exception as re_err:
                        logger.error("Reconnection failed: %s", re_err)

            stop_event.wait(timeout=10.0)

    except Exception as e:
        logger.error("Service error: %s", e)
        raise
    finally:
        logger.info("Shutting down...")
        if publisher is not None:
            try:
                publisher.disconnect()
            except Exception as e:
                logger.error("Error disconnecting MQTT: %s", e)
        if bridge is not None:
            try:
                bridge.close()
            except Exception as e:
                logger.error("Error closing B-route: %s", e)
        logger.info("Shutdown complete")


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="J11 Smart Meter MQTT Service")
    parser.add_argument(
        "--config", default="/etc/j11_meter/config.yaml", help="Path to config YAML"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    run_service(config)


if __name__ == "__main__":
    main()

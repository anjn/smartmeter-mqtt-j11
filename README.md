# j11-meter

MQTT service for publishing smart meter data (RS-WSUHA-J11) to Home Assistant via B-route.

## Prerequisites

- Python 3.10+
- RS-WSUHA-J11 smart meter adapter
- MQTT broker (e.g., Mosquitto)

## Installation

```bash
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

## Configuration

1. Copy the example config:
   ```bash
   sudo mkdir -p /etc/j11_meter
   sudo cp config.example.yaml /etc/j11_meter/config.yaml
   ```

2. Edit `/etc/j11_meter/config.yaml` with your MQTT broker and B-route credentials.

## Usage

```bash
j11-meter --config /etc/j11_meter/config.yaml
# or
python -m j11_meter.main --config /etc/j11_meter/config.yaml
```

Enable debug logging:

```bash
j11-meter --config /etc/j11_meter/config.yaml --debug
```

## systemd

```bash
sudo cp j11-meter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now j11-meter
```

View logs:

```bash
journalctl -u j11-meter -f
```

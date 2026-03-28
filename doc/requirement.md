# MQTT実装仕様書

**対象**: RS-WSUHA-J11 + Proxmox LXC + Home Assistant VM
**目的**: LXC 上の Python プロセスが Bルートで取得した電力データを MQTT で Home Assistant に連携する。
Home Assistant の MQTT 統合は discovery に対応しており、discovery prefix の既定値は `homeassistant`、HA は既定で `homeassistant/status` に birth / LWT を送ります。 ([Home Assistant][1])

## 1. 構成

* **データ取得側**: Proxmox LXC 内の Python サービス
* **Broker**: Home Assistant 側の Mosquitto Broker
* **可視化側**: Home Assistant MQTT 統合
* **接続方式**: TCP, MQTT 3.1.1
* **認証**: MQTT username/password

Broker の設定は Home Assistant の MQTT 統合で行い、broker の hostname/IP, port, username, password を指定する構成とする。 ([Home Assistant][1])

## 2. トピック設計

### 2.1 Discovery prefix

* `homeassistant`

これは Home Assistant MQTT の既定値に合わせる。 ([Home Assistant][1])

### 2.2 デバイス識別子

* device id: `j11_broute_meter`

### 2.3 Discovery topic

* `homeassistant/sensor/j11_meter_power/config`
* `homeassistant/sensor/j11_meter_current_r/config`
* `homeassistant/sensor/j11_meter_current_t/config`
* `homeassistant/sensor/j11_meter_status/config`

### 2.4 State topic

* `home/j11_meter/power_w`
* `home/j11_meter/current_r_a`
* `home/j11_meter/current_t_a`
* `home/j11_meter/status`

### 2.5 Availability topic

* `home/j11_meter/availability`

## 3. Home Assistant discovery payload 仕様

Home Assistant の MQTT discovery では、デバイスとエンティティを JSON payload で公開する。discovery は retained を使うか、HA の birth message を見て再送するのが推奨です。 ([Home Assistant][1])

### 3.1 共通 device オブジェクト

```json
{
  "identifiers": ["j11_broute_meter"],
  "name": "J11 Smart Meter",
  "manufacturer": "RATOC/ROHM",
  "model": "RS-WSUHA-J11"
}
```

### 3.2 瞬時電力センサー

Topic:
`homeassistant/sensor/j11_meter_power/config`

Payload:

```json
{
  "name": "Smart Meter Power",
  "unique_id": "j11_meter_power_w",
  "state_topic": "home/j11_meter/power_w",
  "availability_topic": "home/j11_meter/availability",
  "payload_available": "online",
  "payload_not_available": "offline",
  "unit_of_measurement": "W",
  "device_class": "power",
  "state_class": "measurement",
  "device": {
    "identifiers": ["j11_broute_meter"],
    "name": "J11 Smart Meter",
    "manufacturer": "RATOC/ROHM",
    "model": "RS-WSUHA-J11"
  }
}
```

### 3.3 瞬時電流 R 相

Topic:
`homeassistant/sensor/j11_meter_current_r/config`

Payload:

```json
{
  "name": "Smart Meter Current R",
  "unique_id": "j11_meter_current_r_a",
  "state_topic": "home/j11_meter/current_r_a",
  "availability_topic": "home/j11_meter/availability",
  "payload_available": "online",
  "payload_not_available": "offline",
  "unit_of_measurement": "A",
  "state_class": "measurement",
  "device": {
    "identifiers": ["j11_broute_meter"],
    "name": "J11 Smart Meter",
    "manufacturer": "RATOC/ROHM",
    "model": "RS-WSUHA-J11"
  }
}
```

### 3.4 瞬時電流 T 相

Topic:
`homeassistant/sensor/j11_meter_current_t/config`

Payload:

```json
{
  "name": "Smart Meter Current T",
  "unique_id": "j11_meter_current_t_a",
  "state_topic": "home/j11_meter/current_t_a",
  "availability_topic": "home/j11_meter/availability",
  "payload_available": "online",
  "payload_not_available": "offline",
  "unit_of_measurement": "A",
  "state_class": "measurement",
  "device": {
    "identifiers": ["j11_broute_meter"],
    "name": "J11 Smart Meter",
    "manufacturer": "RATOC/ROHM",
    "model": "RS-WSUHA-J11"
  }
}
```

### 3.5 ステータスセンサー

Topic:
`homeassistant/sensor/j11_meter_status/config`

Payload:

```json
{
  "name": "Smart Meter Link Status",
  "unique_id": "j11_meter_status",
  "state_topic": "home/j11_meter/status",
  "availability_topic": "home/j11_meter/availability",
  "payload_available": "online",
  "payload_not_available": "offline",
  "icon": "mdi:transmission-tower",
  "device": {
    "identifiers": ["j11_broute_meter"],
    "name": "J11 Smart Meter",
    "manufacturer": "RATOC/ROHM",
    "model": "RS-WSUHA-J11"
  }
}
```

## 4. State payload 仕様

### 4.1 `home/j11_meter/power_w`

* 型: stringified integer
* 例: `"636"`

### 4.2 `home/j11_meter/current_r_a`

* 型: stringified decimal
* 例: `"6.0"`

### 4.3 `home/j11_meter/current_t_a`

* 型: stringified decimal
* 例: `"1.0"`

### 4.4 `home/j11_meter/status`

* 型: string
* 値:

  * `connected`
  * `degraded`
  * `disconnected`
  * `error`

### 4.5 `home/j11_meter/availability`

* 型: string
* 値:

  * `online`
  * `offline`

## 5. retain / QoS 仕様

### 5.1 Discovery

* retain: `true`
* qos: `1`

HA は MQTT discovery を retained で保持するか、birth を購読して再送する方式が推奨される。 ([Home Assistant][1])

### 5.2 State

* retain: `true`
* qos: `0`

理由:

* HA 再起動後に最新値がすぐ見える
* 電力値は高頻度更新なので QoS 0 で十分

### 5.3 Availability

* retain: `true`
* qos: `1`

## 6. 起動シーケンス

LXC 内サービス起動時は次の順序とする。

1. MQTT broker 接続
2. `home/j11_meter/availability = online` publish
3. discovery payload を publish
4. Bルート接続確認
5. 値取得
6. state topic を publish
7. 以後周期実行

HA は `homeassistant/status` に birth message `online` を送るため、これを購読して discovery を再送してもよい。 ([Home Assistant][1])

## 7. 定期送信仕様

* 読み取り周期: **10秒**
* publish 周期: **10秒**
* discovery 再送:

  * 起動時
  * HA birth 受信時
  * 24時間ごと任意再送

## 8. エラー処理

### 8.1 一時的な読み取り失敗

* `status = degraded`
* availability は `online` のまま
* 前回成功値は保持
* 3回連続失敗で `status = disconnected`

### 8.2 MQTT broker 切断

* 自動再接続
* 再接続後に discovery を再送
* availability を `online` に再送

### 8.3 Bルート再接続

以下で再接続を試みる。

* `PANA` 失敗
* `UDP` 送信失敗が連続 3 回
* 一定時間値が取得できない

## 9. Home Assistant 側要件

* MQTT 統合を有効化する
* Broker は Mosquitto Broker を推奨
* discovery は有効のまま使う
* `homeassistant` prefix を使用する

Home Assistant の MQTT discovery は既定で有効です。 ([Home Assistant][1])

## 10. Python 実装要件

* ライブラリ:

  * `pyserial`
  * `paho-mqtt`
* systemd サービス化
* 異常終了時は自動再起動
* 設定ファイル:

  * MQTT host
  * MQTT port
  * MQTT username
  * MQTT password
  * RBID
  * Bルート password
  * serial device path

## 11. 最低限の JSON 送信例

### Discovery

```json
{"name":"Smart Meter Power","unique_id":"j11_meter_power_w","state_topic":"home/j11_meter/power_w","availability_topic":"home/j11_meter/availability","payload_available":"online","payload_not_available":"offline","unit_of_measurement":"W","device_class":"power","state_class":"measurement","device":{"identifiers":["j11_broute_meter"],"name":"J11 Smart Meter","manufacturer":"RATOC/ROHM","model":"RS-WSUHA-J11"}}
```

### State

```text
Topic: home/j11_meter/power_w
Payload: 636
```

```text
Topic: home/j11_meter/current_r_a
Payload: 6.0
```

```text
Topic: home/j11_meter/current_t_a
Payload: 1.0
```

```text
Topic: home/j11_meter/availability
Payload: online
```


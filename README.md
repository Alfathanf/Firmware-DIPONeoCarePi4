# DIPONeoCare Raspberry Pi - Device Registration

This project is a standalone Python 3 implementation for the Raspberry Pi 4 device-registration phase. It does not modify or replace the ESP32-S3 firmware.

## Implemented now

- Detect the Raspberry Pi network MAC address.
- Detect the Raspberry Pi local IPv4 address.
- Send the ESP32-compatible registration payload to the backend.
- Parse `deviceId`, `deviceToken`, and `paired`.
- Persist identity in `data/device_identity.json` with owner-only permissions.
- Skip registration on later runs while valid identity data is stored.
- Retry network/server failures when running without `--once`.
- Never print or store the token in source control or logs.

Heartbeats, frame upload, audio upload, camera use, live streaming, and AI processing are intentionally not implemented.

## ESP32 registration contract

The source implementation uses:

- Base URL: `https://diponeocare.up.railway.app/`
- Method: `POST`
- Endpoint: `api/devices/register`
- Content type: `application/json`
- Registration header: no authentication header
- Authenticated subsequent-request header: `x-device-token`

Payload:

```json
{
  "macAddress": "DC:A6:32:12:34:56",
  "localIp": "192.168.1.50",
  "firmwareVersion": "1.0.0"
}
```

The ESP32 expects:

```json
{
  "success": true,
  "data": {
    "deviceId": "device-id",
    "deviceToken": "device-token",
    "paired": false
  }
}
```

Source references: [device_registration.cpp](../src/network/device_registration.cpp), [http_client.cpp](../src/network/http_client.cpp), [network_scheduler.cpp](../src/network/network_scheduler.cpp), [config.h](../include/config.h), and [wifi_manager.cpp](../src/wifi/wifi_manager.cpp).

If `paired` is `false`, this phase treats registration as successful but not yet paired. It does not register again on subsequent runs.

## Install on Raspberry Pi OS

```bash
cd ~/DIPONeoCare/raspi
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Keep `.env` and `data/` outside Git. Both are ignored by this project's `.gitignore`.

## Run registration

One check/request:

```bash
python3 main.py --once
```

Retry until successful:

```bash
python3 main.py
```

Stop retry mode with `Ctrl+C`.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 -c "from device.identity import DeviceIdentity; i=DeviceIdentity.detect('1.0.0'); print(i)"
ls -l data/device_identity.json
```

The registration log shows MAC, local IP, software version, and device ID, but not the device token. Running again should print "already registered" and make no HTTP request.

To test backend failure, stop or unreachable the network/backend and run `python3 main.py --once`. It will return an error and exit status 1 without crashing.

## Module layout

- `main.py`: command-line entry point and retry loop.
- `config.py`: `.env` and runtime settings.
- `device/identity.py`: Raspberry Pi MAC and local IP detection.
- `device/registration.py`: registration response parsing and persistent identity storage.
- `communication/api_client.py`: HTTP/HTTPS requests.
- `camera/`, `audio/`, `storage/`: reserved for later phases.

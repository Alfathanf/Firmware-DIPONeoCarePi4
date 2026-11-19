# DIPONeoCare Raspberry Pi - Device Registration

This project is a standalone Python 3 implementation for Raspberry Pi 4 device registration and heartbeat. It does not modify or replace the ESP32-S3 firmware.

## Implemented now

- Detect the Raspberry Pi network MAC address.
- Detect the Raspberry Pi local IPv4 address.
- Send the ESP32-compatible registration payload to the backend.
- Parse `deviceId`, `deviceToken`, and `paired`.
- Persist identity in `data/device_identity.json` with owner-only permissions.
- Skip registration on later runs while valid identity data is stored.
- Retry network/server failures when running without `--once`.
- Never print or store the token in source control or logs.

Frame upload is implemented. Audio upload, live streaming, and AI processing remain intentionally unimplemented.

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

## Run heartbeat

Send one heartbeat using only the saved Raspberry Pi identity:

```bash
python3 main.py --heartbeat
```

Run registration as needed, then continuously send heartbeats:

```bash
python3 main.py
```

The continuous mode uses the ESP32 heartbeat contract:

- Endpoint: `api/devices/heartbeat`
- Method: `POST`
- Normal interval: 15 seconds
- Payload:
  ```json
  {"macAddress":"DC:A6:32:12:34:56","localIp":"192.168.1.50"}
  ```
- Header: `x-device-token: <saved Raspberry Pi token>`

The payload does not include `deviceId`; the ESP32 firmware authenticates with the token and uses HTTP success status. The Raspberry Pi uses the loaded saved `deviceId` for logging and validation only.

Stop continuous mode with `Ctrl+C` or `SIGTERM`. Failure responses and network errors are retried without deleting the saved identity or repeating registration. HTTP 401/403 is reported as authentication failure.

## Install camera dependency on Raspberry Pi OS

Use Raspberry Pi OS package management rather than pip for Picamera2:

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-pil
cd ~/DIPONeoCare/raspi
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

The OV5647 CSI camera must be enabled and visible to the Raspberry Pi OS camera stack.

## Run Frame Upload

Send one captured frame using the saved Raspberry Pi identity:

```bash
python3 main.py --frame-upload
```

Run the complete application with heartbeat and frame capture/upload:

```bash
python3 main.py
```

Frame upload uses:

- Method: `POST`
- Endpoint: `api/devices/upload/frame`
- Header: `x-device-token`
- Multipart fields: `macAddress`, `captureId`, `timestamp`
- Multipart file field: `image`
- Filename: `frame.jpg`
- File content type: `image/jpeg`

The queue is latest-first and bounded. The default capacity is one frame. A new capture supersedes and removes the oldest queued frame. Failed uploads retain the latest frame, while newer captures replace older retained frames. The uploader does not keep a growing offline backlog.

## Frame configuration

```env
FRAME_CAPTURE_INTERVAL_SECONDS=1
FRAME_UPLOAD_TIMEOUT_SECONDS=5
FRAME_UPLOAD_RETRY_SECONDS=5
FRAME_QUEUE_MAX_SIZE=1
FRAME_IMAGE_FORMAT=jpeg
FRAME_IMAGE_QUALITY=85
FRAME_IMAGE_WIDTH=640
FRAME_IMAGE_HEIGHT=480
```

Physical camera verification:

```bash
rpicam-hello --timeout 3000
python3 main.py --frame-upload
```

Frame capture uses `Picamera2.capture_file()` with an in-memory `io.BytesIO` buffer and JPEG format. The implementation validates that the result starts with a JPEG SOI marker (`FF D8`) and ends with an EOI marker (`FF D9`) before placing it on the frame queue.

## Audio Upload

The Raspberry Pi records five-second mono WAV windows with `arecord`:

```bash
arecord -l
arecord --list-devices
arecord --dump-hw-params -D plughw -f S16_LE -r 16000 -c 1
```

Use `AUDIO_DEVICE` as an ALSA PCM name only when needed. Leave it empty for ALSA default device selection.

Audio upload uses:

- Endpoint: `api/devices/upload/audio`
- Method: `POST`
- Header: `x-device-token`
- Multipart fields: `macAddress`, `audioWindowId`, `startedAt`, `durationSeconds`
- File field: `audio`
- Filename: `audio_<audioWindowId>.wav`
- Content type: `audio/wav`
- WAV format: 16 kHz, mono, 16-bit PCM
- Duration: 5 seconds

Install ALSA tools on Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y alsa-utils
```

Test recording:

```bash
arecord -D default -t wav -f S16_LE -r 16000 -c 1 -d 5 test.wav
aplay test.wav
```

Run one audio recording and upload:

```bash
python3 main.py --audio-upload
```

The full service runs heartbeat, frame upload, and audio upload independently:

```bash
python3 main.py
```

The audio queue is FIFO and disk-backed. It preserves insert order and does not replace older recordings. When the configured in-memory queue is full, new WAV and metadata files remain on disk and are loaded for later processing; the queue policy does not silently discard recordings. Failed uploads keep the WAV and metadata until an HTTP 2xx response. Successful uploads remove both.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 -c "from device.identity import DeviceIdentity; i=DeviceIdentity.detect('1.0.0'); print(i)"
ls -l data/device_identity.json
```

Use mocked requests for the automated heartbeat suite:

```bash
python3 -m unittest discover -s tests -v
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

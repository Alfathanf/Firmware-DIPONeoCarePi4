import logging
import psutil
import threading
import time
from dataclasses import dataclass
from typing import Optional

from camera.camera_manager import CameraError, CameraManager
from live_stream.live_stream_client import LiveStreamClient


@dataclass(frozen=True)
class LiveFrame:
    jpeg: bytes
    sequence: int
    captured_monotonic: float


class LatestFrameBuffer:
    def __init__(self) -> None:
        self._frame: Optional[LiveFrame] = None
        self._lock = threading.Lock()
        self.replaced = 0

    def put(self, frame: LiveFrame) -> None:
        with self._lock:
            if self._frame is not None:
                self.replaced += 1
            self._frame = frame

    def take(self) -> Optional[LiveFrame]:
        with self._lock:
            frame = self._frame
            self._frame = None
            return frame

    def clear(self) -> None:
        with self._lock:
            self._frame = None


def build_live_url(base_url: str, device_id: str) -> str:
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    elif not base.startswith(("wss://", "ws://")):
        raise ValueError("BACKEND_BASE_URL must use HTTP, HTTPS, WS, or WSS")
    return f"{base}/api/devices/{device_id}/live/ingest"


def exponential_backoff(
    base_seconds: float,
    max_seconds: float,
    attempt: int,
) -> float:
    delay = base_seconds * (2 ** max(0, attempt - 1))
    return min(delay, max_seconds)


class LiveStreamPublisher:
    def __init__(
        self,
        settings,
        registration_manager,
        identity,
        stop_event: Optional[threading.Event] = None,
        camera: Optional[CameraManager] = None,
    ) -> None:
        self.settings = settings
        self.registration_manager = registration_manager
        self.identity = identity
        self.stop_event = stop_event or threading.Event()
        self.buffer = LatestFrameBuffer()
        self._owns_camera = camera is None
        self.camera = camera or CameraManager(
            settings.live_stream_width,
            settings.live_stream_height,
            settings.live_stream_jpeg_quality,
        )
        self.client = None
        self.sequence = 0
        self.capture_count = 0
        self.send_count = 0
        self.capture_duration_total = 0.0
        self.jpeg_size_total = 0
        self.send_duration_total = 0.0
        self.reconnect_count = 0
        self.capture_thread = None
        self.publisher_thread = None

    def stop(self) -> None:
        self.stop_event.set()
        if self.client is not None:
            self.client.close()
        self.buffer.clear()
        if self._owns_camera:
            self.camera.stop()

    def run(self) -> None:
        registration = self.registration_manager.load()
        if registration is None:
            logging.error("[LIVE] Saved Raspberry Pi identity is unavailable")
            return

        live_url = build_live_url(
            self.settings.backend_base_url,
            registration.device_id,
        )
        headers = {
            "x-device-mac": self.identity.mac_address,
            "x-device-token": registration.device_token,
        }

        self.client = LiveStreamClient(
            live_url,
            headers,
            self.settings.live_stream_ping_interval_seconds,
            self.settings.live_stream_ping_timeout_seconds,
        )

        try:
            self.camera.start(fps=self.settings.live_stream_fps)
        except CameraError as exc:
            logging.error("[LIVE] Camera unavailable: %s", exc)
            return

        self.capture_thread = threading.Thread(
            target=self._capture_loop,
            name="live-capture",
            daemon=True,
        )
        self.publisher_thread = threading.Thread(
            target=self._publisher_loop,
            name="live-publisher",
            daemon=True,
        )
        self.capture_thread.start()
        self.publisher_thread.start()
        self._stats_loop()

    def _capture_loop(self) -> None:
        interval = 1.0 / max(1, self.settings.live_stream_fps)
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                jpeg = self.camera.capture_jpeg()
                if not jpeg:
                    raise CameraError("Captured live JPEG is empty")
                self.sequence += 1
                self.capture_count += 1
                self.jpeg_size_total += len(jpeg)
                self.buffer.put(
                    LiveFrame(
                        jpeg=jpeg,
                        sequence=self.sequence,
                        captured_monotonic=started,
                    )
                )
            except CameraError as exc:
                logging.error("[LIVE] Capture failed: %s", exc)

            elapsed = time.monotonic() - started
            self.capture_duration_total += elapsed
            delay = max(0.0, interval - elapsed)
            self.stop_event.wait(delay)

    def _publisher_loop(self) -> None:
        attempt = 0
        while not self.stop_event.is_set():
            try:
                if self.client.connected:
                    attempt = 0
                if not self.client.connected and not self.client.connecting:
                    attempt += 1
                    delay = exponential_backoff(
                        self.settings.live_stream_reconnect_base_seconds,
                        self.settings.live_stream_reconnect_max_seconds,
                        attempt,
                    )
                    self.reconnect_count += 1
                    logging.info(
                        "[LIVE] Reconnecting in %.1f seconds",
                        delay,
                    )
                    if self.stop_event.wait(delay):
                        break
                    self.client.connect()
                    if self.client.connecting:
                        self.stop_event.wait(0.25)
                    continue
            except Exception as exc:
                attempt += 1
                self.reconnect_count += 1
                delay = exponential_backoff(
                    self.settings.live_stream_reconnect_base_seconds,
                    self.settings.live_stream_reconnect_max_seconds,
                    attempt,
                )
                logging.warning(
                    "[LIVE] Connection failed: %s; reconnecting in %.1f seconds",
                    exc,
                    delay,
                )
                self.stop_event.wait(delay)
                continue

            attempt = 0
            frame = self.buffer.take()
            if frame is None:
                self.stop_event.wait(0.005)
                continue

            started = time.monotonic()
            sent = self.client.send_binary(frame.jpeg)
            duration = time.monotonic() - started
            self.send_duration_total += duration
            if sent:
                self.send_count += 1
            else:
                self.buffer.put(frame)

            self.stop_event.wait(
                max(0.0, 1.0 / max(1, self.settings.live_stream_fps) - duration)
            )

    def _stats_loop(self) -> None:
        next_stats = time.monotonic() + 5.0
        while not self.stop_event.is_set():
            remaining = next_stats - time.monotonic()
            if remaining > 0:
                self.stop_event.wait(remaining)
                continue
            interval = 5.0
            capture_fps = self.capture_count / interval
            send_fps = self.send_count / interval
            avg_capture = (
                self.capture_duration_total / self.capture_count
                if self.capture_count
                else 0.0
            )
            avg_jpeg_kb = (
                self.jpeg_size_total / self.capture_count / 1024
                if self.capture_count
                else 0.0
            )
            avg_send = (
                self.send_duration_total / self.send_count
                if self.send_count
                else 0.0
            )
            process = psutil.Process()
            logging.info(
                "[LIVE] Stats captureFPS=%.1f sendFPS=%.1f "
                "avgCapture=%.3fs avgSend=%.3fs avgJPEG=%.1fKB "
                "replaced=%d reconnects=%d cpu=%.1f%% ram=%.1fMB "
                "connection=%s",
                capture_fps,
                send_fps,
                avg_capture,
                avg_send,
                avg_jpeg_kb,
                self.buffer.replaced,
                self.reconnect_count,
                process.cpu_percent(interval=None),
                process.memory_info().rss / 1024 / 1024,
                "connected" if self.client.connected else "disconnected",
            )
            self.capture_count = 0
            self.send_count = 0
            self.capture_duration_total = 0.0
            self.jpeg_size_total = 0
            self.send_duration_total = 0.0
            next_stats = time.monotonic() + interval

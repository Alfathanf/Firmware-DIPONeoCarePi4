import logging
import threading
import time
from datetime import datetime, timezone

from camera.camera_manager import CameraError, CameraManager
from frame.frame_queue import Frame, FrameQueue


class FrameCaptureManager:
    def __init__(
        self,
        camera: CameraManager,
        queue: FrameQueue,
        mac_address: str,
        interval_seconds: float,
        stop_event: threading.Event,
    ) -> None:
        self.camera = camera
        self.queue = queue
        self.mac_address = mac_address
        self.interval_seconds = interval_seconds
        self.stop_event = stop_event
        self.sequence = 0

    def run(self) -> None:
        try:
            self.camera.start()
        except CameraError as exc:
            logging.error("[FRAME] Camera unavailable: %s", exc)
            return

        logging.info("[FRAME] Starting frame capture...")
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    jpeg = self.camera.capture_jpeg()
                    if not jpeg:
                        raise CameraError("Captured JPEG is empty")

                    now = datetime.now(timezone.utc)
                    timestamp = now.isoformat(timespec="milliseconds").replace(
                        "+00:00", "Z"
                    )
                    compact_mac = "".join(
                        character
                        for character in self.mac_address
                        if character.isalnum()
                    ).upper()
                    compact_timestamp = "".join(
                        character
                        for character in timestamp
                        if character.isdigit() or character in "TZ"
                    )
                    self.sequence += 1
                    frame = Frame(
                        capture_id=f"{compact_mac}_{compact_timestamp}",
                        timestamp=timestamp,
                        mac_address=self.mac_address,
                        jpeg=jpeg,
                        sequence=self.sequence,
                    )
                    dropped = self.queue.put(frame)
                    if dropped is not None:
                        logging.info(
                            "[FRAME] Superseded older frame id=%s",
                            dropped.capture_id,
                        )
                except CameraError as exc:
                    logging.error("[FRAME] Capture failed: %s", exc)

                elapsed = time.monotonic() - started
                delay = max(0.0, self.interval_seconds - elapsed)
                self.stop_event.wait(delay)
        finally:
            self.camera.stop()

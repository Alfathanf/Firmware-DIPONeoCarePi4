import logging
import threading
import time

from communication.api_client import ApiClient, ApiError
from config import Settings
from frame.frame_queue import FrameQueue


class FrameUploadError(RuntimeError):
    pass


class FrameAuthError(FrameUploadError):
    pass


class FrameUploader:
    def __init__(
        self,
        settings: Settings,
        frame_queue: FrameQueue,
        stop_event: threading.Event,
        registration_manager,
    ) -> None:
        self.settings = settings
        self.frame_queue = frame_queue
        self.stop_event = stop_event
        self.registration_manager = registration_manager
        self.last_error = None

    def upload_one(self) -> bool:
        registration = self.registration_manager.load()
        if registration is None or not registration.device_id or not registration.device_token:
            raise FrameUploadError("Saved Raspberry Pi identity is unavailable")

        frame = self.frame_queue.pop_latest()
        if frame is None:
            return False

        api_client = ApiClient(
            self.settings.backend_base_url,
            self.settings.frame_upload_timeout_seconds,
        )
        fields = {
            "macAddress": frame.mac_address,
            "captureId": frame.capture_id,
            "timestamp": frame.timestamp,
        }
        try:
            response = api_client.post_multipart(
                "api/devices/upload/frame",
                fields,
                "image",
                "frame.jpg",
                frame.jpeg,
                "image/jpeg",
                registration.device_token,
            )
        except ApiError as exc:
            self.frame_queue.restore_if_latest(frame)
            self.last_error = str(exc)
            raise FrameUploadError(str(exc)) from exc

        if 200 <= response.status_code < 300:
            self.last_error = None
            logging.info(
                "[FRAME] Upload successful: HTTP %d captureId=%s",
                response.status_code,
                frame.capture_id,
            )
            return True

        self.frame_queue.restore_if_latest(frame)
        if response.status_code in (401, 403):
            message = f"Authentication rejected: HTTP {response.status_code}"
            self.last_error = message
            raise FrameAuthError(message)

        message = f"HTTP {response.status_code}"
        self.last_error = message
        raise FrameUploadError(message)

    def run(self) -> None:
        logging.info("[FRAME] Starting frame uploader...")
        wait_seconds = 0
        while not self.stop_event.is_set():
            if wait_seconds > 0:
                self.stop_event.wait(wait_seconds)
                if self.stop_event.is_set():
                    break

            try:
                uploaded = self.upload_one()
                wait_seconds = 0.0
                if not uploaded:
                    self.stop_event.wait(0.25)
            except FrameAuthError as exc:
                logging.error("[FRAME] Upload failed: %s", exc)
                logging.error("[FRAME] Identity retained; no registration retry")
                wait_seconds = self.settings.frame_upload_retry_seconds
            except FrameUploadError as exc:
                logging.error("[FRAME] Upload failed: %s", exc)
                logging.info("[FRAME] Retaining latest frame and retrying")
                wait_seconds = self.settings.frame_upload_retry_seconds

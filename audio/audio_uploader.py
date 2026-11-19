import logging
import threading

from audio.audio_queue import AudioQueue
from communication.api_client import ApiClient, ApiError


class AudioUploadError(RuntimeError):
    pass


class AudioAuthError(AudioUploadError):
    pass


class AudioUploader:
    def __init__(
        self,
        settings,
        queue: AudioQueue,
        stop_event: threading.Event,
        registration_manager,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.stop_event = stop_event
        self.registration_manager = registration_manager
        self.last_error = None

    def upload_one(self) -> bool:
        registration = self.registration_manager.load()
        if (
            registration is None
            or not registration.device_id
            or not registration.device_token
        ):
            raise AudioUploadError("Saved Raspberry Pi identity is unavailable")

        recording = self.queue.pop_oldest()
        if recording is None:
            return False

        try:
            file_bytes = recording.file_path.read_bytes()
        except OSError as exc:
            self.queue.restore_oldest(recording)
            raise AudioUploadError(f"Unable to read pending WAV: {exc}") from exc

        api_client = ApiClient(
            self.settings.backend_base_url,
            self.settings.audio_upload_timeout_seconds,
        )
        fields = {
            "macAddress": recording.mac_address,
            "audioWindowId": recording.audio_window_id,
            "startedAt": recording.started_at,
            "durationSeconds": str(recording.duration_seconds),
        }
        try:
            response = api_client.post_multipart(
                "api/devices/upload/audio",
                fields,
                "audio",
                f"audio_{recording.audio_window_id}.wav",
                file_bytes,
                "audio/wav",
                registration.device_token,
            )
        except ApiError as exc:
            self.queue.restore_oldest(recording)
            self.last_error = str(exc)
            raise AudioUploadError(str(exc)) from exc

        if 200 <= response.status_code < 300:
            self.queue.acknowledge_success(recording)
            self.last_error = None
            logging.info(
                "[AUDIO] Upload successful: HTTP %d window=%s",
                response.status_code,
                recording.audio_window_id,
            )
            return True

        self.queue.restore_oldest(recording)
        if response.status_code in (401, 403):
            message = f"Authentication rejected: HTTP {response.status_code}"
            self.last_error = message
            raise AudioAuthError(message)

        message = f"HTTP {response.status_code}"
        self.last_error = message
        raise AudioUploadError(message)

    def run(self) -> None:
        logging.info("[AUDIO] Starting FIFO audio uploader...")
        wait_seconds = 0
        while not self.stop_event.is_set():
            if wait_seconds > 0:
                self.stop_event.wait(wait_seconds)
                if self.stop_event.is_set():
                    break
            try:
                uploaded = self.upload_one()
                wait_seconds = 0
                if not uploaded:
                    self.stop_event.wait(0.25)
            except AudioAuthError as exc:
                logging.error("[AUDIO] Upload failed: %s", exc)
                logging.error("[AUDIO] Identity retained; no registration retry")
                wait_seconds = self.settings.audio_upload_retry_seconds
            except AudioUploadError as exc:
                logging.error("[AUDIO] Upload failed: %s", exc)
                logging.info("[AUDIO] Retaining FIFO recording and retrying")
                wait_seconds = self.settings.audio_upload_retry_seconds

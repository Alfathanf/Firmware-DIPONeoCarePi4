import logging
import threading
import datetime
from dataclasses import dataclass
from typing import Optional

from communication.api_client import ApiClient, ApiError
from config import Settings
from device.identity import DeviceIdentity
from device.registration import RegistrationManager, RegistrationResult


class HeartbeatError(RuntimeError):
    pass


class HeartbeatAuthError(HeartbeatError):
    pass


@dataclass(frozen=True)
class HeartbeatResult:
    http_status: int
    device_id: str
    response_body: str


class HeartbeatService:
    def __init__(
        self,
        settings: Settings,
        registration_manager: RegistrationManager,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self.settings = settings
        self.registration_manager = registration_manager
        self.stop_event = stop_event or threading.Event()
        self.last_heartbeat_at = None
        self.last_error: Optional[str] = None

    def stop(self) -> None:
        self.stop_event.set()

    def get_identity(self) -> Optional[RegistrationResult]:
        identity = self.registration_manager.load()
        if identity is None:
            return None
        if not identity.device_id or not identity.device_token:
            return None
        return identity

    def send_once(self) -> HeartbeatResult:
        registration = self.get_identity()
        if registration is None:
            raise HeartbeatError(
                "Saved Raspberry Pi identity is unavailable or incomplete"
            )

        try:
            identity = DeviceIdentity.detect(self.settings.firmware_version)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HeartbeatError(
                f"Unable to refresh Raspberry Pi network identity: {exc}"
            ) from exc

        payload = {
            "macAddress": identity.mac_address,
            "localIp": identity.local_ip,
        }
        api_client = ApiClient(
            self.settings.backend_base_url,
            self.settings.heartbeat_timeout_seconds,
        )
        try:
            response = api_client.post_json(
                "api/devices/heartbeat",
                payload,
                device_token=registration.device_token,
            )
        except ApiError as exc:
            self.last_error = str(exc)
            raise HeartbeatError(str(exc)) from exc

        body = api_client.response_summary(response)
        if 200 <= response.status_code < 300:
            self.last_error = None
            self.last_heartbeat_at = datetime.datetime.now(datetime.timezone.utc)
            return HeartbeatResult(
                http_status=response.status_code,
                device_id=registration.device_id,
                response_body=body,
            )

        if response.status_code in (401, 403):
            message = f"Authentication rejected: HTTP {response.status_code}"
            self.last_error = message
            raise HeartbeatAuthError(message)

        message = f"Heartbeat failed: HTTP {response.status_code}"
        self.last_error = message
        raise HeartbeatError(message)

    def run(self) -> None:
        logging.info("[HEARTBEAT] Initializing...")
        logging.info("[HEARTBEAT] Starting heartbeat service...")

        while not self.stop_event.is_set():
            logging.info("[HEARTBEAT] Sending heartbeat...")
            try:
                result = self.send_once()
                logging.info(
                    "[HEARTBEAT] HTTP Status: %d",
                    result.http_status,
                )
                logging.info(
                    "[HEARTBEAT] Heartbeat successful (deviceId=%s).",
                    result.device_id,
                )
                wait_seconds = self.settings.heartbeat_interval_seconds
            except HeartbeatAuthError as exc:
                logging.error("[HEARTBEAT] Request failed.")
                logging.error("[HEARTBEAT] Reason: %s", exc)
                logging.error(
                    "[HEARTBEAT] Authentication is invalid; retaining saved identity."
                )
                wait_seconds = self.settings.heartbeat_retry_seconds
            except HeartbeatError as exc:
                logging.error("[HEARTBEAT] Request failed.")
                logging.error("[HEARTBEAT] Reason: %s", exc)
                logging.error("[HEARTBEAT] Retrying...")
                wait_seconds = self.settings.heartbeat_retry_seconds

            logging.info(
                "[HEARTBEAT] Next heartbeat in %d seconds.",
                wait_seconds,
            )
            self.stop_event.wait(wait_seconds)

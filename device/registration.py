import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from communication.api_client import ApiClient, ApiError
from config import Settings
from device.identity import DeviceIdentity


class RegistrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegistrationResult:
    device_id: str
    device_token: str
    paired: bool
    mac_address: str
    firmware_version: str
    local_ip: str

    def to_dict(self) -> dict:
        return {
            "deviceId": self.device_id,
            "deviceToken": self.device_token,
            "paired": self.paired,
            "macAddress": self.mac_address,
            "firmwareVersion": self.firmware_version,
            "localIp": self.local_ip,
        }


class RegistrationManager:
    def __init__(self, identity_file: Path) -> None:
        self.identity_file = identity_file

    def load(self) -> Optional[RegistrationResult]:
        if not self.identity_file.exists():
            return None

        try:
            data = json.loads(self.identity_file.read_text(encoding="utf-8"))
            device_id = str(data.get("deviceId", "")).strip()
            device_token = str(data.get("deviceToken", "")).strip()
            if not device_id or not device_token:
                logging.warning(
                    "Persistent identity file is incomplete; registration will be retried"
                )
                return None
            return RegistrationResult(
                device_id=device_id,
                device_token=device_token,
                paired=bool(data.get("paired", False)),
                mac_address=str(data.get("macAddress", "")),
                firmware_version=str(data.get("firmwareVersion", "")),
                local_ip=str(data.get("localIp", "")),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logging.warning(
                "Persistent identity file could not be read: %s", exc
            )
            return None

    def save(self, result: RegistrationResult) -> None:
        self.identity_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.identity_file.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps(result.to_dict(), indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary_file, 0o600)
        temporary_file.replace(self.identity_file)
        os.chmod(self.identity_file, 0o600)

    def register(
        self,
        identity: DeviceIdentity,
        settings: Settings,
    ) -> RegistrationResult:
        payload = {
            "macAddress": identity.mac_address,
            "localIp": identity.local_ip,
            "firmwareVersion": identity.firmware_version,
        }
        api_client = ApiClient(
            settings.backend_base_url,
            settings.request_timeout_seconds,
        )

        try:
            response = api_client.post_json(
                "api/devices/register",
                payload,
            )
        except ApiError as exc:
            raise RegistrationError(str(exc)) from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise RegistrationError(
                f"HTTP {response.status_code}: {api_client.response_summary(response)}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RegistrationError("Backend returned invalid JSON") from exc

        if body.get("success") is not True:
            raise RegistrationError("Backend registration response has success=false")

        data = body.get("data")
        if not isinstance(data, dict):
            raise RegistrationError("Backend response is missing data")

        device_id = str(data.get("deviceId", "")).strip()
        device_token = str(data.get("deviceToken", "")).strip()
        if not device_id or not device_token:
            raise RegistrationError(
                "Backend response is missing deviceId or deviceToken"
            )

        paired = data.get("paired", False)
        if not isinstance(paired, bool):
            raise RegistrationError("Backend response has invalid paired status")

        result = RegistrationResult(
            device_id=device_id,
            device_token=device_token,
            paired=paired,
            mac_address=identity.mac_address,
            firmware_version=identity.firmware_version,
            local_ip=identity.local_ip,
        )
        try:
            self.save(result)
        except OSError as exc:
            raise RegistrationError(
                f"Registration succeeded but identity could not be saved: {exc}"
            ) from exc
        return result

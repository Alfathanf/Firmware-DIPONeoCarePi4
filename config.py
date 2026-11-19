import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    backend_base_url: str
    firmware_version: str
    identity_file: Path
    request_timeout_seconds: float
    registration_retry_seconds: int
    heartbeat_interval_seconds: int = 15
    heartbeat_retry_seconds: int = 5
    heartbeat_timeout_seconds: float = 5.0

    @classmethod
    def from_environment(cls) -> "Settings":
        project_dir = Path(__file__).resolve().parent
        load_dotenv(project_dir / ".env")

        backend_base_url = os.getenv(
            "BACKEND_BASE_URL",
            "https://diponeocare.up.railway.app/",
        ).strip()
        if not backend_base_url:
            raise ValueError("BACKEND_BASE_URL cannot be empty")
        if not backend_base_url.startswith(("http://", "https://")):
            raise ValueError("BACKEND_BASE_URL must start with http:// or https://")

        identity_file_value = os.getenv(
            "IDENTITY_FILE",
            str(project_dir / "data" / "device_identity.json"),
        )
        identity_file = Path(identity_file_value).expanduser()

        try:
            request_timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
            retry_seconds = int(os.getenv("REGISTRATION_RETRY_SECONDS", "20"))
            heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "15"))
            heartbeat_retry = int(os.getenv("HEARTBEAT_RETRY_SECONDS", "5"))
            heartbeat_timeout = float(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "5"))
        except ValueError as exc:
            raise ValueError("Numeric environment settings are invalid") from exc

        if (
            request_timeout <= 0
            or heartbeat_timeout <= 0
            or retry_seconds < 1
            or heartbeat_interval < 1
            or heartbeat_retry < 1
        ):
            raise ValueError("Timeout and retry interval settings must be positive")

        return cls(
            backend_base_url=backend_base_url,
            firmware_version=os.getenv("FIRMWARE_VERSION", "1.0.0").strip(),
            identity_file=identity_file,
            request_timeout_seconds=request_timeout,
            registration_retry_seconds=retry_seconds,
            heartbeat_interval_seconds=heartbeat_interval,
            heartbeat_retry_seconds=heartbeat_retry,
            heartbeat_timeout_seconds=heartbeat_timeout,
        )

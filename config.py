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
    frame_capture_interval_seconds: float = 1.0
    frame_upload_timeout_seconds: float = 5.0
    frame_upload_retry_seconds: int = 5
    frame_queue_max_size: int = 1
    frame_image_format: str = "jpeg"
    frame_image_quality: int = 85
    frame_image_width: int = 640
    frame_image_height: int = 480
    audio_device: str = ""
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_bit_depth: int = 16
    audio_record_duration_seconds: int = 5
    audio_capture_interval_seconds: float = 5.0
    audio_queue_max_size: int = 3
    audio_upload_timeout_seconds: float = 5.0
    audio_upload_retry_seconds: int = 5
    audio_storage_dir: Path = Path("data/audio")
    live_stream_enabled: bool = True
    live_stream_fps: int = 15
    live_stream_width: int = 640
    live_stream_height: int = 480
    live_stream_jpeg_quality: int = 80
    live_stream_reconnect_base_seconds: float = 1.0
    live_stream_reconnect_max_seconds: float = 30.0
    live_stream_ping_interval_seconds: float = 20.0
    live_stream_ping_timeout_seconds: float = 10.0
    live_stream_max_pending_frames: int = 1

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
            frame_capture_interval = float(os.getenv("FRAME_CAPTURE_INTERVAL_SECONDS", "1"))
            frame_upload_timeout = float(os.getenv("FRAME_UPLOAD_TIMEOUT_SECONDS", "5"))
            frame_upload_retry = int(os.getenv("FRAME_UPLOAD_RETRY_SECONDS", "5"))
            frame_queue_max_size = int(os.getenv("FRAME_QUEUE_MAX_SIZE", "1"))
            frame_image_quality = int(os.getenv("FRAME_IMAGE_QUALITY", "85"))
            frame_image_width = int(os.getenv("FRAME_IMAGE_WIDTH", "640"))
            frame_image_height = int(os.getenv("FRAME_IMAGE_HEIGHT", "480"))
            audio_sample_rate = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
            audio_channels = int(os.getenv("AUDIO_CHANNELS", "1"))
            audio_bit_depth = int(os.getenv("AUDIO_BIT_DEPTH", "16"))
            audio_record_duration = int(os.getenv("AUDIO_RECORD_DURATION_SECONDS", "5"))
            audio_capture_interval = float(os.getenv("AUDIO_CAPTURE_INTERVAL_SECONDS", "5"))
            audio_queue_max_size = int(os.getenv("AUDIO_QUEUE_MAX_SIZE", "3"))
            audio_upload_timeout = float(os.getenv("AUDIO_UPLOAD_TIMEOUT_SECONDS", "5"))
            audio_upload_retry = int(os.getenv("AUDIO_UPLOAD_RETRY_SECONDS", "5"))
            live_stream_fps = int(os.getenv("LIVE_STREAM_FPS", "15"))
            live_stream_width = int(os.getenv("LIVE_STREAM_WIDTH", "640"))
            live_stream_height = int(os.getenv("LIVE_STREAM_HEIGHT", "480"))
            live_stream_jpeg_quality = int(os.getenv("LIVE_STREAM_JPEG_QUALITY", "80"))
            live_stream_reconnect_base = float(os.getenv("LIVE_STREAM_RECONNECT_BASE_SECONDS", "1"))
            live_stream_reconnect_max = float(os.getenv("LIVE_STREAM_RECONNECT_MAX_SECONDS", "30"))
            live_stream_ping_interval = float(os.getenv("LIVE_STREAM_PING_INTERVAL_SECONDS", "20"))
            live_stream_ping_timeout = float(os.getenv("LIVE_STREAM_PING_TIMEOUT_SECONDS", "10"))
            live_stream_max_pending = int(os.getenv("LIVE_STREAM_MAX_PENDING_FRAMES", "1"))
        except ValueError as exc:
            raise ValueError("Numeric environment settings are invalid") from exc

        if (
            request_timeout <= 0
            or heartbeat_timeout <= 0
            or retry_seconds < 1
            or heartbeat_interval < 1
            or heartbeat_retry < 1
            or frame_capture_interval <= 0
            or frame_upload_timeout <= 0
            or frame_upload_retry < 1
            or frame_queue_max_size < 1
            or frame_image_quality < 1
            or frame_image_quality > 100
            or frame_image_width < 1
            or frame_image_height < 1
            or audio_sample_rate != 16000
            or audio_channels != 1
            or audio_bit_depth != 16
            or audio_record_duration < 1
            or audio_capture_interval < 0
            or audio_queue_max_size < 1
            or audio_upload_timeout <= 0
            or audio_upload_retry < 1
            or live_stream_fps < 1
            or live_stream_width < 1
            or live_stream_height < 1
            or live_stream_jpeg_quality < 1
            or live_stream_jpeg_quality > 100
            or live_stream_reconnect_base <= 0
            or live_stream_reconnect_max < live_stream_reconnect_base
            or live_stream_ping_interval <= 0
            or live_stream_ping_timeout <= 0
            or live_stream_max_pending != 1
        ):
            raise ValueError("Frame, audio, and live stream settings must be positive")
        if live_stream_ping_interval <= live_stream_ping_timeout:
            raise ValueError(
                "LIVE_STREAM_PING_INTERVAL_SECONDS must be greater than "
                "LIVE_STREAM_PING_TIMEOUT_SECONDS"
            )

        audio_storage_value = os.getenv(
            "AUDIO_STORAGE_DIR",
            str(project_dir / "data" / "audio"),
        )
        audio_storage_dir = Path(audio_storage_value).expanduser()
        if not audio_storage_dir.is_absolute():
            audio_storage_dir = project_dir / audio_storage_dir

        return cls(
            backend_base_url=backend_base_url,
            firmware_version=os.getenv("FIRMWARE_VERSION", "1.0.0").strip(),
            identity_file=identity_file,
            request_timeout_seconds=request_timeout,
            registration_retry_seconds=retry_seconds,
            heartbeat_interval_seconds=heartbeat_interval,
            heartbeat_retry_seconds=heartbeat_retry,
            heartbeat_timeout_seconds=heartbeat_timeout,
            frame_capture_interval_seconds=frame_capture_interval,
            frame_upload_timeout_seconds=frame_upload_timeout,
            frame_upload_retry_seconds=frame_upload_retry,
            frame_queue_max_size=frame_queue_max_size,
            frame_image_format=os.getenv("FRAME_IMAGE_FORMAT", "jpeg").strip().lower(),
            frame_image_quality=frame_image_quality,
            frame_image_width=frame_image_width,
            frame_image_height=frame_image_height,
            audio_device=os.getenv("AUDIO_DEVICE", "").strip(),
            audio_sample_rate=audio_sample_rate,
            audio_channels=audio_channels,
            audio_bit_depth=audio_bit_depth,
            audio_record_duration_seconds=audio_record_duration,
            audio_capture_interval_seconds=audio_capture_interval,
            audio_queue_max_size=audio_queue_max_size,
            audio_upload_timeout_seconds=audio_upload_timeout,
            audio_upload_retry_seconds=audio_upload_retry,
            audio_storage_dir=audio_storage_dir,
            live_stream_enabled=os.getenv("LIVE_STREAM_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on"),
            live_stream_fps=live_stream_fps,
            live_stream_width=live_stream_width,
            live_stream_height=live_stream_height,
            live_stream_jpeg_quality=live_stream_jpeg_quality,
            live_stream_reconnect_base_seconds=live_stream_reconnect_base,
            live_stream_reconnect_max_seconds=live_stream_reconnect_max,
            live_stream_ping_interval_seconds=live_stream_ping_interval,
            live_stream_ping_timeout_seconds=live_stream_ping_timeout,
            live_stream_max_pending_frames=live_stream_max_pending,
        )

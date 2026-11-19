import argparse
import logging
import signal
import threading
import time
from datetime import datetime, timezone

from config import Settings
from device.identity import DeviceIdentity
from device.registration import RegistrationError, RegistrationManager
from device.heartbeat import HeartbeatAuthError, HeartbeatError, HeartbeatService
from camera.camera_manager import CameraError, CameraManager
from frame.frame_queue import Frame, FrameQueue
from frame.frame_capture import FrameCaptureManager
from frame.frame_uploader import FrameUploader
from audio.audio_queue import AudioQueue
from audio.audio_recorder import AudioRecorder, AudioError
from audio.audio_uploader import AudioUploader
from live_stream.live_stream_publisher import LiveStreamPublisher


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_frame_upload_once(settings, manager, registration, identity) -> int:
    camera = CameraManager(
        settings.frame_image_width,
        settings.frame_image_height,
        settings.frame_image_quality,
    )
    try:
        camera.start()
        jpeg = camera.capture_jpeg()
    except (CameraError, RuntimeError) as exc:
        logging.error("[FRAME] Capture failed: %s", exc)
        return 1
    finally:
        camera.stop()

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    compact_mac = "".join(
        character for character in identity.mac_address if character.isalnum()
    ).upper()
    compact_timestamp = "".join(
        character for character in timestamp if character.isdigit() or character in "TZ"
    )
    frame_queue = FrameQueue(settings.frame_queue_max_size)
    frame_queue.put(
        Frame(
            capture_id=f"{compact_mac}_{compact_timestamp}",
            timestamp=timestamp,
            mac_address=identity.mac_address,
            jpeg=jpeg,
            sequence=1,
        )
    )
    uploader = FrameUploader(
        settings,
        frame_queue,
        threading.Event(),
        manager,
    )
    try:
        uploader.upload_one()
        return 0
    except Exception as exc:
        logging.error("[FRAME] Upload failed: %s", exc)
        return 1


def run_audio_upload_once(settings, manager, identity) -> int:
    queue = AudioQueue(
        settings.audio_storage_dir,
        settings.audio_queue_max_size,
    )
    recorder = AudioRecorder(
        settings,
        identity.mac_address,
        queue,
        threading.Event(),
    )
    try:
        recording = recorder.record_once()
        if not queue.put(recording):
            logging.error("[AUDIO] Queue full; recording retained on disk")
            return 1
    except AudioError as exc:
        logging.error("[AUDIO] Recording failed: %s", exc)
        return 1

    uploader = AudioUploader(
        settings,
        queue,
        threading.Event(),
        manager,
    )
    try:
        if uploader.upload_one():
            return 0
        return 1
    except Exception as exc:
        logging.error("[AUDIO] Upload failed: %s", exc)
        return 1


def run_live_stream_once(settings, manager, identity) -> int:
    if not settings.live_stream_enabled:
        logging.error("[LIVE] Live streaming is disabled")
        return 1
    stop_event = threading.Event()
    publisher = LiveStreamPublisher(
        settings,
        manager,
        identity,
        stop_event,
    )

    def handle_stop(_signum, _frame) -> None:
        logging.info("[LIVE] Shutdown requested.")
        publisher.stop()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)
    publisher.run()
    return 0


def run_services(settings, manager, identity) -> int:
    heartbeat = HeartbeatService(settings, manager)
    frame_queue = FrameQueue(settings.frame_queue_max_size)
    camera = CameraManager(
        settings.frame_image_width,
        settings.frame_image_height,
        settings.frame_image_quality,
    )
    stop_event = threading.Event()
    capture = FrameCaptureManager(
        camera,
        frame_queue,
        identity.mac_address,
        settings.frame_capture_interval_seconds,
        stop_event,
        start_camera=not settings.live_stream_enabled,
    )
    uploader = FrameUploader(settings, frame_queue, stop_event, manager)
    audio_queue = AudioQueue(
        settings.audio_storage_dir,
        settings.audio_queue_max_size,
    )
    audio_recorder = AudioRecorder(
        settings,
        identity.mac_address,
        audio_queue,
        stop_event,
    )
    audio_uploader = AudioUploader(
        settings,
        audio_queue,
        stop_event,
        manager,
    )
    live_publisher = None
    live_thread = None
    if settings.live_stream_enabled:
        live_publisher = LiveStreamPublisher(
            settings,
            manager,
            identity,
            stop_event,
            camera=camera,
        )
        live_thread = threading.Thread(
            target=live_publisher.run,
            name="live-stream",
            daemon=True,
        )

    def handle_stop(_signum, _frame) -> None:
        logging.info("[SHUTDOWN] Shutdown requested.")
        heartbeat.stop()
        stop_event.set()
        if live_publisher is not None:
            live_publisher.stop()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    heartbeat_thread = threading.Thread(
        target=heartbeat.run,
        name="heartbeat",
        daemon=True,
    )
    capture_thread = threading.Thread(
        target=capture.run,
        name="frame-capture",
        daemon=True,
    )
    uploader_thread = threading.Thread(
        target=uploader.run,
        name="frame-uploader",
        daemon=True,
    )
    audio_capture_thread = threading.Thread(
        target=audio_recorder.run,
        name="audio-capture",
        daemon=True,
    )
    audio_uploader_thread = threading.Thread(
        target=audio_uploader.run,
        name="audio-uploader",
        daemon=True,
    )
    heartbeat_thread.start()
    capture_thread.start()
    uploader_thread.start()
    audio_capture_thread.start()
    audio_uploader_thread.start()
    if live_thread is not None:
        live_thread.start()

    stop_event.wait()
    camera.stop()
    heartbeat_thread.join(timeout=2)
    capture_thread.join(timeout=2)
    uploader_thread.join(timeout=2)
    audio_recorder.stop()
    audio_capture_thread.join(timeout=5)
    audio_uploader_thread.join(timeout=2)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DIPONeoCare Raspberry Pi registration, heartbeat, and frame upload"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one registration check and exit",
    )
    parser.add_argument(
        "--heartbeat",
        action="store_true",
        help="Send one heartbeat using saved identity and exit",
    )
    parser.add_argument(
        "--frame-upload",
        action="store_true",
        help="Capture one frame and upload it once using saved identity",
    )
    parser.add_argument(
        "--audio-upload",
        action="store_true",
        help="Record one WAV window and upload it once using saved identity",
    )
    parser.add_argument(
        "--live-stream",
        action="store_true",
        help="Run live WebSocket streaming only",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        settings = Settings.from_environment()
        identity = DeviceIdentity.detect(settings.firmware_version)
    except (OSError, RuntimeError, ValueError) as exc:
        logging.error("Unable to initialize device identity: %s", exc)
        return 1

    manager = RegistrationManager(settings.identity_file)

    registration = manager.load()
    if registration is not None:
        logging.info(
            "Device is already registered (deviceId=%s, paired=%s)",
            registration.device_id,
            registration.paired,
        )
        logging.info(
            "MAC=%s localIP=%s softwareVersion=%s",
            identity.mac_address,
            identity.local_ip,
            identity.firmware_version,
        )
        if args.frame_upload:
            return run_frame_upload_once(settings, manager, registration, identity)
        if args.audio_upload:
            return run_audio_upload_once(settings, manager, identity)
        if args.live_stream:
            return run_live_stream_once(settings, manager, identity)
        if args.heartbeat:
            heartbeat = HeartbeatService(settings, manager)
            try:
                result = heartbeat.send_once()
                logging.info(
                    "[HEARTBEAT] HTTP Status: %d",
                    result.http_status,
                )
                logging.info(
                    "[HEARTBEAT] Heartbeat successful (deviceId=%s).",
                    result.device_id,
                )
                return 0
            except (HeartbeatError, HeartbeatAuthError) as exc:
                logging.error("[HEARTBEAT] Request failed: %s", exc)
                return 1
        if args.once:
            return 0

        return run_services(settings, manager, identity)

    logging.info(
        "Registering Raspberry Pi (MAC=%s localIP=%s softwareVersion=%s)",
        identity.mac_address,
        identity.local_ip,
        identity.firmware_version,
    )

    should_continue = not args.once
    if args.heartbeat:
        logging.error(
            "[HEARTBEAT] Saved Raspberry Pi identity is unavailable; --heartbeat does not register"
        )
        return 1
    if args.frame_upload:
        logging.error(
            "[FRAME] Saved Raspberry Pi identity is unavailable; --frame-upload does not register"
        )
        return 1
    if args.audio_upload:
        logging.error(
            "[AUDIO] Saved Raspberry Pi identity is unavailable; --audio-upload does not register"
        )
        return 1
    if args.live_stream:
        logging.error(
            "[LIVE] Saved Raspberry Pi identity is unavailable; --live-stream does not register"
        )
        return 1
    while True:
        try:
            result = manager.register(identity, settings)
            if result.paired:
                logging.info(
                    "Registration successful (deviceId=%s). Device is paired.",
                    result.device_id,
                )
            else:
                logging.info(
                    "Registration successful (deviceId=%s). Device is not paired yet.",
                    result.device_id,
                )
            if args.once:
                return 0

            return run_services(settings, manager, identity)
        except RegistrationError as exc:
            logging.error("Registration failed: %s", exc)
            if not should_continue:
                return 1

            logging.info(
                "Retrying registration in %d seconds...",
                settings.registration_retry_seconds,
            )
            time.sleep(settings.registration_retry_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

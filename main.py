import argparse
import logging
import signal
import time

from config import Settings
from device.identity import DeviceIdentity
from device.registration import RegistrationError, RegistrationManager
from device.heartbeat import HeartbeatAuthError, HeartbeatError, HeartbeatService


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DIPONeoCare Raspberry Pi device registration"
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

        heartbeat = HeartbeatService(settings, manager)

        def handle_stop(_signum, _frame) -> None:
            logging.info("[HEARTBEAT] Shutdown requested.")
            heartbeat.stop()

        signal.signal(signal.SIGINT, handle_stop)
        signal.signal(signal.SIGTERM, handle_stop)
        heartbeat.run()
        return 0

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

            heartbeat = HeartbeatService(settings, manager)

            def handle_stop(_signum, _frame) -> None:
                logging.info("[HEARTBEAT] Shutdown requested.")
                heartbeat.stop()

            signal.signal(signal.SIGINT, handle_stop)
            signal.signal(signal.SIGTERM, handle_stop)
            heartbeat.run()
            return 0
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

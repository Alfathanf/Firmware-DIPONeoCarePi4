import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from config import Settings
from device.identity import DeviceIdentity
from device.registration import RegistrationManager, RegistrationResult
from device.heartbeat import (
    HeartbeatAuthError,
    HeartbeatError,
    HeartbeatService,
)


class HeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.identity_file = Path(self.temp_dir.name) / "device_identity.json"
        self.settings = Settings(
            backend_base_url="https://diponeocare.example/",
            firmware_version="1.0.0",
            identity_file=self.identity_file,
            request_timeout_seconds=10,
            registration_retry_seconds=20,
            heartbeat_interval_seconds=15,
            heartbeat_retry_seconds=5,
            heartbeat_timeout_seconds=5,
        )
        self.manager = RegistrationManager(self.identity_file)
        self.manager.save(
            RegistrationResult(
                device_id="raspi-device",
                device_token="raspi-secret-token",
                paired=True,
                mac_address="DC:A6:32:12:34:56",
                firmware_version="1.0.0",
                local_ip="192.168.1.50",
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("communication.api_client.requests.post")
    @patch("device.heartbeat.DeviceIdentity.detect")
    def test_success_payload_endpoint_and_auth_header(self, detect, post):
        detect.return_value = DeviceIdentity(
            mac_address="DC:A6:32:12:34:56",
            local_ip="192.168.1.50",
            firmware_version="1.0.0",
        )
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"success":true}'
        post.return_value = response

        result = HeartbeatService(self.settings, self.manager).send_once()

        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.device_id, "raspi-device")
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://diponeocare.example/api/devices/heartbeat",
        )
        self.assertEqual(
            kwargs["json"],
            {"macAddress": "DC:A6:32:12:34:56", "localIp": "192.168.1.50"},
        )
        self.assertEqual(
            kwargs["headers"],
            {
                "Content-Type": "application/json",
                "x-device-token": "raspi-secret-token",
            },
        )
        self.assertNotIn("deviceId", kwargs["json"])

    def test_missing_identity_does_not_send_request(self):
        missing_manager = RegistrationManager(
            Path(self.temp_dir.name) / "missing.json"
        )
        heartbeat = HeartbeatService(self.settings, missing_manager)
        with self.assertRaises(HeartbeatError):
            heartbeat.send_once()

    @patch("communication.api_client.requests.post")
    @patch("device.heartbeat.DeviceIdentity.detect")
    def test_http_error_is_reported(self, detect, post):
        detect.return_value = DeviceIdentity(
            "DC:A6:32:12:34:56", "192.168.1.50", "1.0.0"
        )
        response = requests.Response()
        response.status_code = 500
        response._content = b'{"message":"failure"}'
        post.return_value = response

        with self.assertRaises(HeartbeatError):
            HeartbeatService(self.settings, self.manager).send_once()

    @patch("communication.api_client.requests.post")
    @patch("device.heartbeat.DeviceIdentity.detect")
    def test_invalid_token_does_not_reregister(self, detect, post):
        detect.return_value = DeviceIdentity(
            "DC:A6:32:12:34:56", "192.168.1.50", "1.0.0"
        )
        response = requests.Response()
        response.status_code = 401
        response._content = b'{"success":false}'
        post.return_value = response

        heartbeat = HeartbeatService(self.settings, self.manager)
        with self.assertRaises(HeartbeatAuthError):
            heartbeat.send_once()
        self.assertIsNotNone(self.manager.load())

    @patch("communication.api_client.requests.post")
    @patch("device.heartbeat.DeviceIdentity.detect")
    def test_connection_error_is_reported_without_crash(self, detect, post):
        detect.return_value = DeviceIdentity(
            "DC:A6:32:12:34:56", "192.168.1.50", "1.0.0"
        )
        post.side_effect = requests.ConnectionError("offline")

        with self.assertRaises(HeartbeatError):
            HeartbeatService(self.settings, self.manager).send_once()

    @patch("communication.api_client.requests.post")
    @patch("device.heartbeat.DeviceIdentity.detect")
    def test_timeout_is_reported(self, detect, post):
        detect.return_value = DeviceIdentity(
            "DC:A6:32:12:34:56", "192.168.1.50", "1.0.0"
        )
        post.side_effect = requests.Timeout("timeout")

        with self.assertRaises(HeartbeatError):
            HeartbeatService(self.settings, self.manager).send_once()

    def test_stop_event_interrupts_wait(self):
        heartbeat = HeartbeatService(self.settings, self.manager)
        heartbeat.stop()
        self.assertTrue(heartbeat.stop_event.is_set())

    @patch.object(HeartbeatService, "send_once")
    def test_configured_interval_is_used(self, send_once):
        from device.heartbeat import HeartbeatResult

        send_once.return_value = HeartbeatResult(
            http_status=200,
            device_id="raspi-device",
            response_body='{"success":true}',
        )
        heartbeat = HeartbeatService(
            self.settings,
            self.manager,
            threading.Event(),
        )
        heartbeat.stop_event.wait = unittest.mock.Mock(
            side_effect=lambda _seconds: heartbeat.stop()
        )

        heartbeat.run()

        heartbeat.stop_event.wait.assert_called_once_with(15)


if __name__ == "__main__":
    unittest.main()

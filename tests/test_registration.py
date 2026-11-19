import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from config import Settings
from device.identity import DeviceIdentity
from device.registration import RegistrationManager, RegistrationResult


class RegistrationManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.identity_file = Path(self.temp_dir.name) / "device_identity.json"
        self.settings = Settings(
            backend_base_url="https://diponeocare.example/",
            firmware_version="1.0.0",
            identity_file=self.identity_file,
            request_timeout_seconds=10,
            registration_retry_seconds=20,
        )
        self.identity = DeviceIdentity(
            mac_address="DC:A6:32:12:34:56",
            local_ip="192.168.1.50",
            firmware_version="1.0.0",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("communication.api_client.requests.post")
    def test_paired_registration_is_saved_and_not_logged_as_token(self, post):
        response = requests.Response()
        response.status_code = 200
        response._content = (
            b'{"success":true,"data":{"deviceId":"raspi-1",'
            b'"deviceToken":"secret-token","paired":true}}'
        )
        post.return_value = response

        manager = RegistrationManager(self.identity_file)
        result = manager.register(self.identity, self.settings)

        self.assertEqual(result.device_id, "raspi-1")
        self.assertTrue(result.paired)
        saved = manager.load()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.device_token, "secret-token")
        self.assertEqual(saved.mac_address, "DC:A6:32:12:34:56")

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://diponeocare.example/api/devices/register",
        )
        self.assertEqual(
            kwargs["json"],
            {
                "macAddress": "DC:A6:32:12:34:56",
                "localIp": "192.168.1.50",
                "firmwareVersion": "1.0.0",
            },
        )
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})

    @patch("communication.api_client.requests.post")
    def test_unpaired_registration_is_still_successful(self, post):
        response = requests.Response()
        response.status_code = 200
        response._content = (
            b'{"success":true,"data":{"deviceId":"raspi-2",'
            b'"deviceToken":"secret-token","paired":false}}'
        )
        post.return_value = response

        result = RegistrationManager(self.identity_file).register(
            self.identity, self.settings
        )
        self.assertFalse(result.paired)

    def test_existing_identity_prevents_new_registration(self):
        manager = RegistrationManager(self.identity_file)
        existing = manager.load()
        self.assertIsNone(existing)

        manager.save(
            RegistrationResult(
                device_id="raspi-existing",
                device_token="stored-token",
                paired=True,
                mac_address="DC:A6:32:12:34:56",
                firmware_version="1.0.0",
                local_ip="192.168.1.50",
            )
        )
        self.assertIsNotNone(manager.load())


if __name__ == "__main__":
    unittest.main()

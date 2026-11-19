import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from config import Settings
from device.registration import RegistrationManager, RegistrationResult
from frame.frame_queue import Frame, FrameQueue
from frame.frame_uploader import (
    FrameAuthError,
    FrameUploader,
)


class FrameUploaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.identity_file = Path(self.temp_dir.name) / "device_identity.json"
        self.settings = Settings(
            backend_base_url="https://diponeocare.example/",
            firmware_version="1.0.0",
            identity_file=self.identity_file,
            request_timeout_seconds=10,
            registration_retry_seconds=20,
            frame_capture_interval_seconds=1,
            frame_upload_timeout_seconds=5,
            frame_upload_retry_seconds=5,
            frame_queue_max_size=1,
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
        self.queue = FrameQueue(1)
        self.queue.put(
            Frame(
                capture_id="DCA632123456_20261119T000000000Z",
                timestamp="2026-11-19T00:00:00.000Z",
                mac_address="DC:A6:32:12:34:56",
                jpeg=b"\xff\xd8jpeg\xff\xd9",
                sequence=1,
            )
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("communication.api_client.requests.post")
    def test_successful_upload_uses_multipart_contract(self, post):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"success":true}'
        post.return_value = response

        uploader = FrameUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        self.assertTrue(uploader.upload_one())

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://diponeocare.example/api/devices/upload/frame",
        )
        self.assertEqual(
            kwargs["headers"],
            {"x-device-token": "raspi-secret-token"},
        )
        self.assertEqual(
            kwargs["data"]["macAddress"],
            "DC:A6:32:12:34:56",
        )
        self.assertEqual(
            kwargs["data"]["captureId"],
            "DCA632123456_20261119T000000000Z",
        )
        self.assertEqual(
            kwargs["data"]["timestamp"],
            "2026-11-19T00:00:00.000Z",
        )
        filename, file_bytes, content_type = kwargs["files"]["image"]
        self.assertEqual(filename, "frame.jpg")
        self.assertEqual(file_bytes, b"\xff\xd8jpeg\xff\xd9")
        self.assertEqual(content_type, "image/jpeg")

    @patch("communication.api_client.requests.post")
    def test_http_error_restores_frame(self, post):
        response = requests.Response()
        response.status_code = 500
        response._content = b'{"success":false}'
        post.return_value = response

        uploader = FrameUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        with self.assertRaises(Exception):
            uploader.upload_one()
        self.assertEqual(len(self.queue), 1)

    @patch("communication.api_client.requests.post")
    def test_timeout_restores_frame(self, post):
        post.side_effect = requests.Timeout("timeout")
        uploader = FrameUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        with self.assertRaises(Exception):
            uploader.upload_one()
        self.assertEqual(len(self.queue), 1)

    @patch("communication.api_client.requests.post")
    def test_auth_error_does_not_delete_identity(self, post):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{"success":false}'
        post.return_value = response

        uploader = FrameUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        with self.assertRaises(FrameAuthError):
            uploader.upload_one()
        self.assertIsNotNone(self.manager.load())

    def test_missing_identity_does_not_pop_frame(self):
        missing_manager = RegistrationManager(
            Path(self.temp_dir.name) / "missing.json"
        )
        uploader = FrameUploader(
            self.settings,
            self.queue,
            threading.Event(),
            missing_manager,
        )
        with self.assertRaises(Exception):
            uploader.upload_one()
        self.assertEqual(len(self.queue), 1)

    def test_stop_event_is_graceful(self):
        stop_event = threading.Event()
        stop_event.set()
        uploader = FrameUploader(
            self.settings,
            self.queue,
            stop_event,
            self.manager,
        )
        uploader.run()
        self.assertTrue(stop_event.is_set())


if __name__ == "__main__":
    unittest.main()

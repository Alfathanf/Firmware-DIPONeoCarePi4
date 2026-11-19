import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from audio.audio_queue import AudioQueue, AudioRecording
from audio.audio_uploader import AudioAuthError, AudioUploader
from config import Settings
from device.registration import RegistrationManager, RegistrationResult


class AudioUploaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.identity_file = self.storage_dir / "device_identity.json"
        self.settings = Settings(
            backend_base_url="https://diponeocare.example/",
            firmware_version="1.0.0",
            identity_file=self.identity_file,
            request_timeout_seconds=10,
            registration_retry_seconds=20,
            audio_sample_rate=16000,
            audio_channels=1,
            audio_bit_depth=16,
            audio_record_duration_seconds=5,
            audio_queue_max_size=3,
            audio_upload_timeout_seconds=5,
            audio_upload_retry_seconds=5,
            audio_storage_dir=self.storage_dir,
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
        wav_path = self.storage_dir / "first.wav"
        wav_path.write_bytes(b"RIFF" + b"\x00" * 44)
        self.recording = AudioRecording(
            audio_window_id="DCA632123456_20261119T000000000Z",
            started_at="2026-11-19T00:00:00.000Z",
            duration_seconds=5,
            mac_address="DC:A6:32:12:34:56",
            file_path=wav_path,
        )
        self.queue = AudioQueue(self.storage_dir, 3)
        self.queue.put(self.recording)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("communication.api_client.requests.post")
    def test_successful_multipart_upload_deletes_file(self, post):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"success":true}'
        post.return_value = response

        uploader = AudioUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        self.assertTrue(uploader.upload_one())

        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://diponeocare.example/api/devices/upload/audio",
        )
        self.assertEqual(
            kwargs["headers"],
            {"x-device-token": "raspi-secret-token"},
        )
        self.assertEqual(
            kwargs["data"],
            {
                "macAddress": "DC:A6:32:12:34:56",
                "audioWindowId": "DCA632123456_20261119T000000000Z",
                "startedAt": "2026-11-19T00:00:00.000Z",
                "durationSeconds": "5",
            },
        )
        filename, file_bytes, content_type = kwargs["files"]["audio"]
        self.assertEqual(
            filename,
            "audio_DCA632123456_20261119T000000000Z.wav",
        )
        self.assertTrue(file_bytes.startswith(b"RIFF"))
        self.assertEqual(content_type, "audio/wav")
        self.assertFalse(self.recording.file_path.exists())

    @patch("communication.api_client.requests.post")
    def test_timeout_retains_fifo_file(self, post):
        post.side_effect = requests.Timeout("timeout")
        uploader = AudioUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        with self.assertRaises(Exception):
            uploader.upload_one()
        self.assertTrue(self.recording.file_path.exists())
        self.assertEqual(len(self.queue), 1)

    @patch("communication.api_client.requests.post")
    def test_http_error_retains_fifo_file(self, post):
        response = requests.Response()
        response.status_code = 500
        response._content = b'{"success":false}'
        post.return_value = response
        uploader = AudioUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        with self.assertRaises(Exception):
            uploader.upload_one()
        self.assertTrue(self.recording.file_path.exists())

    @patch("communication.api_client.requests.post")
    def test_auth_error_does_not_delete_identity(self, post):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{"success":false}'
        post.return_value = response
        uploader = AudioUploader(
            self.settings,
            self.queue,
            threading.Event(),
            self.manager,
        )
        with self.assertRaises(AudioAuthError):
            uploader.upload_one()
        self.assertIsNotNone(self.manager.load())
        self.assertTrue(self.recording.file_path.exists())


if __name__ == "__main__":
    unittest.main()

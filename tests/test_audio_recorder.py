import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from audio.audio_queue import AudioQueue
from audio.audio_recorder import AudioError, AudioRecorder
from config import Settings


class AudioRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(
            backend_base_url="https://diponeocare.example/",
            firmware_version="1.0.0",
            identity_file=Path(self.temp_dir.name) / "identity.json",
            request_timeout_seconds=10,
            registration_retry_seconds=20,
            audio_device="default",
            audio_sample_rate=16000,
            audio_channels=1,
            audio_bit_depth=16,
            audio_record_duration_seconds=5,
            audio_capture_interval_seconds=5,
            audio_queue_max_size=3,
            audio_upload_timeout_seconds=5,
            audio_upload_retry_seconds=5,
            audio_storage_dir=Path(self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_arecord_command_matches_contract_and_creates_wav(self):
        def fake_popen(command, stdout=None, stderr=None):
            process = Mock()
            target = Path(command[-1])
            target.write_bytes(b"RIFF" + b"\x00" * 44)
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            process.poll.return_value = 0
            return process

        queue = AudioQueue(self.settings.audio_storage_dir, 3)
        recorder = AudioRecorder(
            self.settings,
            "DC:A6:32:12:34:56",
            queue,
            threading.Event(),
            popen=fake_popen,
        )

        recording = recorder.record_once()

        self.assertEqual(recording.duration_seconds, 5)
        self.assertEqual(recording.file_path.suffix, ".wav")
        self.assertEqual(recording.mac_address, "DC:A6:32:12:34:56")

    def test_arecord_error_is_reported(self):
        process = Mock()
        process.returncode = 1
        process.communicate.return_value = (b"", b"device unavailable")
        process.poll.return_value = 1

        queue = AudioQueue(self.settings.audio_storage_dir, 3)
        recorder = AudioRecorder(
            self.settings,
            "DC:A6:32:12:34:56",
            queue,
            threading.Event(),
            popen=lambda *args, **kwargs: process,
        )

        with self.assertRaises(AudioError):
            recorder.record_once()


if __name__ == "__main__":
    unittest.main()

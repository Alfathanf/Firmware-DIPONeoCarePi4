import tempfile
import unittest
from pathlib import Path

from audio.audio_queue import AudioQueue, AudioRecording


class AudioQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_recording(self, name: str) -> AudioRecording:
        wav_path = self.storage_dir / f"{name}.wav"
        wav_path.write_bytes(b"RIFF" + b"\x00" * 44)
        return AudioRecording(
            audio_window_id=name,
            started_at="2026-11-19T00:00:00.000Z",
            duration_seconds=5,
            mac_address="DC:A6:32:12:34:56",
            file_path=wav_path,
        )

    def test_fifo_keeps_insert_order(self):
        queue = AudioQueue(self.storage_dir, max_size=3)
        self.assertTrue(queue.put(self.make_recording("first")))
        self.assertTrue(queue.put(self.make_recording("second")))

        self.assertEqual(queue.pop_oldest().audio_window_id, "first")
        self.assertEqual(queue.pop_oldest().audio_window_id, "second")

    def test_queue_full_does_not_discard_recording(self):
        queue = AudioQueue(self.storage_dir, max_size=1)
        first = self.make_recording("first")
        second = self.make_recording("second")

        self.assertTrue(queue.put(first))
        self.assertFalse(queue.put(second))
        self.assertEqual(len(queue), 1)
        self.assertTrue(second.file_path.exists())
        self.assertTrue(second.metadata_path().exists())

    def test_success_removes_wav_and_metadata(self):
        queue = AudioQueue(self.storage_dir, max_size=1)
        recording = self.make_recording("success")
        queue.put(recording)
        queue.acknowledge_success(recording)

        self.assertFalse(recording.file_path.exists())
        self.assertFalse(recording.metadata_path().exists())

    def test_failed_upload_is_restored_at_fifo_head(self):
        queue = AudioQueue(self.storage_dir, max_size=2)
        first = self.make_recording("first")
        second = self.make_recording("second")
        queue.put(first)
        queue.put(second)

        head = queue.pop_oldest()
        queue.restore_oldest(head)

        self.assertEqual(queue.pop_oldest().audio_window_id, "first")


if __name__ == "__main__":
    unittest.main()

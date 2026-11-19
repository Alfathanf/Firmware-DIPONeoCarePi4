import unittest
from unittest.mock import Mock

from camera.camera_manager import CameraError, CameraManager


class CameraManagerTests(unittest.TestCase):
    def test_capture_file_writes_jpeg_bytes_to_buffer(self):
        camera = Mock()

        def capture_file(buffer, format=None):
            self.assertEqual(format, "jpeg")
            buffer.write(b"\xff\xd8mock-jpeg\xff\xd9")

        camera.capture_file.side_effect = capture_file
        manager = CameraManager(width=640, height=480, quality=85)
        manager.camera = camera

        jpeg = manager.capture_jpeg()

        self.assertEqual(jpeg, b"\xff\xd8mock-jpeg\xff\xd9")
        camera.capture_file.assert_called_once()

    def test_capture_file_rejects_invalid_output(self):
        camera = Mock()
        camera.capture_file.side_effect = lambda buffer, format=None: buffer.write(
            b"not-jpeg"
        )
        manager = CameraManager(width=640, height=480, quality=85)
        manager.camera = camera

        with self.assertRaises(CameraError):
            manager.capture_jpeg()

    def test_stop_closes_camera(self):
        camera = Mock()
        manager = CameraManager(width=640, height=480, quality=85)
        manager.camera = camera

        manager.stop()

        camera.stop.assert_called_once_with()
        camera.close.assert_called_once_with()
        self.assertIsNone(manager.camera)


if __name__ == "__main__":
    unittest.main()

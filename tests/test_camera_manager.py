import unittest
import sys
from types import ModuleType
from unittest.mock import Mock, patch

from camera.camera_manager import CameraError, CameraManager


class CameraManagerTests(unittest.TestCase):
    def test_start_does_not_apply_unsupported_jpeg_control(self):
        camera = Mock()
        camera.options = {}
        camera.create_video_configuration.return_value = {"main": {"format": "MJPEG"}}
        picamera_module = ModuleType("picamera2")
        picamera_module.Picamera2 = Mock(return_value=camera)

        with patch.dict(sys.modules, {"picamera2": picamera_module}):
            manager = CameraManager(width=640, height=480, quality=80)
            manager.start(fps=15)

        controls = camera.set_controls.call_args.args[0]
        self.assertIn("FrameDurationLimits", controls)
        self.assertNotIn("JpegQuality", controls)
        self.assertNotIn("JpegQuality", str(controls))
        self.assertEqual(camera.options["quality"], 80)
        camera.start.assert_called_once_with()
        camera.configure.assert_called_once()

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

    def test_mjpeg_buffer_is_returned_as_valid_jpeg(self):
        camera = Mock()
        camera.capture_buffer.return_value = b"\xff\xd8mock-mjpeg\xff\xd9"
        manager = CameraManager(width=640, height=480, quality=80)
        manager.camera = camera
        manager._started_format = "MJPEG"

        jpeg = manager.capture_jpeg()

        self.assertEqual(jpeg, b"\xff\xd8mock-mjpeg\xff\xd9")
        camera.capture_buffer.assert_called_once_with("main")

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

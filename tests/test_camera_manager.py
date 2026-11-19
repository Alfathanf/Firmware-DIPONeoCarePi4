import unittest
import sys
from enum import Enum
from types import ModuleType
from unittest.mock import Mock, patch

from camera.camera_manager import CameraError, CameraManager


class FakeQuality(Enum):
    VERY_LOW = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4


class CameraManagerTests(unittest.TestCase):
    def test_start_does_not_apply_unsupported_jpeg_control(self):
        camera = Mock()
        camera.options = {}
        camera.create_video_configuration.return_value = {"main": {"format": "YUV420"}}
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
        self.assertEqual(
            camera.create_video_configuration.call_args.kwargs["main"]["format"],
            "YUV420",
        )
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

    def test_raw_capture_buffer_is_not_treated_as_jpeg(self):
        camera = Mock()
        camera.capture_buffer.return_value = b"raw-yuyv-frame"
        camera.capture_file.side_effect = lambda buffer, format=None: buffer.write(
            b"\xff\xd8mock-jpeg\xff\xd9"
        )
        manager = CameraManager(width=640, height=480, quality=80)
        manager.camera = camera

        jpeg = manager.capture_jpeg()

        self.assertEqual(jpeg, b"\xff\xd8mock-jpeg\xff\xd9")
        camera.capture_file.assert_called_once()
        camera.capture_buffer.assert_not_called()

    def test_live_encoder_delivers_only_complete_jpeg_frames(self):
        camera = Mock()
        camera.options = {}
        encoder = Mock()
        camera.create_video_configuration.return_value = {"main": {"format": "NV12"}}
        picamera_module = ModuleType("picamera2")
        picamera_module.__path__ = []
        picamera_module.Picamera2 = Mock(return_value=camera)
        encoders_module = ModuleType("picamera2.encoders")
        encoders_module.JpegEncoder = Mock()
        encoders_module.MJPEGEncoder = Mock(return_value=encoder)
        encoders_module.Quality = FakeQuality
        encoders_module._hw_encoder_available = True
        outputs_module = ModuleType("picamera2.outputs")

        class Output:
            pass

        outputs_module.Output = Output
        received = []
        manager = CameraManager(width=640, height=480, quality=80)

        with patch.dict(sys.modules, {
            "picamera2": picamera_module,
            "picamera2.encoders": encoders_module,
            "picamera2.outputs": outputs_module,
        }):
            manager.start_live_stream(15, received.append)

        controls = camera.set_controls.call_args.args[0]
        self.assertNotIn("JpegQuality", controls)
        self.assertEqual(
            camera.create_video_configuration.call_args.kwargs["main"]["format"],
            "NV12",
        )
        self.assertIs(
            camera.start_encoder.call_args.kwargs["quality"],
            FakeQuality.VERY_HIGH,
        )
        output = camera.start_encoder.call_args.args[1]
        output.outputframe(b"\x00not-a-jpeg")
        output.outputframe(b"\xff\xd8one-frame\xff\xd9")
        self.assertEqual(received, [b"\xff\xd8one-frame\xff\xd9"])
        manager.stop()
        camera.stop_encoder.assert_called_once_with(encoder)

    def test_software_encoder_uses_requested_jpeg_quality(self):
        camera = Mock()
        camera.options = {}
        camera.create_video_configuration.return_value = {"main": {"format": "YUV420"}}
        picamera_module = ModuleType("picamera2")
        picamera_module.__path__ = []
        picamera_module.Picamera2 = Mock(return_value=camera)
        encoders_module = ModuleType("picamera2.encoders")
        encoder = Mock()
        encoders_module.JpegEncoder = Mock(return_value=encoder)
        encoders_module._hw_encoder_available = False
        outputs_module = ModuleType("picamera2.outputs")

        class Output:
            pass

        outputs_module.Output = Output
        manager = CameraManager(width=640, height=480, quality=73)
        with patch.dict(sys.modules, {
            "picamera2": picamera_module,
            "picamera2.encoders": encoders_module,
            "picamera2.outputs": outputs_module,
        }):
            manager.start_live_stream(15, Mock())

        encoders_module.JpegEncoder.assert_called_once_with(q=73)
        self.assertEqual(
            camera.create_video_configuration.call_args.kwargs["main"]["format"],
            "YUV420",
        )
        self.assertIsNone(camera.start_encoder.call_args.kwargs["quality"])
        manager.stop()

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

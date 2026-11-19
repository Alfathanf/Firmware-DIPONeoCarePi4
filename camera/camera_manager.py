import logging
import io
import threading


class CameraError(RuntimeError):
    pass


class CameraManager:
    def __init__(self, width: int, height: int, quality: int) -> None:
        self.width = width
        self.height = height
        self.quality = quality
        self.camera = None
        self._lock = threading.RLock()
        self._started_format = None
        self._started_fps = None

    def start(self, fps: int = 5) -> None:
        with self._lock:
            if self.camera is not None:
                return
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CameraError(
                "Picamera2 is unavailable. Install it with apt in Raspberry Pi OS."
            ) from exc

        with self._lock:
            if self.camera is not None:
                return
            try:
                camera = Picamera2()
                if hasattr(camera, "options"):
                    camera.options["quality"] = max(1, min(int(self.quality), 100))
                config = camera.create_video_configuration(
                    main={
                        "size": (self.width, self.height),
                        "format": "MJPEG",
                    }
                )
                camera.configure(config)
                fps = max(1, min(int(fps), 30))
                frame_duration_us = max(1000, 1_000_000 // fps)
                camera.set_controls({
                    "FrameDurationLimits": (
                        frame_duration_us,
                        frame_duration_us,
                    ),
                })
                camera.start()
                self.camera = camera
                self._started_format = "MJPEG"
                self._started_fps = fps
            except Exception as exc:
                try:
                    if "camera" in locals():
                        camera.close()
                except Exception:
                    pass
                self.camera = None
                raise CameraError(f"Unable to initialize camera: {exc}") from exc

    def capture_jpeg(self) -> bytes:
        with self._lock:
            if self.camera is None:
                raise CameraError("Camera has not been initialized")

            try:
                capture_buffer = getattr(self.camera, "capture_buffer", None)
                if callable(capture_buffer) and self._started_format == "MJPEG":
                    jpeg = bytes(capture_buffer("main"))
                    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                        raise CameraError("Picamera2 MJPEG capture returned invalid JPEG bytes")
                    return jpeg
                return self._capture_jpeg_fallback()
            except CameraError:
                raise
            except Exception as exc:
                raise CameraError(f"JPEG frame capture failed: {exc}") from exc

    def _capture_jpeg_fallback(self) -> bytes:
        buffer = io.BytesIO()
        try:
            capture_file = getattr(self.camera, "capture_file", None)
            if callable(capture_file):
                capture_file(buffer, format="jpeg")
                jpeg = buffer.getvalue()
                if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                    raise CameraError("Picamera2 capture did not return valid JPEG bytes")
                return jpeg

            try:
                from PIL import Image
            except ImportError as exc:
                raise CameraError(
                    "Pillow is unavailable for JPEG fallback capture"
                ) from exc

            frame = self.camera.capture_array()
            with io.BytesIO() as output:
                Image.fromarray(frame).save(
                    output,
                    format="JPEG",
                    quality=self.quality,
                )
                jpeg = output.getvalue()
            if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                raise CameraError("Captured frame did not produce valid JPEG bytes")
            return jpeg
        except CameraError:
            raise
        except Exception as exc:
            raise CameraError(f"JPEG frame capture fallback failed: {exc}") from exc
        finally:
            buffer.close()

    def stop(self) -> None:
        with self._lock:
            if self.camera is not None:
                try:
                    self.camera.stop()
                except Exception as exc:
                    logging.warning("[FRAME] Camera stop warning: %s", exc)
                try:
                    close = getattr(self.camera, "close", None)
                    if callable(close):
                        close()
                except Exception as exc:
                    logging.warning("[FRAME] Camera close warning: %s", exc)
                self.camera = None
            self._started_format = None
            self._started_fps = None

import logging
import io


class CameraError(RuntimeError):
    pass


class CameraManager:
    def __init__(self, width: int, height: int, quality: int) -> None:
        self.width = width
        self.height = height
        self.quality = quality
        self.camera = None

    def start(self) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CameraError(
                "Picamera2 is unavailable. Install it with apt in Raspberry Pi OS."
            ) from exc

        try:
            self.camera = Picamera2()
            config = self.camera.create_video_configuration(
                main={
                    "size": (self.width, self.height),
                    "format": "RGB888",
                }
            )
            self.camera.configure(config)
            self.camera.start()
        except Exception as exc:
            self.camera = None
            raise CameraError(f"Unable to initialize camera: {exc}") from exc

    def capture_jpeg(self) -> bytes:
        if self.camera is None:
            raise CameraError("Camera has not been initialized")

        buffer = io.BytesIO()
        try:
            capture_file = getattr(self.camera, "capture_file", None)
            if not callable(capture_file):
                return self._capture_array_as_jpeg()

            capture_file(buffer, format="jpeg")
            jpeg = buffer.getvalue()
            if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                raise CameraError("Picamera2 capture did not return valid JPEG bytes")
            return jpeg
        except CameraError:
            raise
        except Exception as exc:
            raise CameraError(f"JPEG frame capture failed: {exc}") from exc
        finally:
            buffer.close()

    def _capture_array_as_jpeg(self) -> bytes:
        try:
            from PIL import Image

            frame = self.camera.capture_array()
            output = io.BytesIO()
            try:
                Image.fromarray(frame).save(
                    output,
                    format="JPEG",
                    quality=self.quality,
                )
                jpeg = output.getvalue()
                if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                    raise CameraError("Captured frame did not produce valid JPEG bytes")
                return jpeg
            finally:
                output.close()
        except CameraError:
            raise
        except Exception as exc:
            raise CameraError(f"JPEG frame capture fallback failed: {exc}") from exc

    def stop(self) -> None:
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

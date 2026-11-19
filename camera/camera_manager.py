import logging
from typing import Optional


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
        try:
            return bytes(self.camera.capture_jpeg())
        except TypeError:
            try:
                import io
                from PIL import Image

                frame = self.camera.capture_array()
                output = io.BytesIO()
                Image.fromarray(frame).save(
                    output,
                    format="JPEG",
                    quality=self.quality,
                )
                return output.getvalue()
            except Exception as exc:
                raise CameraError(f"JPEG frame capture failed: {exc}") from exc
        except Exception as exc:
            raise CameraError(f"JPEG frame capture failed: {exc}") from exc

    def stop(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
            except Exception as exc:
                logging.warning("[FRAME] Camera stop warning: %s", exc)
            self.camera = None

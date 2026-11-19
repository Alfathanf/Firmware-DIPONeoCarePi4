import io
import logging
import threading
from typing import Callable, Optional


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
        self._live_encoder = None
        self._live_output = None

    def _create_camera(self, fps: int, stream_format: str) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CameraError(
                "Picamera2 is unavailable. Install it with apt in Raspberry Pi OS."
            ) from exc

        camera = None
        try:
            camera = Picamera2()
            if hasattr(camera, "options"):
                camera.options["quality"] = max(1, min(int(self.quality), 100))
            config = camera.create_video_configuration(
                main={
                    "size": (self.width, self.height),
                    "format": stream_format,
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
            self._started_format = stream_format
            self._started_fps = fps
        except Exception as exc:
            if camera is not None:
                try:
                    camera.close()
                except Exception:
                    logging.warning("[FRAME] Camera cleanup after startup failure failed")
            self.camera = None
            raise CameraError(f"Unable to initialize camera: {exc}") from exc

    def start(self, fps: int = 5) -> None:
        with self._lock:
            if self.camera is not None:
                return
            self._create_camera(fps, "YUV420")

    @staticmethod
    def _hardware_quality(quality, requested: int):
        profiles = (
            (25, quality.VERY_LOW),
            (35, quality.LOW),
            (50, quality.MEDIUM),
            (65, quality.HIGH),
            (80, quality.VERY_HIGH),
        )
        return min(profiles, key=lambda profile: abs(profile[0] - requested))[1]

    def start_live_stream(
        self,
        fps: int,
        on_frame: Callable[[bytes], None],
    ) -> None:
        with self._lock:
            if self.camera is not None:
                raise CameraError(
                    "Camera is already running without the live encoder; "
                    "stop it before starting live streaming"
                )

            try:
                from picamera2.encoders import JpegEncoder
                from picamera2.outputs import Output
            except ImportError as exc:
                raise CameraError(
                    "Picamera2 does not provide the required JPEG encoder/output API"
                ) from exc

            try:
                try:
                    from picamera2.encoders import (
                        MJPEGEncoder,
                        Quality,
                        _hw_encoder_available,
                    )
                except ImportError:
                    _hw_encoder_available = False

                if _hw_encoder_available:
                    encoder = MJPEGEncoder()
                    stream_format = "NV12"
                    encoder_quality = self._hardware_quality(Quality, self.quality)
                    logging.info(
                        "[LIVE] Using Picamera2 hardware MJPEG encoder "
                        "(quality profile nearest to %d)",
                        self.quality,
                    )
                else:
                    encoder = JpegEncoder(q=self.quality)
                    stream_format = "YUV420"
                    encoder_quality = None
                    logging.warning(
                        "[LIVE] Hardware MJPEG encoder is unavailable; "
                        "using Picamera2 software JPEG encoder"
                    )
            except Exception as exc:
                raise CameraError(f"Unable to create Picamera2 JPEG encoder: {exc}") from exc

            class LatestJpegOutput(Output):
                def outputframe(
                    self,
                    frame,
                    keyframe=True,
                    timestamp=None,
                    packet=None,
                    audio=False,
                ):
                    if audio or frame is None:
                        return
                    jpeg = bytes(frame)
                    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                        logging.error(
                            "[LIVE] Picamera2 encoder emitted an invalid JPEG frame"
                        )
                        return
                    try:
                        on_frame(jpeg)
                    except Exception:
                        logging.exception("[LIVE] JPEG output callback failed")

            output = LatestJpegOutput()
            try:
                self._create_camera(fps, stream_format)
                self._live_encoder = encoder
                self._live_output = output
                self.camera.start_encoder(
                    encoder,
                    output,
                    quality=encoder_quality,
                )
            except Exception as exc:
                self.stop()
                if isinstance(exc, CameraError):
                    raise
                raise CameraError(f"Unable to start live JPEG encoder: {exc}") from exc

    def capture_jpeg(self) -> bytes:
        with self._lock:
            if self.camera is None:
                raise CameraError("Camera has not been initialized")

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
                raise CameraError(f"JPEG frame capture failed: {exc}") from exc
            finally:
                buffer.close()

    def stop(self) -> None:
        with self._lock:
            if self.camera is not None:
                if self._live_encoder is not None:
                    try:
                        self.camera.stop_encoder(self._live_encoder)
                    except Exception as exc:
                        logging.warning("[LIVE] Encoder stop warning: %s", exc)
                    self._live_encoder = None
                    self._live_output = None
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

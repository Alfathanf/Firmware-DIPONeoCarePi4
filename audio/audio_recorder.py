import logging
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from audio.audio_queue import AudioQueue, AudioRecording


class AudioError(RuntimeError):
    pass


class AudioRecorder:
    def __init__(
        self,
        settings,
        mac_address: str,
        queue: AudioQueue,
        stop_event: threading.Event,
        popen=subprocess.Popen,
    ) -> None:
        self.settings = settings
        self.mac_address = mac_address
        self.queue = queue
        self.stop_event = stop_event
        self.Popen = popen
        self.process = None
        self.sequence = 0

    def stop(self) -> None:
        self.stop_event.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def record_once(self) -> AudioRecording:
        started = datetime.now(timezone.utc)
        started_at = started.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        compact_mac = "".join(
            character for character in self.mac_address if character.isalnum()
        ).upper()
        compact_timestamp = "".join(
            character for character in started_at
            if character.isdigit() or character in "TZ"
        )
        window_id = f"{compact_mac}_{compact_timestamp}"
        target = self.settings.audio_storage_dir / f"{window_id}.wav"

        command = [
            "arecord",
            "-q",
            "-t",
            "wav",
            "-r",
            str(self.settings.audio_sample_rate),
            "-c",
            str(self.settings.audio_channels),
            "-f",
            f"S{self.settings.audio_bit_depth}_LE",
        ]
        if self.settings.audio_device:
            command.extend(["-D", self.settings.audio_device])
        command.extend(["-d", str(self.settings.audio_record_duration_seconds)])
        command.append(str(target))

        try:
            self.process = self.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = self.process.communicate(
                timeout=self.settings.audio_record_duration_seconds + 5
            )
            return_code = self.process.returncode
        except subprocess.TimeoutExpired as exc:
            if self.process is not None:
                self.process.terminate()
                self.process.wait(timeout=2)
            raise AudioError("ALSA recording timed out") from exc
        except FileNotFoundError as exc:
            raise AudioError(
                "arecord is unavailable. Install alsa-utils and verify USB microphone."
            ) from exc
        except Exception as exc:
            raise AudioError(f"ALSA recording failed: {exc}") from exc
        finally:
            self.process = None

        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise AudioError(
                f"arecord exited with status {return_code}: {detail or 'unknown ALSA error'}"
            )
        if not target.exists() or target.stat().st_size <= 44:
            raise AudioError("Recording did not produce a valid WAV file")

        return AudioRecording(
            audio_window_id=window_id,
            started_at=started_at,
            duration_seconds=self.settings.audio_record_duration_seconds,
            mac_address=self.mac_address,
            file_path=target,
        )

    def run(self) -> None:
        logging.info("[AUDIO] Starting USB microphone recorder...")
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                recording = self.record_once()
                if not self.queue.put(recording):
                    logging.error(
                        "[AUDIO] FIFO queue full; retaining recording on disk and stopping capture: %s",
                        recording.file_path,
                    )
                    self.stop_event.wait(
                        self.settings.audio_capture_interval_seconds
                    )
            except AudioError as exc:
                logging.error("[AUDIO] Recording failed: %s", exc)

            elapsed = time.monotonic() - started
            delay = max(0.0, self.settings.audio_capture_interval_seconds - elapsed)
            self.stop_event.wait(delay)

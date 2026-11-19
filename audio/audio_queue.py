import json
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Iterator, Optional


@dataclass(frozen=True)
class AudioRecording:
    audio_window_id: str
    started_at: str
    duration_seconds: int
    mac_address: str
    file_path: Path

    def metadata_path(self) -> Path:
        return self.file_path.with_suffix(".json")


class AudioQueue:
    def __init__(self, storage_dir: Path, max_size: int) -> None:
        if max_size < 1:
            raise ValueError("Audio queue capacity must be at least 1")
        self.storage_dir = storage_dir
        self.max_size = max_size
        self._items: Deque[AudioRecording] = deque()
        self._lock = threading.Lock()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._load_pending()

    def _load_pending(self) -> None:
        for metadata_path in sorted(self.storage_dir.glob("*.json")):
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                wav_path = Path(data["filePath"])
                if not wav_path.exists():
                    continue
                recording = AudioRecording(
                    audio_window_id=str(data["audioWindowId"]),
                    started_at=str(data["startedAt"]),
                    duration_seconds=int(data["durationSeconds"]),
                    mac_address=str(data["macAddress"]),
                    file_path=wav_path,
                )
                if any(
                    item.audio_window_id == recording.audio_window_id
                    for item in self._items
                ):
                    continue
                self._items.append(recording)
                if len(self._items) >= self.max_size:
                    break
            except (json.JSONDecodeError, KeyError, OSError, ValueError):
                continue

    def put(self, recording: AudioRecording) -> bool:
        with self._lock:
            metadata = {
                "audioWindowId": recording.audio_window_id,
                "startedAt": recording.started_at,
                "durationSeconds": recording.duration_seconds,
                "macAddress": recording.mac_address,
                "filePath": str(recording.file_path),
            }
            recording.metadata_path().write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )
            if len(self._items) >= self.max_size:
                return False
            self._items.append(recording)
            return True

    def pop_oldest(self) -> Optional[AudioRecording]:
        with self._lock:
            if not self._items:
                self._load_pending()
            if not self._items:
                return None
            return self._items.popleft()

    def restore_oldest(self, recording: AudioRecording) -> None:
        with self._lock:
            if not any(
                item.audio_window_id == recording.audio_window_id
                for item in self._items
            ):
                self._items.appendleft(recording)

    def acknowledge_success(self, recording: AudioRecording) -> None:
        metadata_path = recording.metadata_path()
        metadata_path.unlink(missing_ok=True)
        recording.file_path.unlink(missing_ok=True)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __iter__(self) -> Iterator[AudioRecording]:
        with self._lock:
            return iter(tuple(self._items))

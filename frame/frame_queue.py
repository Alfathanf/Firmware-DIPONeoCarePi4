import threading
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Frame:
    capture_id: str
    timestamp: str
    mac_address: str
    jpeg: bytes
    sequence: int


class FrameQueue:
    def __init__(self, max_size: int) -> None:
        if max_size < 1:
            raise ValueError("Frame queue capacity must be at least 1")
        self.max_size = max_size
        self._frames: List[Frame] = []
        self._lock = threading.Lock()

    def put(self, frame: Frame) -> Optional[Frame]:
        with self._lock:
            dropped = None
            self._frames.append(frame)
            self._frames.sort(key=lambda item: item.sequence, reverse=True)
            if len(self._frames) > self.max_size:
                dropped = self._frames.pop()
            return dropped

    def get_latest(self) -> Optional[Frame]:
        with self._lock:
            if not self._frames:
                return None
            return max(self._frames, key=lambda item: item.sequence)

    def pop_latest(self) -> Optional[Frame]:
        with self._lock:
            if not self._frames:
                return None
            frame = max(self._frames, key=lambda item: item.sequence)
            self._frames.remove(frame)
            return frame

    def restore_if_latest(self, frame: Frame) -> bool:
        with self._lock:
            if any(item.capture_id == frame.capture_id for item in self._frames):
                return False
            if self._frames:
                newest_sequence = max(item.sequence for item in self._frames)
                if newest_sequence > frame.sequence:
                    return False
            self._frames.append(frame)
            self._frames.sort(key=lambda item: item.sequence, reverse=True)
            if len(self._frames) > self.max_size:
                self._frames.pop()
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

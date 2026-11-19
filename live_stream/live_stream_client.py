import logging
import threading
from typing import Callable, Optional

try:
    import websocket
except ImportError:
    websocket = None


class LiveStreamClient:
    def __init__(
        self,
        url: str,
        headers: dict,
        ping_interval_seconds: float,
        ping_timeout_seconds: float,
        on_binary: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        self.url = url
        self.headers = headers
        self.ping_interval_seconds = ping_interval_seconds
        self.ping_timeout_seconds = ping_timeout_seconds
        self.on_binary = on_binary
        self.connection = None
        self.connected = False
        self.reconnect_count = 0
        self.connecting = False
        self._lock = threading.RLock()
        self._connection_thread = None

    def connect(self) -> None:
        if websocket is None:
            raise RuntimeError(
                "websocket-client is unavailable. Install requirements.txt dependencies."
            )
        with self._lock:
            if self.connected or self.connecting:
                return
            self.connecting = True
        with self._lock:
            self.connection = websocket.WebSocketApp(
                self.url,
                header=[
                    f"{name}: {value}"
                    for name, value in self.headers.items()
                ],
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_pong=self._on_pong,
            )

        self.reconnect_count += 1
        self._connection_thread = threading.Thread(
            target=self.connection.run_forever,
            kwargs={
                "ping_interval": self.ping_interval_seconds,
                "ping_timeout": self.ping_timeout_seconds,
            },
            name="live-websocket",
            daemon=True,
        )
        self._connection_thread.start()

    def _on_open(self, _connection) -> None:
        with self._lock:
            self.connected = True
            self.connecting = False
        logging.info("[LIVE] WebSocket handshake successful")

    def _on_message(self, _connection, message) -> None:
        if isinstance(message, bytes):
            if self.on_binary is not None:
                self.on_binary(message)
            return
        logging.debug("[LIVE] Backend text message ignored")

    def _on_error(self, _connection, error) -> None:
        logging.error("[LIVE] WebSocket error: %s", error)

    def _on_close(
        self,
        _connection,
        close_status_code=None,
        close_message=None,
    ) -> None:
        with self._lock:
            self.connected = False
            self.connecting = False
        logging.warning(
            "[LIVE] WebSocket disconnected status=%s",
            close_status_code,
        )

    def _on_pong(
        self,
        _connection,
        _data,
    ) -> None:
        logging.debug("[LIVE] WebSocket pong received")

    def send_binary(self, jpeg: bytes) -> bool:
        with self._lock:
            if not self.connected or self.connection is None:
                return False
            try:
                self.connection.send(jpeg, opcode=websocket.ABNF.OPCODE_BINARY)
                return True
            except Exception as exc:
                logging.error("[LIVE] Binary frame send failed: %s", exc)
                self.connected = False
                return False

    def close(self) -> None:
        with self._lock:
            self.connected = False
            self.connecting = False
            if self.connection is not None:
                try:
                    self.connection.close()
                except Exception as exc:
                    logging.warning("[LIVE] WebSocket close warning: %s", exc)
            self.connection = None

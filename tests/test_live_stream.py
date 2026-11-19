import threading
import unittest
import os
from unittest.mock import Mock, patch

from config import Settings
from live_stream.live_stream_client import LiveStreamClient
from live_stream.live_stream_publisher import (
    LatestFrameBuffer,
    LiveFrame,
    build_live_url,
    exponential_backoff,
)


class LiveStreamTests(unittest.TestCase):
    def test_live_url_and_device_id(self):
        url = build_live_url(
            "https://diponeocare.up.railway.app/",
            "raspi-device",
        )
        self.assertEqual(
            url,
            "wss://diponeocare.up.railway.app/api/devices/"
            "raspi-device/live/ingest",
        )

    def test_headers_include_raspberry_mac_and_token(self):
        client = LiveStreamClient(
            "wss://example.test/api/devices/raspi/live/ingest",
            {
                "x-device-mac": "DC:A6:32:12:34:56",
                "x-device-token": "raspi-token",
            },
            20,
            10,
        )
        self.assertEqual(
            client.headers["x-device-mac"],
            "DC:A6:32:12:34:56",
        )
        self.assertEqual(
            client.headers["x-device-token"],
            "raspi-token",
        )

    def test_latest_frame_replaces_previous_frame(self):
        buffer = LatestFrameBuffer()
        buffer.put(LiveFrame(b"first", 1, 1.0))
        buffer.put(LiveFrame(b"second", 2, 2.0))

        frame = buffer.take()
        self.assertEqual(frame.jpeg, b"second")
        self.assertEqual(buffer.replaced, 1)
        self.assertIsNone(buffer.take())

    def test_binary_send_uses_websocket_binary_opcode(self):
        fake_websocket = Mock()
        fake_websocket.ABNF.OPCODE_BINARY = 2
        with patch(
            "live_stream.live_stream_client.websocket",
            fake_websocket,
        ):
            client = LiveStreamClient(
                "wss://example.test/live",
                {"x-device-token": "raspi-token"},
                20,
                10,
            )
            client.connected = True
            client.connection = Mock()

            self.assertTrue(client.send_binary(b"\xff\xd8jpeg\xff\xd9"))
            client.connection.send.assert_called_once()
            self.assertEqual(
                client.connection.send.call_args.kwargs["opcode"],
                2,
            )

    def test_exponential_backoff_is_bounded(self):
        self.assertEqual(exponential_backoff(1, 30, 1), 1)
        self.assertEqual(exponential_backoff(1, 30, 3), 4)
        self.assertEqual(exponential_backoff(1, 30, 10), 30)

    def test_graceful_stop_clears_buffer_and_client(self):
        fake_websocket = Mock()
        fake_websocket.ABNF.OPCODE_BINARY = 2
        with patch(
            "live_stream.live_stream_client.websocket",
            fake_websocket,
        ):
            client = LiveStreamClient(
                "wss://example.test/live",
                {},
                20,
                10,
            )
            connection = Mock()
            client.connection = connection
            client.connected = True
            client.close()
            connection.close.assert_called_once()
            self.assertFalse(client.connected)

    def test_disconnect_callback_clears_connected_state(self):
        client = LiveStreamClient(
            "wss://example.test/live",
            {},
            20,
            10,
        )
        client.connected = True
        client._on_close(None, 1006, "disconnected")
        self.assertFalse(client.connected)

    def test_ping_configuration_is_retained(self):
        client = LiveStreamClient(
            "wss://example.test/live",
            {},
            ping_interval_seconds=20,
            ping_timeout_seconds=10,
        )
        self.assertEqual(client.ping_interval_seconds, 20)
        self.assertEqual(client.ping_timeout_seconds, 10)

    def test_equal_ping_interval_and_timeout_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be greater"):
            LiveStreamClient(
                "wss://example.test/live",
                {},
                ping_interval_seconds=20,
                ping_timeout_seconds=20,
            )

    def test_non_jpeg_binary_payload_is_rejected(self):
        client = LiveStreamClient(
            "wss://example.test/live",
            {},
            ping_interval_seconds=20,
            ping_timeout_seconds=10,
        )
        client.connected = True
        client.connection = Mock()

        self.assertFalse(client.send_binary(b"raw-yuyv-frame"))
        client.connection.send.assert_not_called()

    def test_connect_does_not_start_duplicate_threads(self):
        fake_websocket = Mock()
        connection = Mock()
        fake_websocket.WebSocketApp.return_value = connection
        fake_thread = Mock()
        with patch(
            "live_stream.live_stream_client.websocket",
            fake_websocket,
        ), patch(
            "live_stream.live_stream_client.threading.Thread",
            return_value=fake_thread,
        ) as thread_factory:
            client = LiveStreamClient(
                "wss://example.test/live",
                {},
                ping_interval_seconds=20,
                ping_timeout_seconds=10,
            )
            client.connect()
            client.connect()

        thread_factory.assert_called_once()
        fake_thread.start.assert_called_once()

    def test_settings_validate_ping_relationship(self):
        environment = {
            "BACKEND_BASE_URL": "https://example.test/",
            "LIVE_STREAM_PING_INTERVAL_SECONDS": "20",
            "LIVE_STREAM_PING_TIMEOUT_SECONDS": "20",
        }
        with patch("config.load_dotenv"), patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ValueError,
                "LIVE_STREAM_PING_INTERVAL_SECONDS must be greater",
            ):
                Settings.from_environment()

    def test_settings_default_ping_timeout_is_ten_seconds(self):
        with patch("config.load_dotenv"), patch.dict(
            os.environ,
            {"BACKEND_BASE_URL": "https://example.test/"},
            clear=True,
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.live_stream_ping_interval_seconds, 20)
        self.assertEqual(settings.live_stream_ping_timeout_seconds, 10)


if __name__ == "__main__":
    unittest.main()

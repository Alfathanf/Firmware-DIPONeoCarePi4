import unittest

from frame.frame_queue import Frame, FrameQueue


def make_frame(sequence: int) -> Frame:
    return Frame(
        capture_id=f"frame-{sequence}",
        timestamp=f"2026-11-19T00:00:0{sequence}Z",
        mac_address="DC:A6:32:12:34:56",
        jpeg=b"jpeg",
        sequence=sequence,
    )


class FrameQueueTests(unittest.TestCase):
    def test_latest_frame_replaces_oldest(self):
        queue = FrameQueue(max_size=2)
        queue.put(make_frame(1))
        queue.put(make_frame(2))
        queue.put(make_frame(3))

        self.assertEqual(len(queue), 2)
        latest = queue.pop_latest()
        self.assertEqual(latest.capture_id, "frame-3")
        self.assertEqual(queue.pop_latest().capture_id, "frame-2")

    def test_bounded_queue_never_exceeds_limit(self):
        queue = FrameQueue(max_size=1)
        for sequence in range(1, 20):
            queue.put(make_frame(sequence))

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue.get_latest().capture_id, "frame-19")

    def test_restore_does_not_replace_newer_frame(self):
        queue = FrameQueue(max_size=2)
        queue.put(make_frame(3))

        self.assertFalse(queue.restore_if_latest(make_frame(2)))
        self.assertEqual(queue.get_latest().capture_id, "frame-3")

    def test_failed_frame_is_restored_for_retry(self):
        queue = FrameQueue(max_size=1)
        frame = make_frame(1)
        queue.put(frame)
        popped = queue.pop_latest()

        self.assertTrue(queue.restore_if_latest(popped))
        self.assertEqual(queue.get_latest().capture_id, "frame-1")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from motion_module.camera import USBCameraManager, list_video_devices


class ListVideoDevicesTests(unittest.TestCase):
    def test_no_devices_when_the_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(list_video_devices(directory), [])

    def test_finds_and_sorts_video_devices_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("video1", "video10", "video0", "audio0"):
                (root / name).write_bytes(b"")
            devices = list_video_devices(directory)
        self.assertEqual(
            [Path(device).name for device in devices],
            ["video0", "video1", "video10"],
        )


class USBCameraManagerTests(unittest.TestCase):
    def test_the_default_feeds_is_one_clearly_labelled_offline_placeholder(self):
        manager = USBCameraManager(auto_start=False)
        feeds = manager.feeds()
        self.assertEqual(len(feeds), 1)
        feed = feeds[0]
        self.assertEqual(feed["id"], "camera-usb-1")
        self.assertEqual(feed["name"], "USB camera")
        self.assertEqual(feed["url"], "")
        self.assertFalse(feed["connected"])
        self.assertTrue(feed["detail"])
        manager.close()

    def test_starting_without_opencv_never_claims_to_be_connected(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("This environment has opencv installed")
        manager = USBCameraManager(auto_start=False)
        manager.start()
        feed = manager.feeds()[0]
        self.assertFalse(feed["connected"])
        self.assertIn("opencv", feed["detail"].lower())
        manager.close()

    def test_an_out_of_range_slot_streams_nothing_rather_than_raising(self):
        manager = USBCameraManager(auto_start=False)
        self.assertEqual(list(manager.mjpeg(1)), [])
        self.assertEqual(list(manager.mjpeg(0)), [])
        manager.close()

    def test_close_before_start_does_not_raise(self):
        USBCameraManager(auto_start=False).close()

import struct
import threading
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from motion_module.camera import (
    USBCameraManager,
    _DeviceStream,
    _is_capture_device,
    _V4L2_CAP_DEVICE_CAPS,
    _V4L2_CAP_VIDEO_CAPTURE,
    _V4L2_CAPABILITY_FORMAT,
    list_video_devices,
)


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


def _fake_query_cap(capabilities: int, device_caps: int):
    """A fake VIDIOC_QUERYCAP response, as bytes shaped like the real ioctl's."""

    return struct.pack(_V4L2_CAPABILITY_FORMAT, b"uvcvideo", b"Generic Camera", b"usb-1", 1,
                        capabilities, device_caps, b"\0" * 12)


class IsCaptureDeviceTests(unittest.TestCase):
    """One physical UVC webcam often exposes a real capture node plus a
    metadata-only node; without filtering, MotionModule used to treat one
    plugged-in camera as two. These pin down the ioctl bit-math that tells
    them apart, since it can't be exercised against real hardware here."""

    def _is_capture_device(self, capabilities: int, device_caps: int) -> bool:
        response = _fake_query_cap(capabilities, device_caps)

        def ioctl(fd, request, buffer, mutate=False):
            buffer[:len(response)] = response

        fake_fcntl = types.SimpleNamespace(ioctl=ioctl)
        with patch.dict(sys.modules, {"fcntl": fake_fcntl}), \
                patch("motion_module.camera.os.open", return_value=3), \
                patch("motion_module.camera.os.close"):
            return _is_capture_device("/dev/video0")

    def test_a_real_capture_node_passes(self):
        self.assertTrue(self._is_capture_device(
            _V4L2_CAP_DEVICE_CAPS | _V4L2_CAP_VIDEO_CAPTURE, _V4L2_CAP_VIDEO_CAPTURE))

    def test_a_metadata_only_node_is_filtered_out(self):
        v4l2_cap_meta_capture = 0x00800000
        self.assertFalse(self._is_capture_device(
            _V4L2_CAP_DEVICE_CAPS | _V4L2_CAP_VIDEO_CAPTURE, v4l2_cap_meta_capture))

    def test_a_driver_without_per_node_device_caps_falls_back_to_capabilities(self):
        self.assertTrue(self._is_capture_device(_V4L2_CAP_VIDEO_CAPTURE, 0))

    def test_a_device_that_will_not_open_is_not_a_capture_device(self):
        fake_fcntl = types.SimpleNamespace(ioctl=lambda *a, **k: None)
        with patch.dict(sys.modules, {"fcntl": fake_fcntl}), \
                patch("motion_module.camera.os.open", side_effect=OSError):
            self.assertFalse(_is_capture_device("/dev/video99"))


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

    def test_missing_opencv_without_auto_install_says_so_immediately(self):
        manager = USBCameraManager(auto_start=False, auto_install=False)
        with patch.dict(sys.modules, {"cv2": None}):
            manager.start()
        feed = manager.feeds()[0]
        self.assertFalse(feed["connected"])
        self.assertIn("pip install opencv-python-headless", feed["detail"])
        manager.close()

    def test_missing_opencv_tries_to_install_it_automatically(self):
        with patch.dict(sys.modules, {"cv2": None}), \
                patch("motion_module.camera.list_video_devices", return_value=["/dev/video0"]), \
                patch("motion_module.camera._is_capture_device", return_value=True), \
                patch("motion_module.camera.subprocess.run") as run:
            run.side_effect = TimeoutError("no network in this test")
            manager = USBCameraManager(auto_start=False)
            manager.start()
            deadline = time.monotonic() + 2
            detail = ""
            while time.monotonic() < deadline:
                detail = manager.feeds()[0]["detail"]
                if "install it yourself" in detail.lower():
                    break
                time.sleep(0.01)
            manager.close()
        self.assertTrue(run.called, "A missing opencv must trigger an automatic install attempt")
        self.assertIn("install it yourself", detail.lower(), "A failed install must fall back to a clear message")

    def test_an_out_of_range_slot_streams_nothing_rather_than_raising(self):
        manager = USBCameraManager(auto_start=False)
        self.assertEqual(list(manager.mjpeg(1)), [])
        self.assertEqual(list(manager.mjpeg(0)), [])
        manager.close()

    def test_close_before_start_does_not_raise(self):
        USBCameraManager(auto_start=False).close()


class CameraLifecycleTests(unittest.TestCase):
    def test_no_install_until_a_camera_exists_and_start_is_idempotent(self):
        scanned = threading.Event()

        def devices(_root):
            scanned.set()
            return []

        with patch.dict(sys.modules, {"cv2": None}), \
                patch("motion_module.camera.list_video_devices", side_effect=devices), \
                patch("motion_module.camera.subprocess.run") as install:
            manager = USBCameraManager(auto_start=False)
            try:
                manager.start()
                self.assertTrue(scanned.wait(1))
                worker = manager._thread
                manager.start()
                self.assertIs(manager._thread, worker)
                install.assert_not_called()
            finally:
                manager.close()
            self.assertFalse(worker.is_alive())
            manager.start()
            self.assertIs(manager._thread, worker)
            install.assert_not_called()

    def test_disconnected_camera_closes_without_holding_telemetry_lock(self):
        manager = USBCameraManager(auto_start=False)

        def close():
            self.assertTrue(manager._lock.acquire(blocking=False))
            manager._lock.release()

        stream = Mock(close=Mock(side_effect=close))
        manager._streams["/dev/video0"] = stream
        manager.close()
        manager.close()
        stream.close.assert_called_once_with()
        self.assertEqual(manager._streams, {})

    def test_capture_error_releases_device_and_discards_stale_frame(self):
        stream = _DeviceStream("/dev/video0")
        stream._frame = b"old frame"
        stream._connected = True
        capture = Mock()
        capture.isOpened.return_value = True

        def fail():
            stream._stop.set()
            raise RuntimeError("device disconnected")

        capture.read.side_effect = fail
        with patch.dict(sys.modules, {"cv2": Mock(VideoCapture=Mock(return_value=capture))}):
            stream._run()
        capture.release.assert_called_once_with()
        self.assertFalse(stream.connected)
        self.assertIsNone(stream._frame)
        self.assertIn("device disconnected", stream.detail)

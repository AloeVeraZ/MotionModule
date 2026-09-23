"""Automatic USB camera discovery and MJPEG streaming for the Driver Station.

A robot's dashboard.py can name a camera without giving it a URL - the
Mecanum sample's "Front" camera does exactly this by default. Rather than
leaving that a permanent offline placeholder, this module looks for a
USB-connected camera and streams it itself, matching the project's named
slots in order. A second physical camera beyond what the project named still
shows up on its own, bringing up the Driver Station's multi-camera toggle
without a line of extra code.

Opening a camera needs OpenCV (``opencv-python-headless``), which is an
optional install, not a hard dependency of MotionModule. Without it, or
without any camera plugged in, the default camera tile still appears; it
just stays a clearly labelled offline placeholder.
"""

from __future__ import annotations

import glob
import threading
import time
from typing import Iterator

from .telemetry import MAX_CAMERAS

DEFAULT_CAMERA_NAME = "USB camera"
_JPEG_QUALITY = 80
_CAPTURE_FPS = 15.0
_RETRY_SECONDS = 5.0
_NO_OPENCV = "Install opencv-python-headless to stream a USB camera automatically."
_NO_DEVICE = "No USB camera detected. Plug one in; it appears here automatically."


def list_video_devices(dev_root: str = "/dev") -> list[str]:
    """Video capture device paths, sorted, without opening any of them."""

    return sorted(glob.glob(f"{dev_root}/video*"))


class _DeviceStream:
    """Reads and JPEG-encodes frames from one camera device.

    Runs on its own background thread and keeps retrying if opening the
    device fails or an open device stops sending frames - unplugging and
    replugging the same device just works, with no outside help.
    """

    def __init__(self, device: str):
        self.device = device
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._connected = False
        self._detail = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        import cv2

        while not self._stop.is_set():
            capture = cv2.VideoCapture(self.device)
            if not capture.isOpened():
                capture.release()
                with self._lock:
                    self._connected = False
                    self._detail = "This camera would not open."
                if self._stop.wait(_RETRY_SECONDS):
                    return
                continue
            self._stream(cv2, capture)
            capture.release()
            with self._lock:
                self._connected = False
            if self._stop.wait(_RETRY_SECONDS):
                return

    def _stream(self, cv2, capture) -> None:
        interval = 1.0 / _CAPTURE_FPS
        while not self._stop.is_set():
            started = time.monotonic()
            ok, frame = capture.read()
            if not ok:
                with self._lock:
                    self._connected = False
                    self._detail = "The camera stopped sending frames."
                return
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
            if ok:
                with self._lock:
                    self._frame = buffer.tobytes()
                    self._connected = True
                    self._detail = ""
            time.sleep(max(0.0, interval - (time.monotonic() - started)))

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def detail(self) -> str:
        with self._lock:
            return self._detail

    def mjpeg(self) -> Iterator[bytes]:
        """A multipart MJPEG stream of the latest frames, for Flask's Response."""

        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while not self._stop.is_set():
            with self._lock:
                frame = self._frame
            if frame is not None:
                yield boundary + frame + b"\r\n"
            time.sleep(1.0 / _CAPTURE_FPS)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


class USBCameraManager:
    """Finds every USB camera plugged into the Pi and streams each one.

    One coordinator thread rescans for video devices every few seconds - so
    a camera plugged in after the dashboard has started, or a second one
    added later, is picked up without a restart - and starts or stops a
    _DeviceStream for each device path found, up to MAX_CAMERAS. Naming a
    feed "Front" or "Rear" is dashboard.py's job, done by matching a
    project's own cameras() against these in order; this manager only knows
    devices, not sides of a robot.
    """

    def __init__(self, *, dev_root: str = "/dev", auto_start: bool = True):
        self._dev_root = dev_root
        self._streams: dict[str, _DeviceStream] = {}
        self._lock = threading.Lock()
        self._opencv_missing = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if auto_start:
            self.start()

    def start(self) -> None:
        if self._thread is not None:
            return
        try:
            import cv2  # noqa: F401  # Only a USB camera needs this.
        except ImportError:
            self._opencv_missing = True
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            wanted = list_video_devices(self._dev_root)[:MAX_CAMERAS]
            with self._lock:
                for device in [item for item in self._streams if item not in wanted]:
                    self._streams.pop(device).close()
                for device in wanted:
                    if device not in self._streams:
                        stream = _DeviceStream(device)
                        stream.start()
                        self._streams[device] = stream
            if self._stop.wait(_RETRY_SECONDS):
                break
        with self._lock:
            for stream in self._streams.values():
                stream.close()

    def feeds(self) -> list[dict]:
        """Every auto-detected camera as normalized Driver Station entries.

        Named generically, in device order. dashboard.py's merge_cameras()
        renames each one to match a project's own cameras() where the two
        line up, and drops the rest when a project never asked for them.
        """

        with self._lock:
            devices = sorted(self._streams)
            streams = [self._streams[device] for device in devices]
        if not streams:
            detail = _NO_OPENCV if self._opencv_missing else _NO_DEVICE
            return [{
                "id": "camera-usb-1", "name": DEFAULT_CAMERA_NAME, "url": "",
                "connected": False, "detail": detail,
            }]
        feeds = []
        for index, stream in enumerate(streams):
            name = DEFAULT_CAMERA_NAME if len(streams) == 1 else f"{DEFAULT_CAMERA_NAME} {index + 1}"
            feeds.append({
                "id": f"camera-usb-{index + 1}",
                "name": name,
                "url": f"/api/camera/usb-{index + 1}.mjpg" if stream.connected else "",
                "connected": stream.connected,
                "detail": stream.detail or "Streaming automatically.",
            })
        return feeds

    def mjpeg(self, slot: int) -> Iterator[bytes]:
        """The MJPEG stream for the slot-th auto-detected camera (1-based)."""

        with self._lock:
            devices = sorted(self._streams)
            stream = self._streams.get(devices[slot - 1]) if 0 < slot <= len(devices) else None
        return stream.mjpeg() if stream is not None else iter(())

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        with self._lock:
            for stream in self._streams.values():
                stream.close()

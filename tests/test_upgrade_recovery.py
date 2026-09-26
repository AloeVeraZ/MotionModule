"""Robot folders written for older releases, and recovery when a project breaks.

The installer keeps any robot folder someone edited, so a release must still
start with the sensors.py those folders hold. If a project cannot load at all,
the dashboard must stay up (not a 502 from nginx), show the error, stop every
output and refuse to move anything.
"""

import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

from motion_module import dashboard
from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.imu import GigaIMU, IMUConfig


ROBOT = """
from sensors import create_sensors


class Drive:
    def __init__(self, module):
        self.module = module
        self.sensors = create_sensors(module)

    def drive(self, forward, strafe, rotate, speed=0.5):
        return {"outputs": {}, "speed": speed}

    def stop(self):
        self.module.stop_all()


def create_drive(module):
    return Drive(module)
"""

# sensors.py as the 0.11 Mecanum sample shipped it (commit 1064c3f).
SENSORS_0_11 = """
from motion_module.imu import GigaIMU
from motion_module.telemetry import IMUReading

IMU = GigaIMU("mpu9255", "Main IMU", address=0x68)


def create_sensors(module):
    return module.local_imu(IMU)
"""

# sensors.py from the releases that read IMUs through the Arduino GIGA.
SENSORS_GIGA = """
from motion_module.sensor_bridge import GigaIMU, GigaPin

IMUS = [GigaIMU("bno055", "Main IMU"), GigaIMU("ism330dhcx", "Backup IMU")]
PINS = [GigaPin("D22", "Intake beam", kind="digital", pull="up")]


class Sensors:
    def __init__(self, module):
        self.giga = module.giga(pins=PINS, imus=IMUS)
        self.imus = [self.giga.imu(imu.name) for imu in IMUS]
        self.giga.calibrate()


def create_sensors(module):
    return Sensors(module)
"""

SENSORS_BROKEN = """
from motion_module.imu import SomethingThatWasRemoved


def create_sensors(module):
    return None
"""


class FakeUpdates:
    def __init__(self):
        self.started = []

    def snapshot(self, refresh=False):
        return {"state": "idle"}

    def start_update(self, ref, password=None):
        self.started.append(ref)
        return "started"

    def close(self):
        pass


def project(folder: Path, sensors: str) -> Path:
    # Each test's robot.py must import its own sensors.py, not a cached one.
    sys.modules.pop("sensors", None)
    robot = folder / "Mecanum"
    robot.mkdir()
    (robot / "robot.py").write_text(textwrap.dedent(ROBOT), encoding="utf-8")
    (robot / "sensors.py").write_text(textwrap.dedent(sensors), encoding="utf-8")
    return robot / "robot.py"


class OldProjectsStillStart(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.module = MotionModule(default_config(), gpio=MockGPIO())
        self.addCleanup(self.module.close)

    def test_retired_gigaimu_declaration_means_the_pi_mpu6500(self):
        with self.assertLogs("motion_module.imu", "WARNING"):
            declaration = GigaIMU("mpu9255", "Main IMU", address=0x68)
        self.assertEqual(declaration, IMUConfig("Main IMU", address=0x68))
        with self.assertLogs("motion_module.imu", "WARNING"):
            self.assertEqual(GigaIMU("mpu9255", "Main IMU", address=0x69).address, 0x69)
        # Other chips are not read; their declaration becomes the MPU6500 at 0x68.
        with self.assertLogs("motion_module.imu", "WARNING") as logs:
            self.assertEqual(GigaIMU("ism330dhcx", "Backup IMU").address, 0x68)
        self.assertIn("no longer read", "\n".join(logs.output))
        with self.assertLogs("motion_module.imu", "WARNING"):
            self.assertEqual(GigaIMU("bno055", compass=True), IMUConfig("IMU", 0x68))

    def test_the_0_11_sample_sensors_py_loads(self):
        path = project(self.folder, SENSORS_0_11)
        with self.assertLogs("motion_module.imu", "WARNING"):
            drive, telemetry, error = dashboard.load_project_hooks(self.module, path)
        self.assertEqual(error, "")
        self.assertNotIsInstance(drive, dashboard.RecoveryDrive)
        self.assertIsNone(telemetry)

    def test_arduino_imu_projects_load_and_report_no_heading(self):
        path = project(self.folder, SENSORS_GIGA)
        with self.assertLogs("motion_module", "WARNING") as logs:
            drive, _telemetry, error = dashboard.load_project_hooks(self.module, path)
        self.assertEqual(error, "")
        self.assertTrue(any("imus=" in line for line in logs.output))
        imu = drive.sensors.imus[0]
        self.assertIsNone(imu.heading())
        imu.zero()
        reading = imu.reading()
        self.assertEqual(reading.name, "Main IMU")
        self.assertFalse(reading.connected)
        self.assertIn("MPU6500", reading.detail)


class RecoveryMode(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.module = MotionModule(default_config(), gpio=MockGPIO())
        self.addCleanup(self.module.close)
        self.path = project(self.folder, SENSORS_BROKEN)
        self.drive, telemetry, self.error = dashboard.load_project_hooks(self.module, self.path)
        self.assertIsNone(telemetry)
        self.updates = FakeUpdates()
        self.app = dashboard.create_app(
            self.module, self.drive, project_name="Mecanum",
            update_checker=self.updates, recovery_error=self.error,
        )
        self.client = self.app.test_client()
        self.headers = {"X-MotionModule-Token": self.app.config["DASHBOARD_TOKEN"]}

    def post(self, path, body):
        return self.client.post(path, json=body, headers=self.headers)

    def test_the_error_names_the_real_problem_and_where(self):
        self.assertIsInstance(self.drive, dashboard.RecoveryDrive)
        self.assertIn("ImportError", self.error)
        self.assertIn("SomethingThatWasRemoved", self.error)
        self.assertIn("sensors.py, line 2", self.error)
        status = self.client.get("/api/status").get_json()
        self.assertEqual(status["recovery"], {"active": True, "error": self.error})
        self.assertTrue(self.client.get("/api/config").get_json()["recovery"]["active"])
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_every_movement_and_actuation_command_is_refused(self):
        commands = {
            "/api/drive": {"sequence": 1, "forward": 0.5},
            "/api/drive/test": {"sequence": 2, "forward": 0.5},
            "/api/mecanum/test": {"sequence": 3, "forward": 0.5},
            "/api/drive/control": {"name": "claw", "value": 1},
            "/api/motors/test": {"confirmed": True, "channel": 1, "power": 0.3},
            "/api/servos/set": {"confirmed": True, "board": 0, "channel": 0, "angle": 90},
            "/api/autonomous/start": {"confirmed": True},
            "/api/servos/output-enable": {"enabled": True},
        }
        for path, body in commands.items():
            response = self.post(path, body)
            self.assertEqual(response.status_code, 423, path)
            self.assertIn("Recovery mode", response.get_json()["error"], path)
        self.assertTrue(all(value == 0 for value in self.module.motor_values.values()))
        self.assertFalse(self.module.servo_outputs_enabled)

    def test_the_drive_itself_refuses_to_move(self):
        with self.assertRaisesRegex(RuntimeError, "Recovery mode"):
            self.drive.drive(1, 0, 0, 1)

    def test_stopping_logs_diagnostics_deploy_and_update_stay_available(self):
        self.assertEqual(self.post("/api/stop", {}).status_code, 200)
        self.assertEqual(self.post("/api/servos/output-enable", {"enabled": False}).status_code, 200)
        self.assertEqual(self.client.get("/api/logs").status_code, 200)
        self.assertEqual(self.client.get("/api/diagnostics").status_code, 200)
        # No workspace in this test, so deploy answers 503, but never "recovery".
        deploy = self.client.post("/api/projects/deploy", headers=self.headers)
        self.assertNotEqual(deploy.status_code, 423)
        update = self.post("/api/updates", {"ref": "testing"})
        self.assertEqual(update.status_code, 202)
        self.assertEqual(self.updates.started, ["testing"])

    def test_a_working_project_is_not_in_recovery(self):
        app = dashboard.create_app(self.module, dashboard.IdleDrive(self.module), update_checker=FakeUpdates())
        self.assertFalse(app.test_client().get("/api/status").get_json()["recovery"]["active"])


class ServeStaysUp(unittest.TestCase):
    """serve() used to raise here, so nothing listened on 8080 and nginx said 502."""

    def run_serve(self, module, path, recovery_error=""):
        created = {}
        real_create_app = dashboard.create_app

        def capture(*args, **kwargs):
            kwargs["update_checker"] = FakeUpdates()
            created["app"] = real_create_app(*args, **kwargs)
            return created["app"]

        server = mock.Mock()
        stop = threading.Event()
        stop.set()
        with mock.patch.object(dashboard, "create_app", capture), \
                mock.patch.object(dashboard, "make_server", return_value=server) as make:
            dashboard.serve(module, stop, path, recovery_error)
        make.assert_called_once()
        return created["app"]

    def test_a_broken_project_still_binds_the_dashboard(self):
        folder = Path(tempfile.mkdtemp())
        path = project(folder, SENSORS_BROKEN)
        with MotionModule(default_config(), gpio=MockGPIO()) as module:
            app = self.run_serve(module, path)
        self.assertIn("SomethingThatWasRemoved", app.config["RECOVERY"]["error"])

    def test_a_hardware_file_that_does_not_load_gives_a_pinless_module(self):
        folder = Path(tempfile.mkdtemp())
        path = project(folder, SENSORS_0_11)
        (path.parent / "hardware.py").write_text("MOTORS = [\n", encoding="utf-8")
        with dashboard.open_module(path) as (module, error):
            self.assertIsInstance(module.gpio, MockGPIO)
            self.assertIn("could not start the robot's hardware", error)
            self.assertIn("No pins are being driven", error)
            app = self.run_serve(module, path, error)
        self.assertEqual(app.config["RECOVERY"]["error"], error)


if __name__ == "__main__":
    unittest.main()

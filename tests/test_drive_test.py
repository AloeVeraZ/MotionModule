"""Project Drive Test routing, default parity, and fail-safe output handling."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from motion_module.dashboard import create_app
from motion_module.deploy import _check_python
from motion_module.drive_test import DriveTest
from motion_module.errors import MotionModuleError
from motion_module.mecanum import mix
from test_dashboard import EXAMPLE_DIR, FakeModule


CUSTOM_TEST = '''
class CustomTest:
    def __init__(self, module):
        self.module = module

    def drive(self, forward, strafe, rotate, speed):
        self.module.set_motors({5: forward * speed, 6: strafe * speed, 7: rotate * speed})
        if strafe:
            self.module.servo(0).set_angle(90 + strafe * 45)
        else:
            self.module.servo(0).release()
        return {"mapping": "custom"}

    def stop(self):
        self.module.custom_stopped = True

def create_test(module):
    return CustomTest(module)
'''


class DriveTestTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name) / "robot.py"
        self.project.write_text("raise AssertionError('Drive Test must not import robot.py')\n")
        self.module = FakeModule()

    def make_client(self, source=CUSTOM_TEST):
        self.project.with_name("test.py").write_text(source, encoding="utf-8")
        self.app = create_app(self.module, project_path=self.project)
        self.addCleanup(self.app.config["STOP_OUTPUTS"])
        self.client = self.app.test_client()
        self.headers = {"X-MotionModule-Token": self.app.config["DASHBOARD_TOKEN"]}
        return self.client

    def command(self, **values):
        return self.client.post("/api/drive/test", headers=self.headers,
                                json={"sequence": 1, **values})

    def test_absent_hook_and_shipped_hook_match_confirmed_mixer(self):
        for path in (None, self.project, EXAMPLE_DIR / "robot.py"):
            drive = DriveTest(self.module, path)
            self.assertFalse(drive.error)
            for axes in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                         (0, 0, 1), (0, 0, -1), (0.7, -0.3, 0.8), (0, 0, 0)):
                with self.subTest(path=path, axes=axes):
                    result = drive.drive(*axes, 0.4)
                    self.assertEqual(result["outputs"], {k: v * 0.4 for k, v in mix(*axes).items()})

    def test_custom_motor_servo_mapping_and_stop_use_only_test_py(self):
        client = self.make_client()
        metadata = client.get("/api/config").json["drive_test"]
        self.assertEqual(metadata["source"], str(self.project.with_name("test.py")))
        self.assertEqual(metadata["error"], "")
        self.assertEqual(self.command(forward=1, strafe=-1, rotate=1, speed=0.6).status_code, 200)
        self.assertEqual([self.module.outputs[n] for n in (5, 6, 7)], [0.6, -0.6, 0.6])
        self.assertEqual(self.module._servos.angles[(0, 0)], 45)
        self.assertEqual(client.post("/api/stop").status_code, 200)
        self.assertTrue(self.module.custom_stopped)
        self.assertFalse(any(self.module.outputs.values()))
        self.assertFalse(any(self.module._servos.pulses.values()))

    def test_full_station_confirmed_mixer_is_not_replaced_by_test_py(self):
        client = self.make_client()
        response = client.post("/api/drive", headers=self.headers,
                               json={"sequence": 1, "rotate": 1, "speed": 0.4, "drive_model": "mecanum"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([self.module.outputs[n] for n in range(1, 5)], [0.4, -0.4, 0.4, -0.4])
        self.assertEqual(self.module.outputs[7], 0)

    def test_bad_hook_is_reported_without_mecanum_fallback(self):
        for source in ("broken python !", "value = 4", "def create_test(module): return object()",
                       "def create_test(module): raise RuntimeError('bad factory')"):
            with self.subTest(source=source):
                self.make_client(source)
                self.assertTrue(self.client.get("/api/config").json["drive_test"]["error"])
                self.assertEqual(self.client.get("/diagnostics").status_code, 200)
                self.assertEqual(self.command(forward=1).status_code, 400)
                self.assertFalse(any(self.module.outputs.values()))

    def test_station_takeover_stops_custom_test_motor_and_servo_outputs(self):
        self.make_client()
        self.command(forward=1, strafe=1, rotate=1)
        response = self.client.post("/api/drive", headers=self.headers,
                                    json={"sequence": 2, "forward": 1, "drive_model": "mecanum"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(self.module.outputs[n] == 0.4 for n in range(1, 5)))
        self.assertFalse(any(self.module.outputs[n] for n in (5, 6, 7)))
        self.assertFalse(any(self.module._servos.pulses.values()))

    def test_hook_runtime_error_and_bad_return_force_motor_and_servo_stop(self):
        for ending, status in (("raise RuntimeError('test failure')", 500),
                               ("return [1, 2]", 400), ("return {'bad': object()}", 400)):
            with self.subTest(ending=ending):
                self.make_client(CUSTOM_TEST.replace('return {"mapping": "custom"}', ending))
                with self.assertLogs(self.app.logger, level="ERROR") if status == 500 else patch.object(self.app.logger, "error"):
                    response = self.command(forward=1, strafe=1)
                self.assertEqual(response.status_code, status)
                self.assertFalse(any(self.module.outputs.values()))
                self.assertFalse(any(self.module._servos.pulses.values()))

    def test_broken_stop_cannot_prevent_hardware_stop(self):
        self.make_client(CUSTOM_TEST.replace("self.module.custom_stopped = True", "raise RuntimeError('bad stop')"))
        self.command(forward=1, strafe=1)
        with self.assertLogs(self.app.logger, level="ERROR"):
            self.assertEqual(self.client.post("/api/stop").status_code, 500)
        self.assertFalse(any(self.module.outputs.values()))
        self.assertFalse(any(self.module._servos.pulses.values()))

    def test_servo_only_command_timeout_releases_outputs(self):
        self.make_client()
        with patch("motion_module.dashboard.threading.Timer") as timer_class:
            self.command(strafe=1)
            self.assertEqual(timer_class.call_args.args[0], self.module.config.watchdog_ms / 1000)
            expire = timer_class.call_args.args[1]
            expire()
        self.assertFalse(any(self.module.outputs.values()))
        self.assertFalse(any(self.module._servos.pulses.values()))

    def test_old_timeout_cannot_stop_new_command(self):
        self.make_client()
        callbacks = []
        # Real Timer objects, but manually fire their callbacks deterministically.
        from threading import Timer
        def timer_factory(interval, callback):
            callbacks.append(callback)
            timer = Timer(interval, callback)
            timer.start = lambda: None
            return timer
        with patch("motion_module.dashboard.threading.Timer", side_effect=timer_factory):
            self.command(sequence=2, forward=1)
            self.command(sequence=3, forward=-1)
            callbacks[0]()
            self.assertEqual(self.module.outputs[5], -0.4)
            callbacks[1]()
            self.assertFalse(any(self.module.outputs.values()))

    def test_auth_sequence_and_numeric_validation_remain_enforced(self):
        self.make_client()
        self.assertEqual(self.client.post("/api/drive/test", json={"forward": 1}).status_code, 403)
        self.assertEqual(self.command(forward=1).status_code, 200)
        self.assertEqual(self.command(forward=-1).json["ignored"], "stale sequence")
        self.assertEqual(self.module.outputs[5], 0.4)
        self.assertEqual(self.command(sequence=2, forward="bad").status_code, 400)
        self.assertFalse(any(self.module.outputs.values()))

    def test_test_py_is_validated_without_executing_it(self):
        self.project.write_text("def create_drive(module): return module\n")
        path = self.project.with_name("test.py")
        path.write_text("raise RuntimeError('never execute uploads')\ndef create_test(module): return module\n")
        _check_python(self.project.parent, strict=True)
        path.write_text("value = 1\n")
        with self.assertRaisesRegex(MotionModuleError, "create_test"):
            _check_python(self.project.parent, strict=True)

    def test_downloaded_sample_contains_test_py(self):
        app = create_app(self.module)
        self.addCleanup(app.config["STOP_OUTPUTS"])
        response = app.test_client().get("/api/projects/sample")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            source = archive.read("Mecanum/test.py").decode()
            self.assertIn("def create_test(module)", source)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from motion_module.config import default_config, hardware_source
from motion_module.runner import main


class RunnerTests(unittest.TestCase):
    def test_runner_uses_the_requested_robot_hardware_and_stops_on_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            config = default_config()
            config = replace(config, motors=(replace(config.motors[0], name="left_wheel"), *config.motors[1:]))
            (project / "hardware.py").write_text(hardware_source(config), encoding="utf-8")
            (project / "robot.py").write_text("# Test robot\n", encoding="utf-8")
            observed = []

            def run(module, stop_event):
                module.motor("left_wheel").set(0.25)
                observed.append((module, stop_event))
                self.assertEqual(module.gpio.values[6], 0.25)

            with patch.dict(os.environ, {"MOTIONMODULE_MOCK": "1", "MOTIONMODULE_ACTIVE_PROJECT": ""}):
                with patch("motion_module.runner.signal.signal"), patch(
                    "motion_module.runner.load_project", return_value=SimpleNamespace(run=run)
                ):
                    self.assertEqual(main([str(project / "robot.py")]), 0)
            module, stop_event = observed[0]
            self.assertTrue(stop_event.is_set())
            self.assertTrue(module.gpio.closed)
            self.assertEqual(set(module.motor_values.values()), {0})


if __name__ == "__main__":
    unittest.main()

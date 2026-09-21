"""Optional project test.py adapter for Debug's fixed Drive Test inputs."""

from pathlib import Path

from .mecanum import MecanumTestDrive, clamp
from .runner import load_project


class DriveTest:
    """Load only test.py; never substitute robot.py or silently hide a bad hook."""

    def __init__(self, module, project_path=None):
        self.driver = None
        self.error = ""
        path = Path(project_path).with_name("test.py") if project_path else None
        self.source = str(path) if path and path.exists() else "Built-in Mecanum"
        try:
            if path and path.exists():
                project = load_project(path)
                factory = getattr(project, "create_test", None)
                if not callable(factory):
                    raise ValueError("test.py must define create_test(module)")
                self.driver = factory(module)
                if not all(callable(getattr(self.driver, name, None)) for name in ("drive", "stop")):
                    raise ValueError("create_test(module) must return an object with drive() and stop()")
            else:
                self.driver = MecanumTestDrive(module)
        except Exception as error:
            self.driver = None
            self.error = f"Drive Test could not load test.py: {error}"
            try:
                module.stop_all()
            finally:
                module.release_all_servos()

    def description(self):
        return {"source": self.source, "error": self.error}

    def drive(self, forward, strafe, rotate, speed=0.4):
        if self.error:
            raise ValueError(self.error)
        forward, strafe, rotate = map(clamp, (forward, strafe, rotate))
        speed = clamp(speed, 0.0, 1.0)
        result = self.driver.drive(forward, strafe, rotate, speed)
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise ValueError("test.py drive() must return a dictionary or None")
        return result

    def stop(self):
        if self.driver is not None:
            self.driver.stop()

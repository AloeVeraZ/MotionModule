import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from motion_module.autonomous import AutonomousRunner, load_autonomous


class FakeModule:
    def __init__(self):
        self.stopped = 0

    def stop_all(self):
        self.stopped += 1


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class LoadAutonomousTests(unittest.TestCase):
    """autonomous.py is optional, and a broken one must say why."""

    def write(self, source):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        folder = Path(self.directory.name)
        (folder / "robot.py").write_text("", encoding="utf-8")
        if source is not None:
            (folder / "autonomous.py").write_text(source, encoding="utf-8")
        return folder / "robot.py"

    def test_a_project_without_the_file_simply_has_no_autonomous(self):
        self.assertIsNone(load_autonomous(FakeModule(), None, self.write(None)))
        self.assertIsNone(load_autonomous(FakeModule(), None, None))

    def test_class_entry_point_is_loaded(self):
        path = self.write(
            "class Auto:\n"
            "    def __init__(self, module, drive):\n"
            "        self.module = module\n"
            "    def run(self, stop):\n"
            "        self.module.ran = True\n"
            "\n"
            "def create_autonomous(module, drive):\n"
            "    return Auto(module, drive)\n"
        )
        routine = load_autonomous(FakeModule(), None, path)
        self.assertTrue(callable(routine.run))

    def test_a_bare_run_function_is_accepted_for_a_short_routine(self):
        path = self.write("def run(module, stop):\n    module.ran = True\n")
        module = FakeModule()
        routine = load_autonomous(module, None, path)
        routine.run(threading.Event())
        self.assertTrue(module.ran)

    def test_a_file_with_no_entry_point_names_what_it_needs(self):
        path = self.write("VALUE = 1\n")
        with self.assertRaisesRegex(RuntimeError, "create_autonomous"):
            load_autonomous(FakeModule(), None, path)

    def test_a_factory_returning_the_wrong_shape_is_rejected(self):
        path = self.write("def create_autonomous(module, drive):\n    return object()\n")
        with self.assertRaisesRegex(RuntimeError, "run\\(stop\\)"):
            load_autonomous(FakeModule(), None, path)


class RunnerTests(unittest.TestCase):
    def runner(self, routine, module=None):
        module = module or FakeModule()
        runner = AutonomousRunner(module, routine)
        self.addCleanup(runner.stop)
        return runner, module

    def test_a_project_without_a_routine_reports_that_and_refuses_to_start(self):
        runner, _ = self.runner(None)
        self.assertFalse(runner.configured)
        self.assertFalse(runner.status()["configured"])
        with self.assertRaisesRegex(RuntimeError, "no autonomous.py"):
            runner.start()

    def test_a_routine_that_returns_ends_as_finished_and_stops_the_outputs(self):
        class Routine:
            duration_seconds = 5

            def run(self, stop):
                return None

        runner, module = self.runner(Routine())
        runner.start()
        self.assertTrue(wait_until(lambda: runner.status()["state"] == "finished"))
        self.assertEqual(module.stopped, 1)
        self.assertEqual(runner.status()["error"], "")

    def test_stopping_sets_the_flag_and_the_routine_is_recorded_as_stopped(self):
        started = threading.Event()

        class Routine:
            duration_seconds = 5

            def run(self, stop):
                started.set()
                while not stop.is_set():
                    time.sleep(0.01)

        runner, module = self.runner(Routine())
        runner.start()
        self.assertTrue(started.wait(2))
        self.assertTrue(runner.running)
        runner.stop()
        self.assertFalse(runner.running)
        self.assertEqual(runner.status()["state"], "stopped")
        self.assertGreaterEqual(module.stopped, 1)

    def test_a_routine_that_raises_is_reported_and_never_leaves_outputs_live(self):
        class Routine:
            duration_seconds = 5

            def run(self, stop):
                raise ValueError("no such motor")

        runner, module = self.runner(Routine())
        runner.start()
        self.assertTrue(wait_until(lambda: runner.status()["state"] == "failed"))
        self.assertIn("no such motor", runner.status()["error"])
        self.assertEqual(module.stopped, 1)

    def test_a_routine_that_never_returns_is_cut_off_at_its_time_limit(self):
        """A runaway routine still ends, without anyone pressing anything."""

        class Routine:
            duration_seconds = 0.2

            def run(self, stop):
                while not stop.is_set():
                    time.sleep(0.01)

        runner, module = self.runner(Routine())
        runner.start()
        self.assertTrue(wait_until(lambda: runner.status()["state"] == "expired", timeout=3))
        self.assertIn("cut short", runner.status()["error"])
        self.assertGreaterEqual(module.stopped, 1)

    def test_starting_twice_is_refused_rather_than_running_two_routines(self):
        class Routine:
            duration_seconds = 5

            def run(self, stop):
                while not stop.is_set():
                    time.sleep(0.01)

        runner, _ = self.runner(Routine())
        runner.start()
        with self.assertRaisesRegex(RuntimeError, "already running"):
            runner.start()

    def test_the_stop_path_is_used_when_one_is_supplied(self):
        calls = []

        class Routine:
            duration_seconds = 5

            def run(self, stop):
                return None

        runner = AutonomousRunner(FakeModule(), Routine(), lambda: calls.append(1))
        self.addCleanup(runner.stop)
        runner.start()
        self.assertTrue(wait_until(lambda: runner.status()["state"] == "finished"))
        self.assertEqual(calls, [1])

    def test_stopped_but_unfinished_routine_cannot_overlap_a_new_run(self):
        entered, finish = threading.Event(), threading.Event()

        class Routine:
            duration_seconds = None

            def run(self, stop):
                entered.set()
                finish.wait(2)

        runner, _ = self.runner(Routine())
        try:
            runner.start()
            self.assertTrue(entered.wait(1))
            runner.stop(timeout=0)
            with self.assertRaisesRegex(RuntimeError, "still stopping"):
                runner.start()
        finally:
            finish.set()
            runner.stop()

    def test_nonfinite_duration_uses_the_default_instead_of_breaking_the_timer(self):
        from motion_module.autonomous import DEFAULT_DURATION_SECONDS
        from types import SimpleNamespace

        for duration in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(duration=duration):
                runner, _ = self.runner(SimpleNamespace(duration_seconds=duration))
                self.assertEqual(runner.status()["duration_seconds"], DEFAULT_DURATION_SECONDS)


if __name__ == "__main__":
    unittest.main()

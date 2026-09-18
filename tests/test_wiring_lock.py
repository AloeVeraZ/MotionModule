"""The robot's reference wiring is locked. Read AGENTS.md before changing this.

The real robot is wired exactly as LOCKED_MOTORS and LOCKED_SERVO_BOARD say,
and that wiring works. These tests fail if a shipped pin map, a driver
assignment, a ground or a wiring table in the docs moves away from it. The
installer runs the test suite, so a release with different wiring will not
install on the robot.

If one of these fails, put the wiring back. Never edit the LOCKED_ values to
make a failing test pass: only the robot's owner can rewire the robot, and
they will say so explicitly. The helpers that read the docs may follow a
reworded table, as long as they still read the same wires.
"""

import re
import unittest
from pathlib import Path

from motion_module.config import DEFAULT_HARDWARE_PATH, load_hardware_file
from motion_module.hardware_guide import hardware_guide
from motion_module.pinout import header_rows, motor_rows

ROOT = Path(__file__).resolve().parents[1]
MECANUM_HARDWARE = ROOT / "examples" / "Mecanum" / "hardware.py"
PINOUT_DOC = ROOT / "docs" / "PINOUT.md"
MECANUM_README = ROOT / "examples" / "Mecanum" / "README.md"
BROKEN = "The locked robot wiring changed. Put it back; AGENTS.md explains why."

# channel: (driver, output, forward (physical pin, GPIO), reverse (physical pin, GPIO), driver ground pin)
LOCKED_MOTORS = {
    1: (1, "A", (37, 26), (35, 19), 39),
    2: (1, "B", (33, 13), (31, 6), 39),
    3: (2, "A", (40, 21), (38, 20), 34),
    4: (2, "B", (36, 16), (32, 12), 34),
    5: (3, "A", (23, 11), (21, 9), 25),
    6: (3, "B", (26, 7), (24, 8), 25),
    7: (4, "A", (15, 22), (13, 27), 14),
    8: (4, "B", (18, 24), (16, 23), 14),
}
# Which wheel of the Mecanum sample is wired to which channel.
LOCKED_MECANUM_WHEELS = {1: "front_left", 2: "rear_left", 3: "front_right", 4: "rear_right"}
# PCA9685 connection: physical header pin. OE is GPIO4.
LOCKED_SERVO_BOARD = {"VCC": 1, "SDA": 3, "SCL": 5, "OE": 7, "GND": 9}
LOCKED_SERVO_OE_GPIO = 4
# What each of the 40 header pins does.
LOCKED_HEADER = {
    "motor": {13, 15, 16, 18, 21, 23, 24, 26, 31, 32, 33, 35, 36, 37, 38, 40},
    "servo": {1, 3, 5, 7},
    "ground": {6, 9, 14, 20, 25, 30, 34, 39},
    "power": {2, 4, 17},
    "reserved": {8, 10, 27, 28},
    "unused": {11, 12, 19, 22, 29},
}
# Pins with a wire on them: every motor input, the servo board, the driver grounds.
LOCKED_WIRED_PINS = (
    LOCKED_HEADER["motor"]
    | set(LOCKED_SERVO_BOARD.values())
    | {ground for *_wires, ground in LOCKED_MOTORS.values()}
)
# docs/PINOUT.md's reserved and unused table, one set of pins per row.
LOCKED_SPARE_ROWS = [{1, 3, 5, 7, 9}, {8, 10}, {27, 28}, {2, 4}, {17}, {6, 20, 30}, {11, 12, 19, 22, 29}]

SHIPPED_PIN_MAPS = (DEFAULT_HARDWARE_PATH, MECANUM_HARDWARE)


def wiring(config) -> dict:
    return {
        row["motor"]: (
            row["driver"],
            row["output"],
            (row["in1_physical"], row["in1_bcm"]),
            (row["in2_physical"], row["in2_bcm"]),
            row["ground_physical"],
        )
        for row in motor_rows(config)
    }


def table_rows(text: str) -> list[list[str]]:
    """Markdown table rows as lists of cells, header and divider rows included."""

    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.lstrip().startswith("|")
    ]


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


class LockedWiringTests(unittest.TestCase):
    def test_every_shipped_pin_map_is_the_locked_wiring(self):
        for path in SHIPPED_PIN_MAPS:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                config = load_hardware_file(path)
                self.assertEqual(wiring(config), LOCKED_MOTORS, BROKEN)
                self.assertTrue(config.servos.enabled, BROKEN)
                self.assertEqual(config.servos.i2c_bus, 1, BROKEN)
                self.assertEqual(config.servos.output_enable_gpio, LOCKED_SERVO_OE_GPIO, BROKEN)

    def test_mecanum_wheels_stay_on_drivers_1_and_2(self):
        config = load_hardware_file(MECANUM_HARDWARE)
        wheels = {motor.channel: motor.name for motor in config.motors if motor.channel in LOCKED_MECANUM_WHEELS}
        self.assertEqual(wheels, LOCKED_MECANUM_WHEELS, BROKEN)

    def test_every_header_pin_keeps_its_job(self):
        for path in SHIPPED_PIN_MAPS:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                header = header_rows(load_hardware_file(path))
                jobs: dict[str, set[int]] = {}
                for row in header:
                    jobs.setdefault(row["category"], set()).add(row["physical"])
                self.assertEqual(jobs, LOCKED_HEADER, BROKEN)
                wired = {row["physical"] for row in header if row["configured"]}
                self.assertEqual(wired, LOCKED_WIRED_PINS, BROKEN)

    def test_wiring_guide_runs_the_servo_board_from_pins_1_to_9(self):
        guide = hardware_guide(load_hardware_file(MECANUM_HARDWARE))
        board = {
            connection["to"].removeprefix("PCA9685 "): int(re.search(r"physical (\d+)", connection["from"]).group(1))
            for connection in guide["wiring"]["logic_connections"]
        }
        self.assertEqual(board, LOCKED_SERVO_BOARD, BROKEN)

    def test_hardware_file_comment_tables_match(self):
        """The wire table a person reads in each hardware.py matches its data."""

        comment = re.compile(r"^\s*#\s+(\d)\s+\w+\s+Driver (\d) · ([AB])\b(.*)$")
        # The built-in file lists all eight channels with their grounds; the
        # Mecanum sample lists its four wheels without a ground column.
        for path, channels, grounds in ((DEFAULT_HARDWARE_PATH, range(1, 9), True),
                                        (MECANUM_HARDWARE, range(1, 5), False)):
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                found = {}
                for line in path.read_text(encoding="utf-8").splitlines():
                    match = comment.match(line)
                    if match:
                        channel, driver, output, rest = match.groups()
                        wires = tuple((int(pin), int(gpio)) for pin, gpio in re.findall(r"pin (\d+)/GPIO(\d+)", rest))
                        ground = re.search(r"pin (\d+)\s*$", rest)
                        found[int(channel)] = (int(driver), output, *wires, int(ground.group(1)) if ground else None)
                expected = {
                    channel: LOCKED_MOTORS[channel] if grounds else (*LOCKED_MOTORS[channel][:4], None)
                    for channel in channels
                }
                self.assertEqual(found, expected, BROKEN)

    def test_pinout_doc_driver_tables_match(self):
        rows = table_rows(PINOUT_DOC.read_text(encoding="utf-8"))
        drivers, bundles = {}, {}
        for cells in rows:
            if len(cells) >= 7 and re.fullmatch(r"\d", cells[0]) and cells[1] in {"A", "B"}:
                wires = [tuple(map(int, pair)) for cell in cells[4:6]
                         for pair in re.findall(r"physical (\d+) / GPIO(\d+)", cell)]
                ground = re.fullmatch(r"physical (\d+)", cells[6])
                drivers[int(cells[2])] = (int(cells[0]), cells[1], *wires, int(ground.group(1)) if ground else None)
            elif (len(cells) >= 3 and re.fullmatch(r"\d", cells[0])
                  and re.fullmatch(r"[\d, and]+", cells[1]) and re.fullmatch(r"\d+", cells[2])):
                bundles[int(cells[0])] = ({int(pin) for pin in re.findall(r"\d+", cells[1])}, int(cells[2]))
        self.assertEqual(drivers, LOCKED_MOTORS, BROKEN)
        expected_bundles = {}
        for driver, _output, forward, reverse, ground in LOCKED_MOTORS.values():
            pins, _ground = expected_bundles.setdefault(driver, (set(), ground))
            pins.update((forward[0], reverse[0]))
        self.assertEqual(bundles, expected_bundles, BROKEN)

    def test_pinout_doc_servo_table_matches(self):
        board = {}
        for cells in table_rows(PINOUT_DOC.read_text(encoding="utf-8")):
            name = re.match(r"(VCC|SDA|SCL|OE|GND)\b", cells[0])
            pin = re.match(r"physical pin (\d+)", cells[1]) if len(cells) > 1 else None
            if name and pin:
                board[name.group(1)] = int(pin.group(1))
        self.assertEqual(board, LOCKED_SERVO_BOARD, BROKEN)

    def test_pinout_doc_lists_only_truly_spare_pins(self):
        doc = PINOUT_DOC.read_text(encoding="utf-8")
        rows = [
            {int(pin) for pin in re.findall(r"(?<!GPIO)\b(\d+)\b", cells[0])}
            for cells in table_rows(section(doc, "## Reserved and unused Pi header pins"))
            if re.match(r"\d", cells[0])
        ]
        self.assertCountEqual(rows, LOCKED_SPARE_ROWS, BROKEN)
        free = re.search(r"GPIOs stay free for later use: physical ([\d,\sand]+)\.", doc)
        self.assertIsNotNone(free, "docs/PINOUT.md should still say which GPIOs are free")
        self.assertEqual({int(pin) for pin in re.findall(r"\d+", free.group(1))},
                         {8, 10} | LOCKED_HEADER["unused"], BROKEN)

    def test_mecanum_readme_puts_each_wheel_on_its_driver(self):
        wheels = {}
        for cells in table_rows(MECANUM_README.read_text(encoding="utf-8")):
            name = re.fullmatch(r"`(\w+)`", cells[0])
            place = re.fullmatch(r"Driver (\d) · ([AB])", cells[2]) if len(cells) > 2 else None
            if name and place and re.fullmatch(r"\d", cells[1]):
                wheels[name.group(1)] = (int(cells[1]), int(place.group(1)), place.group(2))
        expected = {name: (channel, *LOCKED_MOTORS[channel][:2]) for channel, name in LOCKED_MECANUM_WHEELS.items()}
        self.assertEqual(wheels, expected, BROKEN)


if __name__ == "__main__":
    unittest.main()

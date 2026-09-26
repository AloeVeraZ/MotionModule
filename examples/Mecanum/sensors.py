"""The Mecanum robot's MPU6500, wired directly to the Raspberry Pi.

Use the single wiring plan in Debug > Wiring and docs/PINOUT.md:
VCC -> physical 17, GND -> 6, AD0 -> 20, SDA -> 11, SCL -> 12.
Enable dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18 and reboot.
The Pi reads the independent bus; no Arduino is part of this setup.

Zeroing happens only when you press Zero IMU in the Driver Station. It makes
the way the robot faces read 0° and its present tilt read level, and nothing
else resets it. The level is saved beside this file and survives a reboot;
the heading cannot (the MPU6500 has no compass), so after a power-off it
starts at 0° facing wherever the robot faces. At every start-up the gyro is
measured at rest for about a second - keep the robot still - because its
resting error changes with temperature; that measurement never moves the zero.

Additional sensors are not declared. Optional USB GPIO expansion through an
Arduino GIGA R1 WiFi is an experimental extension; see docs/CODING.md.
"""

import json
from pathlib import Path

from motion_module.imu import IMUConfig
from motion_module.telemetry import IMUReading


# The built-in IMU is MPU6500 on the independent Pi I2C bus.
IMU = IMUConfig("Main IMU", address=0x68)

# Where Zero IMU keeps the level. A name starting with "." is ignored when
# MotionModule checks whether this folder is still an untouched sample.
LEVEL_FILE = Path(__file__).with_name(".imu-level.json")


class RobotSensors:
    """One Pi IMU shared by driving, autonomous and the dashboard."""

    def __init__(self, module, level_file=None):
        self.imu = module.local_imu(IMU)
        self.level_file = Path(level_file or LEVEL_FILE)
        if self.imu is not None:
            try:
                saved = json.loads(self.level_file.read_text(encoding="utf-8"))
                self.imu.set_level(saved["pitch"], saved["roll"])
            except (OSError, ValueError, KeyError, TypeError):
                pass  # never zeroed yet: level is the chip's own

    def heading(self):
        """Degrees from -180 to 180, increasing on a left turn; None offline."""
        return self.imu.heading() if self.imu is not None else None

    def rate(self):
        """How fast the robot turns, degrees per second, left positive; None offline."""
        return self.imu.rate() if self.imu is not None else None

    def zero_heading(self):
        """Zero IMU: the way the robot faces reads 0° and its tilt reads level.

        Only a person pressing Zero IMU calls this. Returns False if the IMU
        is not ready yet.
        """
        if self.imu is None or self.imu.heading() is None:
            return False
        self.imu.zero(level=True)
        pitch, roll = self.imu.level
        try:
            self.level_file.write_text(json.dumps({"pitch": pitch, "roll": roll}), encoding="utf-8")
        except OSError:
            pass  # still zeroed until the next restart
        return True

    def recalibrate(self):
        """Measure the gyro at rest again. Keep the robot still for a second."""
        if self.imu is not None:
            self.imu.recalibrate()

    def reading(self):
        if self.imu is not None:
            return self.imu.reading()
        return IMUReading(
            name=IMU.name, connected=False, calibrated=False,
            detail="Pi MPU6500 unavailable. On the Pi, enable the i2c-gpio overlay and reboot; see Debug > Wiring.",
        )


def create_sensors(module):
    """Called once by robot.py; MotionModule closes the IMU on shutdown."""
    return RobotSensors(module)

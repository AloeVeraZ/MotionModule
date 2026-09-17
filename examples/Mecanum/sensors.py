"""Every sensor on this robot. The Arduino GIGA R1 WiFi reads them all.

The GIGA is the robot's sensor board. It reads each digital pin as on or off,
each analog pin as a number, and whichever sensor registers the Pi asks for,
then passes the numbers up its USB cable; the Pi does every calculation. This
file says what is wired to the GIGA and gives every reading a name. robot.py
imports it, so the drive code, autonomous.py, and dashboard.py all share the
same sensors.

Set up the GIGA once, no Arduino IDE needed:
  1. Plug its USB-C port into one of the Pi's USB ports.
  2. On the Pi run  motionmodule giga flash  (or Debug -> Install firmware).
  3. Wire the sensors below, then deploy this folder.

Both IMU boards chain together with STEMMA QT / Qwiic cables. The first one
connects to the GIGA:
    red    -> 3.3V         black  -> GND
    blue   -> SDA 20       yellow -> SCL 21
Mount the IMUs flat, parts side up, anywhere on the robot's frame.

The GIGA's pins take 3.3 V at most. Never connect a 5 V signal to them.
"""

from motion_module.sensor_bridge import GigaIMU, GigaPin


# IMUs on the GIGA's I2C pins. Delete a line if that board is not fitted; the
# first IMU listed is the one the robot steers by.
IMUS = [
    # Adafruit BNO055 9-axis. The chip fuses its own readings and is ready in
    # about a second. compass=True adds its magnetometer for a north heading,
    # but motors and steel nearby bend that, so a robot is usually better off
    # without it.
    GigaIMU("bno055", "Main IMU"),
    # Adafruit ISM330DHCX 6-axis (an LSM6DSOX works the same way; say
    # "lsm6dsox"). It reports a raw gyro and accelerometer, and the Pi turns
    # those into a heading. Keep the robot still for a second after power-on
    # while it measures the gyro at rest.
    GigaIMU("ism330dhcx", "Backup IMU"),
]

# Anything else wired to the GIGA's pins. The Pi sees:
#   digital pins as True (3.3 V) or False (0 V); pull="up" holds an
#   unconnected pin True, so a switch wired to GND reads False when pressed
#   analog pins A0-A7 as 0 (0 V) to 4095 (3.3 V)
PINS = [
    GigaPin("A0", "Arm potentiometer", kind="analog", unit="raw", minimum=0, maximum=4095),
    GigaPin("D22", "Intake beam", kind="digital", pull="up"),
]


class RobotSensors:
    """What the rest of the robot reads. Add a method for each sensor it uses."""

    def __init__(self, module):
        # One USB connection reads everything declared above. In the laptop
        # demo and in tests the GIGA is simulated, and every reading is None.
        self.giga = module.giga(pins=PINS, imus=IMUS)
        self.imus = [self.giga.imu(imu.name) for imu in IMUS]

    def heading(self):
        """Degrees from -180 to 180. Turning left counts up, as rotate does.

        Reads the first IMU that is streaming, so the robot keeps its heading
        if one board drops out. None when no IMU is streaming.
        """

        for imu in self.imus:
            heading = imu.heading()
            if heading is not None:
                return heading
        return None

    def zero_heading(self):
        """Make the way the robot faces now read 0 degrees."""

        for imu in self.imus:
            imu.zero()

    def calibrate_gyro(self):
        """Measure the 6-axis gyro again. Keep the robot still for a second."""

        self.giga.calibrate()

    def arm_position(self):
        """0 to 4095 from the arm potentiometer, or None without a reading."""

        return self.giga.value("Arm potentiometer")

    def intake_blocked(self):
        """True while something breaks the intake beam, which pulls D22 low."""

        beam = self.giga.value("Intake beam")
        return None if beam is None else not beam


def create_sensors(module):
    """Called once by robot.py."""

    return RobotSensors(module)

"""Debug → Drive Test: the same physically verified Mecanum behavior.

Copy this file beside your robot.py to customize only the Debug test.
Keep create_test(module), drive(forward, strafe, rotate, speed), and stop().
W/S supplies forward (+/-), D/A strafe (+/-), Q/E rotate (+/-).
Space calls stop() and forcibly stops all motors and releases all servos.
Use the supplied module for motors/servos; never open a second controller.
Do not move hardware at import or construction time, or start background loops.
The full Driver Station continues to use robot.py, not this file.
"""

from motion_module.mecanum import MecanumTestDrive


def create_test(module):
    return MecanumTestDrive(module)

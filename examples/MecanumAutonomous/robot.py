"""Entry point for the bundled Autonomous Driver program.

MotionModule loads this file from robots/autonomous/Autonomous Driver. The
existing IMU-guided 90-degree turn routine lives beside it in autonomous.py and creates
its own four-wheel drive. It reads MotionModule's built-in module.imu sensor;
teleop code and sensor configuration files are not required.
"""

PROGRAM_MODE = "autonomous"

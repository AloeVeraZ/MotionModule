# Mecanum autonomous

This separate program installs in `robots/autonomous/Mecanum/`. Select it in
Driver Station's Autonomous picker, then press Enable. It turns left to 90°,
180°, 270° and 360° from the heading at Enable, settling at each stop. It uses
the Pi-connected MPU6500 gyroscope and the same four motor channels as the
Mecanum teleop program. It does not move if the IMU is unavailable.

The turn plan is in `autonomous.py`. Disable stops all outputs immediately.
Keep the robot off the ground for the first powered check.

# Autonomous Driver

This separate program installs in `robots/autonomous/Autonomous Driver/`. Select it in
Driver Station's Autonomous picker, then press Enable. It turns left to 90°,
180°, 270° and 360° from the heading at Enable, then ends the routine. It uses
the Pi-connected MPU6500 gyroscope and the same four motor channels as the
Mecanum teleop program. It reads the always-running `module.imu`; it does not
configure or create a sensor. Switching from teleop keeps the same reader and
calibration. It works with both the regular MotionModule and
MotionModule Mini. The bundled code is for four-wheel mecanum robots; it does
not move if the IMU is unavailable.

If startup calibration is still finishing at Enable, the routine waits while
stopped for up to five seconds. It stops with an explanation if heading is
still unavailable, and Disable interrupts the wait immediately.

The turn plan is in `autonomous.py`. Disable stops all outputs immediately.
Each turn uses up to 50% motor power, drops to a 40% cap for its last 30°,
then tapers further as it reaches the target. A marker counts as reached when
the heading is within 2° or crosses it between sensor readings. That arrival
is latched: outputs stop for 0.25 seconds, then the next turn starts, without
reversing to chase the previous marker. The final pause at 360° ends the run.
Momentum may carry the robot slightly past a marker during the pause.
`TURN_SPEED`, `APPROACH_SPEED`, `APPROACH_DEGREES` and `MARKER_PAUSE_SECONDS`
control this profile; it does not change teleop's tuning. A turn that cannot
reach its marker still stops with a timeout.
Software updates refresh unchanged copies of this bundled program and keep
the previous copy in `backups/`. Edited robot programs are left as they are.
Keep the robot off the ground for the first powered check.

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
Each turn cruises at up to 100% motor power. Within the last 25°, power is
capped at 60% and the requested turn rate progressively falls from 200°/s to
80°/s near the marker. That approach rate can only decrease for this target.
After overshoot, recovery uses a still lower 12°/s target and a 28% power cap,
latched for the rest of that turn even if it undershoots back across the marker.
Only a new marker restores cruise speed. PID brakes and reverses as needed;
available torque lets slow corrections overcome friction without demanding a
fast return. These rates are control targets, not a guarantee against momentum.
Crossing a marker does not complete a turn: heading must stay
within **±3° for 0.2 seconds** with a low measured turn rate before advancing.
The same correction and settling happens at 360°, then all outputs stop and
the routine ends.

`TurnPID` in `core/motion_module/heading.py` supplies the autonomous gains
(`kp=0.065`, `ki=0.006`, `kd=0.0035`, `derivative_seconds=0.01` for this program). On approach and recovery, P requests
a bounded turn rate, D follows the measured rate, and I supplies torque to
overcome friction. The integral has a 60% power bound and protection against
windup; it resets
for every target and when crossing or entering tolerance. The derivative uses
filtered changes in heading, including across ±180°, so a noisy gyro-rate
reading alone cannot prevent settling. Teleop's tuning is independent.
`TURN_SPEED`, `APPROACH_SPEED` and `CORRECTION_SPEED` set the power limits;
`APPROACH_DEGREES`, `APPROACH_RATE`, `FINAL_APPROACH_RATE` and `CORRECTION_RATE`
in `autonomous.py` control the slowdown. These are starting gains; verify and
tune on the real robot. Each marker has 20 seconds for turning and correction,
with a 90-second overall limit. A stalled turn fails without skipping ahead;
its error names the marker from the start and the current IMU heading/error.
Software updates refresh unchanged copies of this bundled program and keep
the previous copy in `backups/`. Edited robot programs are left as they are.
Keep the robot off the ground for the first powered check.

The stock factory applies `IMU_TO_MIXER_SIGN = -1` to heading corrections:
on the reference robot, positive mixer rotation was measured to decrease IMU
heading. This conversion leaves manual drive controls, motor inversion and
wiring unchanged. Custom drives supplied to `MecanumAutonomous` must accept
positive rotation as increasing heading. The old simulation assumed that
relationship already held for the stock mixer, which hid the feedback error.

On-robot tuning on 2026-10-19 completed all four markers in 3.4–3.7 seconds
across five runs. Every accepted marker was within 2.4°, and final resting
errors were within 1.1°. Temporary overshoot reached about 5.7° before slow
correction; acceptance still requires ±3° and low rotation rate for 0.2 seconds.
More aggressive tuning increased overshoot and completion time. Battery charge
and floor traction affect these measurements; they are not guaranteed times.

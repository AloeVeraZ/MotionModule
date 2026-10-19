# Release notes

## October 19, 2026

- **Faster autonomous:** 90° → 180° → 270° → 360°, then stop. Fixed gyro feedback direction; PID slows the approach and corrects overshoot. Each marker must settle within ±3° for 0.2 seconds. Five robot runs finished in 3.4–3.7 seconds; battery and traction affect results. [Details](../examples/MecanumAutonomous/README.md).
- **MotionModule Mini:** four motor outputs, the same servo and IMU support, and a shared runtime with the full eight-motor build. [Build guide](../MotionModuleMini/README.md).
- **Programs and IMU:** separate Teleop and Autonomous folder pickers, one shared Mecanum sample, and continuous built-in IMU access across program changes.
- **Dashboard:** responsive layouts, simpler controls and update selection, improved connection handling, and automatic diagnostic refreshes.
- **Updates and backups:** preserve robot files and active programs, save pre-update snapshots, download robot code and diagnostic reports, and support explicit fresh installs. Unchanged bundled autonomous copies receive the updated routine; edited copies are preserved. [Installer notes](../installer/README.md).
- **Build files:** updated enclosure CAD, mounting-screw documentation, and full/Mini build references. Existing wiring is unchanged.

Update an installed Pi: `motionmodule install main`.

# Release notes

## November 1, 2026

- **Fewer 502 Bad Gateway pages:** the dashboard now opens in recovery mode, showing the reason, when the active robot folder is missing, when robot code calls `sys.exit()`, and when robot code has not finished loading after 60 seconds. systemd also never stops restarting it, a failed fresh install starts it again, and a damaged module-variant file no longer blocks starting or installing. To pick this up, run `motionmodule install main` over SSH.

## October 19, 2026

- **Fresh-install repair:** fixed an unset previous-program variable that could abort installation after stopping the dashboard, leaving a 502 Bad Gateway. To recover over SSH, run `motionmodule install main` without `--fresh`.
- **Faster autonomous:** 90° → 180° → 270° → 360°, then stop. Fixed gyro feedback direction; PID slows the approach and corrects overshoot. Each marker must settle within ±3° for 0.2 seconds. Five robot runs finished in 3.4–3.7 seconds; battery and traction affect results. [Details](../examples/MecanumAutonomous/README.md).
- **MotionModule Mini:** four motor outputs, the same servo and IMU support, and a shared runtime with the full eight-motor build. [Build guide](../MotionModuleMini/README.md).
- **Programs and IMU:** separate Teleop and Autonomous folder pickers, one shared Mecanum sample, and continuous built-in IMU access across program changes.
- **Dashboard:** responsive layouts, simpler controls and update selection, improved connection handling, and automatic diagnostic refreshes.
- **Updates and backups:** preserve robot files and active programs, save pre-update snapshots, download robot code and diagnostic reports, and support explicit fresh installs. Unchanged bundled autonomous copies receive the updated routine; edited copies are preserved. [Installer notes](../installer/README.md).
- **Build files:** updated enclosure CAD, mounting-screw documentation, and full/Mini build references. Existing wiring is unchanged.

Update an installed Pi: `motionmodule install main`.

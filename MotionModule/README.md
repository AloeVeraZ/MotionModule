# MotionModule

The full module has **8 motor outputs on 4 dual H-bridge boards**, **16 servo
outputs on one PCA9685**, and a Pi-connected MPU6500 IMU.

Both builds use the same [runtime](../core/motion_module), dashboard, robot API,
watchdog and Driver Station. This folder holds the full build's default
[hardware definition](hardware.py); the shipped default and existing installer
paths stay in place.

- [Full bill of materials](../BOM.md)
- [Full wiring guide](../docs/PINOUT.md)
- [Complete wiring diagram](../docs/images/motionmodule-complete-wiring.png)
- [Enclosure CAD and assembly](../cad/README.md)
- [MotionModule Mini](../MotionModuleMini/README.md)

Install the full module from testing on the Pi:

```bash
motionmodule install testing --variant standard
```

For a fresh install from a repository checkout:

```bash
bash install.sh --version testing --variant standard
```

The dashboard Updates page shows the installed module and branch. Its module
selector can install either build; changing module keeps your active robot project and its files.

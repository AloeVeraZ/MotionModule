<div align="center">

# MotionModule

### A Raspberry Pi motion controller for eight brushed motors and PCA9685 servos

Python robot projects · raised-wheel diagnostics · wireless editing · explicit version rollback

</div>

MotionModule is an FTC-style teaching controller inspired by the direct
deployment workflow of Systemcore/Motioncore, built around ordinary Raspberry
Pi hardware. Four dual H-bridge boards control eight brushed DC motors; one or
more I2C PCA9685 boards provide 16 servo channels each. The included
`examples/Mecanum` project is the student-editable example and fixes the City Tech robot's rotation
mix by keeping wheel polarity in configuration instead of changing the
kinematics.

> [!CAUTION]
> This is developmental lab hardware, not an approved FTC competition control
> system. Raise all wheels, fuse every power branch, and keep a physical power
> cutoff within reach during commissioning.

## Hardware

Start with the root-level **[bill of materials](BOM.md)**, which lists the exact
Amazon motor and servo boards plus the still-to-be-sized power, fuse, wiring,
and connector parts.

The reference build uses the exact boards supplied for this project:

- [GODIYMODULES 3–18 V, 10 A dual H-bridge motor driver](https://www.amazon.com/dp/B0FKH352D2), four boards for eight motors.
- [AITRIP PCA9685 16-channel I2C servo controller](https://www.amazon.com/dp/B07WS5XY63), address `0x40` by default.
- Raspberry Pi 5 with a 40-pin header and current Raspberry Pi OS (the current tested target).
- Separate, fused motor and servo power rails sized for the actual stall current.
- A 10 kΩ pull-down from every H-bridge input to signal ground so motors stay
  disabled while the Pi is booting or shut down.

The motor board accepts PWM through its four inputs at up to 2 kHz. MotionModule
uses 1 kHz and never energizes both directions of one motor simultaneously. The
PCA9685 runs its 16 outputs without consuming 16 Pi pins and can be expanded by
assigning unique I2C addresses.

See the complete [pinout and power boundaries](docs/PINOUT.md) before wiring.

## Repository layout

```text
MotionModule repository/
├── core/motion_module/        # Reusable motor, servo, safety, and web runtime
├── installer/                 # Pi setup, services, Wi-Fi, versions, rollback
├── config/default.toml        # Eight-motor and PCA9685 hardware defaults
├── docs/                      # Pinout, setup, coding, and architecture
├── tests/                     # Hardware-independent validation
├── examples/                  # Copyable robot styles; not system code
│   └── Mecanum/
├── BOM.md                     # Complete reference hardware list
├── install.sh                 # One-line and local installation entry point
├── requirements.txt
└── pyproject.toml
```

`core/motion_module` is not robot-specific code. It is the installed Python
engine that safely controls GPIO, motors, servos, the watchdog, networking, and
the dashboard. Everything needed to install and run MotionModule is visible at
the repository root. `examples/Mecanum` is only a copyable starting project.

## Install on the Raspberry Pi

Flash current Raspberry Pi OS, create a normal sudo-capable user, enable SSH,
and connect the Pi to Wi-Fi or Ethernet. Then SSH into it and run:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | bash
```

Do not put `sudo` before that command. For a classroom with multiple modules,
give each a unique hostname:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --hostname motionmodule-01
```

The installer creates:

| Item | Location |
| --- | --- |
| Robot projects | `~/MotionModule/robots/PROJECT_NAME` |
| Active project | `~/MotionModule/active` symlink |
| Persistent hardware config | `~/.config/motionmodule/config.toml` |
| Versioned runtimes | `~/.local/share/motionmodule/releases` |
| Active system service | `motionmodule.service` |
| Wi-Fi failover service | `motionmodule-network.service` |
| Saved network settings | `/etc/motionmodule/network.json` |

It never enables automatic updates and never overwrites an existing robot
project folder or hardware configuration. At the end it automatically runs
`motionmodule doctor`, links to the GitHub pinout, and reboots. Use
`--no-reboot` only when another provisioning step must run first. Rerun the
doctor check after wiring and before applying motor power.

## Connect, edit, and run

The recommended workflow is VS Code Remote‑SSH over the Pi's saved Wi-Fi or
Ethernet connection:

```bash
ssh YOUR_PI_USER@motionmodule.local
```

In VS Code, install **Remote - SSH**, connect to the same address, and open
`~/MotionModule`. Saving changes edits the code directly on the Pi. Apply them
with:

```bash
motionmodule restart
motionmodule logs
```

Open `http://motionmodule.local` or type the Pi's IP address directly into a
browser. Nginx accepts normal HTTP on port 80 and forwards it to the versioned
MotionModule dashboard. Overview shows live motor, servo, controller, and
network state. Debug combines the complete 40-pin diagram, four-driver/servo
wiring, guarded bench tests, Doctor warnings, service logs, and Wi-Fi setup.
Its servo test selects PCA9685 channels 0–15 and includes goBILDA 300°,
5-turn/1800°, continuous-rotation, and generic positional profiles, plus a
dedicated zero/neutral command. Code contains the editing workflow and guarded
manual drive controls.

At every boot the Pi first uses the Wi-Fi configured in Raspberry Pi Imager (or
the most recently saved network). If no client Wi-Fi connects within 30 seconds,
it automatically creates the protected `MotionModule` hotspot. Join it with the
fresh-install password `motionrobot`, then open `http://10.42.0.1`. A
manually requested hotspot lasts for the current boot; rebooting tries preferred
Wi-Fi first again.

The dashboard belongs to the active versioned runtime. Updating or rolling back
MotionModule changes the interface and backend together, while the existing
robot project folders remain untouched.

Read [setup and commissioning](docs/SETUP.md) and the
[coding guide](docs/CODING.md)
for the full workflow.

## Add or switch robot projects

Every direct folder in `~/MotionModule/robots` that contains `robot.py` is a
robot project. `examples/Mecanum` is copied there as the default on first
installation, but the runtime is reusable:

```text
~/MotionModule/
├── active -> robots/Swerve/
└── robots/
    ├── Mecanum/
    │   └── robot.py
    ├── Swerve/
    │   └── robot.py
    └── WalkingRobot/
        └── robot.py
```

List or activate them without reinstalling the system:

```bash
motionmodule project list
motionmodule project Swerve
```

Repository examples can also be selected during installation with
`--robot PROJECT_NAME`. The selected project appears in the dashboard Code page.

## Diagnostics and versions

```bash
motionmodule pinout
motionmodule doctor
motionmodule test-motor 1
motionmodule test-servo 0 --board 0 --angle 90
motionmodule project list
motionmodule versions
motionmodule install main
motionmodule rollback
motionmodule hotspot status
```

Motor drivers expose inputs only, so software cannot identify whether a driver
or motor is physically connected. `doctor` validates GPIO/I2C/software state;
the explicitly confirmed low-power motor pulse is the physical test. PCA9685
boards do acknowledge their addresses and are detected non-destructively.

## Development

All safety and kinematics tests run without Raspberry Pi hardware:

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
python -m motion_module pinout
python -m motion_module doctor
```

Set `MOTIONMODULE_MOCK=1` on a Pi to run the complete application without
claiming GPIO.

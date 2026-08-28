<div align="center">

# MotionModule

### A Raspberry Pi motion controller for eight brushed motors and PCA9685 servos

Python robot projects · raised-wheel diagnostics · wireless editing · explicit version rollback

</div>

MotionModule is an FTC-style teaching controller inspired by the direct
deployment workflow of Systemcore/Motioncore, built around ordinary Raspberry
Pi hardware. Four dual H-bridge boards control eight brushed DC motors; one or
more I2C PCA9685 boards provide 16 servo channels each. The included `Mecanum`
project is the student-editable example and fixes the City Tech robot's rotation
mix by keeping wheel polarity in configuration instead of changing the
kinematics.

> [!CAUTION]
> This is developmental lab hardware, not an approved FTC competition control
> system. Raise all wheels, fuse every power branch, and keep a physical power
> cutoff within reach during commissioning.

## Hardware

The reference build uses the exact boards supplied for this project:

- [GODIYMODULES 3–18 V, 10 A dual H-bridge motor driver](https://www.amazon.com/dp/B0FKH352D2), four boards for eight motors.
- [AITRIP PCA9685 16-channel I2C servo controller](https://www.amazon.com/dp/B07WS5XY63), address `0x40` by default.
- Raspberry Pi 4 with a 40-pin header and current Raspberry Pi OS (the tested target).
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
MotionModule/
├── Mecanum/                  # Student robot.py, wheel math, browser controls
├── config/default.toml       # Eight-motor and PCA9685 reference configuration
├── docs/                     # Pinout, setup, coding, and architecture
├── installer/                # Pi installer, services, version CLI, Wi-Fi controller
├── motion_module/            # Reusable motor/servo/safety runtime
├── tests/                    # Hardware-independent validation
├── install.sh                # Local and one-line installation entry point
└── pyproject.toml
```

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
| Student code | `~/MotionModule/Mecanum` |
| Persistent hardware config | `~/.config/motionmodule/config.toml` |
| Versioned runtimes | `~/.local/share/motionmodule/releases` |
| Active system service | `motionmodule.service` |
| Wi-Fi failover service | `motionmodule-network.service` |
| Saved network settings | `/etc/motionmodule/network.json` |

It never enables automatic updates and never overwrites an existing student
`Mecanum` folder or hardware configuration. At the end it automatically runs
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

Open `http://motionmodule.local:8080` for the Mecanum browser driver station.
The gear button opens network settings: it shows the current IP, scans nearby
networks, saves a new preferred network, and can start the robot hotspot.

At every boot the Pi first uses the Wi-Fi configured in Raspberry Pi Imager (or
the most recently saved network). If no client Wi-Fi connects within 30 seconds,
it automatically creates the protected `MotionModule` hotspot. Join it with the
fresh-install password `motionrobot`, then open `http://10.42.0.1:8080`. A
manually requested hotspot lasts for the current boot; rebooting tries preferred
Wi-Fi first again.

Read [setup and commissioning](docs/SETUP.md) and the [coding guide](docs/CODING.md)
for the full workflow.

## Diagnostics and versions

```bash
motionmodule pinout
motionmodule doctor
motionmodule test-motor 1
motionmodule test-servo 0 --board 0 --angle 90
motionmodule versions
motionmodule install v0.1.0
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
python -m unittest discover -s tests -v
python -m motion_module pinout
python -m motion_module doctor
```

Set `MOTIONMODULE_MOCK=1` on a Pi to run the complete application without
claiming GPIO.

# MotionModule

MotionModule is a Raspberry Pi robot controller for eight brushed motors and
PCA9685 servo boards. It is an independent, FTC-style system inspired by the
idea of combining a Control Hub and Expansion Hub, but it does not use or
depend on that hardware or software.

The reusable runtime owns GPIO, I2C, safety, networking, diagnostics, and the
browser dashboard. Each robot is one separate Python folder containing its own
behavior and hardware map, so the same installation can run a Mecanum, tank,
walking, or other robot.

> [!CAUTION]
> MotionModule is developmental lab hardware, not an approved competition
> controller. Fuse every power branch, keep a physical motor-power cutoff in
> reach, and raise the wheels for initial tests.

## Hardware

See the root-level **[bill of materials](BOM.md)** for the reference parts:

- four dual H-bridge boards for eight brushed-motor outputs;
- one or more PCA9685 I2C boards, with 16 servo channels per board;
- Raspberry Pi 5 with a 40-pin header;
- separate, fused motor and servo power supplies; and
- a 10 kΩ pull-down from every H-bridge input to signal ground.

Read the complete **[pinout and power boundaries](docs/PINOUT.md)** before
wiring. Never connect motor battery positive or the PCA9685 servo V+ rail to a
Pi header power pin.

## Install on a Raspberry Pi

In Raspberry Pi Imager, install current Raspberry Pi OS, create a normal
sudo-capable user, enable SSH for initial administration, and enter the Wi-Fi
the robot should prefer. Boot the Pi, connect once, and run:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | bash
```

Do not put `sudo` before that command. The installer:

1. installs all OS and Python dependencies;
2. creates a versioned runtime and persistent robot workspace;
3. configures the dashboard, GPIO/I2C access, mDNS, and Wi-Fi fallback;
4. runs the non-moving MotionModule Doctor automatically;
5. prints the GitHub pinout as its final message; and
6. reboots the Pi.

The first install uses hostname `motionmodule`. Give multiple robots unique
names with `--hostname motionmodule-01`. Updates are always explicit; no
automatic updater is installed.

## Connect to the robot UI

Put the computer on the same Wi-Fi as the Pi and open this in Chrome or Edge:

```text
http://motionmodule.local
```

The Pi's numeric IP also works. If no saved Wi-Fi connects within 30 seconds,
the robot creates its fallback hotspot:

```text
Network:  MotionModule
Password: motionrobot
Website:  http://10.42.0.1
```

The same Driver Station and deployment flow works through normal Wi-Fi,
Ethernet, or the robot hotspot. Debug shows the current hostname and every IP,
can scan and join another network, can start the hotspot for the current boot,
and can rename the robot. A reboot always tries saved Wi-Fi first.

## Dashboard

- **Overview** shows live motor output, servo commands and I2C responses,
  watchdog state, temperature, memory, disk, uptime, and network status.
- **Debug** combines the full generic GPIO pinout, driver and servo wiring,
  USB-device inventory, guarded hardware tests, Doctor, logs, useful commands,
  Wi-Fi, hostname, and hotspot controls.
- **Code** is the browser Driver Station. It deploys one local Python robot
  folder, shows communications/code/network/output state, provides guarded
  keyboard drive, and includes the time-limited web terminal.

## Deploy robot code from the browser

No editor plugin or remote coding connection is required. Code the project in
any local editor, then:

1. Open **Code** in the robot dashboard.
2. Press **Choose one robot project folder**.
3. Select the whole folder containing `robot.py` and `hardware.py`.
4. Review the files, accept the stop/restart confirmation, and press
   **Deploy and run**.
5. Wait for the dashboard to reconnect after the service restarts.

The Pi accepts Python and project documentation only, checks every Python file,
parses `hardware.py` without executing it, validates the pins and safety limits,
stops all outputs, backs up an older project with the same name, atomically
installs the new folder, makes it active, and restarts MotionModule. A validation
error leaves the working project in place.

Press **Download Mecanum sample** on that page for a complete starting folder.
Unzip it, rename the folder, edit it locally, and deploy the renamed folder.

## Robot project format

Every project is self-contained:

```text
MyRobot/
├── robot.py          # required browser-control entry point
├── hardware.py       # required pins and electrical settings
├── drivetrain.py     # optional Python modules
├── mechanisms.py
└── README.md         # optional project notes
```

### `hardware.py`

`hardware.py` contains exactly one literal `HARDWARE` dictionary. It cannot
contain imports, function calls, calculations, or executable setup code. This
lets MotionModule validate an uploaded pinout without running student code.

```python
HARDWARE = {
    "module": {
        "pwm_hz": 1000,
        "deadtime_ms": 15,
        "watchdog_ms": 500,
    },
    "motors": {
        1: {
            "name": "left_drive",
            "forward_gpio": 12,
            "reverse_gpio": 6,
            "inverted": True,
        },
        2: {
            "name": "right_drive",
            "forward_gpio": 19,
            "reverse_gpio": 16,
            "inverted": False,
        },
    },
    "servos": {
        "enabled": True,
        "i2c_bus": 1,
        "frequency_hz": 50,
        "addresses": [0x40],
        "minimum_pulse_us": 500,
        "maximum_pulse_us": 2500,
    },
}
```

Use BCM GPIO numbers in this file. Debug converts them to physical header pins.
The included Mecanum sample contains the complete eight-motor reference map.
Older installed projects without `hardware.py` continue to use the persistent
`~/.config/motionmodule/config.toml` fallback, but every new browser deployment
must include `hardware.py`.

### `robot.py`

`robot.py` must define `create_drive(module)`. Return an object with
`drive(forward, strafe, rotate, speed)` and `stop()` methods. Do not move
hardware or start a permanent loop at import time, because the dashboard loads
this file during startup.

This is a complete two-sided drive example:

```python
def clamp(value):
    return max(-1.0, min(1.0, value))


class TankDrive:
    def __init__(self, module):
        self.module = module

    def drive(self, forward, strafe, rotate, speed=0.5):
        left = forward + rotate
        right = forward - rotate
        scale = max(1.0, abs(left), abs(right))
        outputs = {
            1: clamp(left / scale * speed),
            2: clamp(left / scale * speed),
            3: clamp(right / scale * speed),
            4: clamp(right / scale * speed),
        }
        self.module.set_motors(outputs)
        return {"outputs": outputs}

    def stop(self):
        self.module.set_motors({1: 0, 2: 0, 3: 0, 4: 0})


def create_drive(module):
    return TankDrive(module)
```

The Driver Station supplies values from `-1.0` to `1.0` for `forward`,
`strafe`, and `rotate`; `speed` is its `0.0` to `1.0` limit. The returned
dictionary must contain JSON-compatible data.

### Motors

Motor channels are 1–8. Use a single channel for a mechanism:

```python
intake = module.motor(5)
intake.set(0.30)
intake.stop()
```

Update a drivetrain together:

```python
module.set_motors({1: 0.4, 2: 0.4, 3: 0.4, 4: 0.4})
```

Values are clamped to `-1.0` through `1.0`. MotionModule applies the project
inversion map, inserts coast time before a direction reversal, and refreshes
the watchdog. Keep nonzero commands arriving faster than the configured
watchdog timeout and call `module.stop_all()` for a whole-robot stop.

### Servos

PCA9685 boards count from 0, and each has channels 0–15:

```python
claw = module.servo(channel=0, board=0)
claw.set_angle(30)
claw.set_angle(110)
claw.release()
```

For a calibrated positional or continuous-rotation servo, use a verified pulse
inside the configured range:

```python
claw.set_pulse_us(1500)
```

The Debug servo tool includes generic 180°/360° position profiles and goBILDA
position, five-turn, and continuous-rotation profiles. `release()` disables
the PWM signal; it does not first move a mechanism to a safe pose.

## What MotionModule can detect

- A PCA9685 can acknowledge its I2C address, so Debug reports detected or no
  response for each configured board.
- USB devices identify themselves. Debug lists their product, vendor/product
  ID, Pi port, Linux driver, device file, and whether the service user has
  access. This is live inventory, not firmware management.
- The reference H-bridge inputs and ordinary servos have no return data. The Pi
  cannot prove that a board, motor, or servo is plugged into those output-only
  wires. Debug labels those outputs as configured but unverified; use the
  guarded low-power bench tests with the robot raised.

## How the system works together

```text
Chrome / Edge on robot network
          │ HTTP
          ▼
       Nginx :80
          │ local proxy
          ▼
MotionModule dashboard + active Python project
          ├── GPIO PWM → four H-bridges → eight motor outputs
          ├── I2C → PCA9685 board(s) → servo channels
          ├── sysfs → read-only USB inventory
          └── watchdog → stops stale motor commands
```

The service loads `~/MotionModule/active/robot.py`. `active` points to one
folder under `~/MotionModule/robots`; browser uploads preserve previous copies
under `~/MotionModule/backups`. Runtime releases live separately, so installing
or rolling back MotionModule does not overwrite robot projects.

The network service tries saved Wi-Fi for 30 seconds and creates the fallback
hotspot only when none connects. Nginx provides the same port-80 page in either
mode.

## Debugging and terminal

Use this order:

1. Open **Debug** and inspect warnings, the generic pinout, USB/I2C devices,
   network addresses, and service log.
2. Run `motionmodule doctor`; it does not intentionally move hardware.
3. Run `motionmodule pinout` and compare every wire before applying power.
4. Raise the robot and use the guarded Motor Bench Test at low power.
5. Select the correct board, channel, and behavior in Servo Pulse Test.
6. Check `motionmodule logs` after a failed project start.

The web terminal at the bottom of Code is a real, unprivileged Bash shell. For
security it needs a short-lived code created during an admin SSH session:

```bash
motionmodule terminal enable       # valid for 15 minutes
motionmodule terminal enable 30    # choose 1–120 minutes
motionmodule terminal disable
```

Enter the printed code in the webpage. The grant expires automatically, is
invalid after reboot, and an idle shell closes after five minutes. The robot UI
uses HTTP, so never put reusable passwords or tokens in this terminal and never
expose it to the public internet.

Useful commands are also explained inside Debug:

| Command | Purpose |
| --- | --- |
| `motionmodule status` | Show the service state |
| `motionmodule doctor` | Run non-moving checks |
| `motionmodule pinout` | Print the physical wiring map |
| `motionmodule restart` | Stop outputs and reload the active project |
| `motionmodule logs` | Follow Python and service output |
| `motionmodule project list` | List installed robot folders |
| `motionmodule project NAME` | Select another installed folder |
| `motionmodule versions` | List installed runtime versions |
| `motionmodule rollback` | Activate the previous runtime |

## Updates and development

Runtime changes are explicit:

```bash
motionmodule install main
motionmodule versions
motionmodule rollback
```

To test the repository without robot hardware:

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
python -m motion_module doctor
```

Set `MOTIONMODULE_MOCK=1` on a Pi to avoid claiming GPIO and I2C hardware.
Detailed references are in [Setup](docs/SETUP.md), [Coding](docs/CODING.md),
[Pinout](docs/PINOUT.md), and [Architecture](docs/ARCHITECTURE.md).

## Repository layout

```text
MotionModule/
├── core/motion_module/    # controller, safety, dashboard, deploy, USB, network
├── installer/             # Pi install, services, Wi-Fi, versions, rollback
├── config/default.toml    # compatibility/default hardware configuration
├── docs/                  # setup, coding, pinout, and architecture
├── examples/
│   └── Mecanum/           # complete downloadable Python robot folder
│       ├── robot.py
│       ├── hardware.py
│       └── mecanum.py
├── tests/                 # hardware-independent automated tests
├── BOM.md
├── install.sh
├── requirements.txt
└── pyproject.toml
```

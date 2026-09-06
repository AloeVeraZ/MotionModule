# MotionModule

MotionModule is a Raspberry Pi robot controller for eight brushed motors and
PCA9685 servo boards. It is an independent, FTC-style system inspired by the
idea of combining a Control Hub and Expansion Hub, but it does not use or
depend on that hardware or software.

The reusable runtime owns GPIO, I2C, safety, networking, diagnostics, and the
browser dashboard. Each robot is one separate Python folder containing its own
behavior and an optional hardware map, so the same installation can run a Mecanum, tank,
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

The exact motor-driver and PCA9685 products are recorded. The motor and servo
models, battery, regulator ratings, and fuse/wire sizing are still unspecified;
**Debug → Parts** lists those open choices alongside the complete reference
BOM. Parts and wiring instructions are available inside the app without an
internet connection.

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

Three pages, each split into tabs:

- **Overview** — live motor power labelled with your own names, servo commands
  and I2C responses, watchdog state, temperature, memory, disk, uptime, network
  status, and a three-step guide for a first-time build.
- **Debug** — **Wiring** (colour-coded 40-pin header map, driver and servo
  wiring, separate 16-output servo-board diagrams, the names you can use in
  code, and USB inventory), **Parts** (complete reference BOM and missing
  specifications),
  **Tests** (guarded raised-wheel motor and servo tests, chosen by name),
  **Checks & logs** (Doctor, service log, command reference), and **Network**
  (Wi-Fi, hostname, hotspot).
- **Code** — the browser Driver Station: **Deploy** a local Python folder,
  **Drive** it from the keyboard, and open the time-limited **Terminal**.

## Deploy robot code from the browser

No editor plugin or remote coding connection is required. Code the project in
any local editor, then:

1. Open **Code → Deploy** in the robot dashboard.
2. Press **Choose your robot folder**.
3. Select the whole folder containing `robot.py`.
4. Review the files, accept the stop/restart confirmation, and press
   **Deploy and run**.
5. Wait for the dashboard to reconnect after the service restarts.

The Pi accepts Python and project documentation only, checks every Python file,
parses any `hardware.py` without executing it, validates the pins and safety
limits, stops all outputs, backs up an older project with the same name,
atomically installs the new folder, makes it active, and restarts MotionModule.
A validation error leaves the working project in place.

Press **Download Mecanum sample** on that page for a complete starting folder.
Unzip it, rename the folder, edit it locally, and deploy the renamed folder.

## One hardware definition file

MotionModule ships with one editable `hardware.py` containing every motor's
name, BCM pin pair, inversion setting and driver/output explanation, plus
servo names, board addresses and timing settings. The installed copy is
`~/.config/motionmodule/hardware.py`. Debug and Code offer a download of the
configuration currently in use.

Your smallest browser project needs only `robot.py`: it uses the installed
hardware map. Add a `hardware.py` next to it when that robot needs different
names or wiring. MotionModule uses the project copy first, then the installed
map, then the default shipped with the runtime. Existing TOML configurations
remain supported for compatibility.

Use the names directly in your robot code:

```python
module.motor("motor_1").set(0.25)
module.servo("servo_1").set_angle(90)
module.stop_all()
```

The Mecanum sample's own hardware file names its four wheels `front_left`,
`rear_left`, `front_right` and `rear_right`, preserving the tested pinout and
inversions. For your own robot, change a name in the hardware file and use
that name in code. No second pin-definition or driver-wrapper file is needed.

## Robot project format

Every project is self-contained, and only the first file is required:

```text
MyRobot/
├── robot.py          # required browser-control entry point
├── hardware.py       # optional: your own names, pins, and inversions
├── drivetrain.py     # optional Python modules
├── mechanisms.py
└── README.md         # optional project notes
```

### `hardware.py`

A project folder does not need this file. Include it only when this robot
needs its own names or wiring; without it, the robot uses the installed
hardware map described above.

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

Use BCM GPIO numbers in this file. Debug converts them to physical header pins
and lists every name it defines. The shipped `hardware.py` contains the complete
eight-motor reference map with a comment showing each output's driver, header
pin, and GPIO, so the easiest way to start is to download it from Debug or Code
and rename the outputs you actually use.

Every name must be unique across motors and servos, and must start with a
letter and use only letters, numbers, and underscores.

### `robot.py`

`robot.py` must define `create_drive(module)`. Return an object with
`drive(forward, strafe, rotate, speed)` and `stop()` methods. Do not move
hardware or start a permanent loop at import time, because the dashboard loads
this file during startup.

This is a complete two-sided drive example:

```python
LEFT = ("motor_1", "motor_2")
RIGHT = ("motor_3", "motor_4")


def clamp(value):
    return max(-1.0, min(1.0, value))


class TankDrive:
    def __init__(self, module):
        self.module = module

    def drive(self, forward, strafe, rotate, speed=0.5):
        left = forward + rotate
        right = forward - rotate
        scale = max(1.0, abs(left), abs(right))
        outputs = {name: clamp(left / scale * speed) for name in LEFT}
        outputs.update({name: clamp(right / scale * speed) for name in RIGHT})
        self.module.set_motors(outputs)
        return {"outputs": outputs}

    def stop(self):
        self.module.set_motors({name: 0 for name in LEFT + RIGHT})


def create_drive(module):
    return TankDrive(module)
```

Those four names come from the shipped `hardware.py`. Rename them there to
`left_front`, `right_rear`, or whatever matches your machine, and use the new
names here.

The Driver Station supplies values from `-1.0` to `1.0` for `forward`,
`strafe`, and `rotate`; `speed` is its `0.0` to `1.0` limit. The returned
dictionary must contain JSON-compatible data.

### Motors

Use a name from the active `hardware.py`, or a motor channel from 1–8:

```python
intake = module.motor("motor_5")  # or module.motor(5)
intake.set(0.30)
intake.stop()
```

Update a drivetrain together, by name or by channel:

```python
module.set_motors({"motor_1": 0.4, "motor_2": 0.4, "motor_3": 0.4, "motor_4": 0.4})
```

Values are clamped to `-1.0` through `1.0`. MotionModule applies the project
inversion map, inserts coast time before a direction reversal, and refreshes
the watchdog. Keep nonzero commands arriving faster than the configured
watchdog timeout and call `module.stop_all()` for a whole-robot stop.

### Servos

Use a servo name, or an explicit board/channel pair. PCA9685 boards count
from 0, and each has channels 0–15:

```python
claw = module.servo("servo_1")  # or module.servo(channel=0, board=0)
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

1. Open **Debug** and inspect warnings, the active pinout, USB/I2C devices,
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
│   ├── hardware.py        # the shipped pin and name definitions
│   └── hardware_guide.py  # offline parts list and wiring reference
├── installer/             # Pi install, services, Wi-Fi, versions, rollback
├── docs/                  # setup, coding, pinout, and architecture
├── examples/
│   └── Mecanum/           # complete downloadable Python robot folder
│       ├── robot.py
│       └── hardware.py
├── tests/                 # hardware-independent automated tests
├── BOM.md
├── install.sh
├── requirements.txt
└── pyproject.toml
```

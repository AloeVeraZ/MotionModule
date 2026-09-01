<div align="center">

# MotionModule

### A Raspberry Pi motion controller for eight brushed motors and PCA9685 servos

Python robot projects · hardware diagnostics · wireless editing · explicit rollback

</div>

MotionModule is an independent, FTC-style robot control project inspired by the
way a REV Control Hub and Expansion Hub combine robot I/O in one system. It is
not affiliated with, built from, or dependent on that control system;
it uses a Raspberry Pi, ordinary H-bridge boards, PCA9685 servo controllers,
and its own Python software.

Four dual H-bridge boards provide eight brushed-motor outputs. One or more I2C
PCA9685 boards provide 16 servo channels each. Robot behavior lives in separate
project folders, so the same MotionModule installation can run a Mecanum,
tank-drive, walking, or other robot without making the core runtime specific to
one machine.

> [!CAUTION]
> MotionModule is developmental lab hardware, not an approved competition
> control system. Raise all wheels, fuse every power branch, and keep a physical
> motor-power cutoff within reach during commissioning.

## Hardware

Start with the root-level **[bill of materials](BOM.md)**. The reference build
uses:

- [GODIYMODULES 3–18 V, 10 A dual H-bridge motor driver](https://www.amazon.com/dp/B0FKH352D2), four boards for eight motor outputs.
- [AITRIP PCA9685 16-channel I2C servo controller](https://www.amazon.com/dp/B07WS5XY63), address `0x40` by default.
- A Raspberry Pi 5 with a 40-pin header and current Raspberry Pi OS.
- Separate, fused motor and servo power rails sized for the real motors' stall
  current and the servos' combined load.
- A 10 kΩ pull-down from every H-bridge input to signal ground, so the drivers
  remain disabled while the Pi boots or is shut down.

MotionModule sends 1 kHz PWM to the motor-driver inputs and inserts a coast
interval before reversing direction. The PCA9685 generates servo PWM without
using one Raspberry Pi pin per servo. Additional PCA9685 boards can be added at
unique I2C addresses.

Read the complete **[pinout and power boundaries](docs/PINOUT.md)** before
wiring. Motor battery positive and servo V+ must never connect to a Raspberry
Pi header power pin.

## Install on the Raspberry Pi

Flash Raspberry Pi OS, create a normal sudo-capable user, enable SSH, and enter
the initial Wi-Fi information in Raspberry Pi Imager. Boot the Pi, connect over
SSH, and run:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | bash
```

Do not put `sudo` before the command. A first install automatically names the
Pi `motionmodule`, so its dashboard is normally `http://motionmodule.local`.
The **Debug → Robot identity** panel shows the hostname, Pi username, exact SSH
target, and current IP addresses. It can also change the hostname later. For
multiple robots, assign each one a unique hostname during installation:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --hostname motionmodule-01
```

The installer creates:

| Item | Location |
| --- | --- |
| Robot projects | `~/MotionModule/robots/PROJECT_NAME` |
| Active project | `~/MotionModule/active` symlink |
| Project backups | `~/MotionModule/backups` |
| Persistent hardware config | `~/.config/motionmodule/config.toml` |
| Versioned runtimes | `~/.local/share/motionmodule/releases` |
| Robot service | `motionmodule.service` |
| Wi-Fi failover service | `motionmodule-network.service` |
| Saved network settings | `/etc/motionmodule/network.json` |

Installation never enables automatic updates and never overwrites an existing
robot project or hardware configuration. It runs the non-moving Doctor check,
prints the pinout link, and reboots automatically.

## Open the robot dashboard

From a computer on the same network, open:

```text
http://motionmodule.local
```

The Pi's IP address also works directly. The dashboard contains:

- **Overview:** live controller, motor-output, servo-board, temperature,
  uptime, health, and network status.
- **Debug:** generic Driver 1A–Driver 4B wiring, the complete Pi header,
  guarded motor and servo tests, Doctor, logs, useful commands, Wi-Fi, and
  hotspot controls.
- **Code:** the VS Code setup, guarded keyboard drive, and the time-limited web
  terminal.

## How robot code works

MotionModule runs exactly one active robot project. On service startup it
imports:

```text
~/MotionModule/active/robot.py
```

That file must define `create_drive(module)`. MotionModule calls it once and
expects a drive object with these two methods:

```python
drive(forward, strafe, rotate, speed) -> dict
stop() -> None
```

The browser's W/A/S/D and Q/E controls repeatedly call `drive(...)`. Releasing
a key sends a new zeroed drive command; Space, STOP, or leaving the page sends a
stop request. If the browser disappears before that request arrives, the 500 ms
watchdog shuts down stale motor output. Saving a file does not reload it;
`motionmodule restart` or a successful local push starts the new code.

Do not start a permanent loop or move hardware at the top level of `robot.py`.
Top-level code runs while the service imports the file and can prevent the
dashboard from starting.

### Robot project structure

A project can be one file or several normal Python modules:

```text
MyRobot/
├── robot.py          # Required entry point
├── drivetrain.py     # Drive math and channel mapping
├── mechanisms.py     # Arm, intake, claw, or other helpers
└── README.md         # Notes for this specific robot
```

Imports are relative to the project folder, so `robot.py` can use
`from drivetrain import TankDrive`. The installed `examples/Mecanum` project is
a working multi-file example.

### Example: write a tank drive

This complete `robot.py` maps the left side to motor channels 1–2 and the right
side to channels 3–4. Robot-specific names belong here, while Debug continues
to show only the generic driver outputs.

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

The four input values supplied by the dashboard are:

| Argument | Range | Meaning |
| --- | ---: | --- |
| `forward` | `-1.0` to `1.0` | Backward to forward |
| `strafe` | `-1.0` to `1.0` | Left to right; a tank drive may ignore it |
| `rotate` | `-1.0` to `1.0` | Turn in either direction |
| `speed` | `0.0` to `1.0` | Dashboard maximum-speed setting |

The returned dictionary must contain JSON-compatible values because it becomes
part of the dashboard API response.

### Control motors

Motor channels are numbered 1–8. A single output can be controlled with a
handle:

```python
intake = module.motor(5)
intake.set(0.30)   # +1.0 full forward; -1.0 full reverse
intake.stop()
```

For a drivetrain, update all related channels together:

```python
module.set_motors({1: 0.4, 2: 0.4, 3: 0.4, 4: 0.4})
```

`set_motors()` clamps values to `-1.0` through `1.0`, applies configured motor
inversion, inserts shared reversal deadtime, and refreshes the watchdog. Keep
refreshing nonzero output faster than the configured 500 ms timeout. Use
`module.stop_all()` when the whole robot must stop.

The channel-to-driver/pin mapping comes from
`~/.config/motionmodule/config.toml` and is shown on the Debug page. Decide what
those channels mean—left wheel, arm motor, intake, or something else—inside the
robot project.

### Control servos

PCA9685 boards count from `0`; every board has channels `0`–`15`:

```python
claw = module.servo(channel=0, board=0)
claw.set_angle(30)
claw.set_angle(110)
claw.release()
```

`set_angle()` is the generic 0–180° API. For a calibrated positional or
continuous-rotation servo, send a verified pulse inside the configured safety
range:

```python
claw.set_pulse_us(1500)  # commonly midpoint or neutral; verify the servo first
```

`release()` disables PWM for that channel; it does not move the mechanism to a
safe pose first. Command the safe pose, wait for the motion to finish, and only
then release it if the mechanism should stop holding torque.

A helper method does not automatically create a dashboard button. Something in
the project's control logic must call it. Keep mechanism mappings and behavior
inside the robot project rather than adding robot-specific assumptions to the
MotionModule core.

## Code with VS Code

VS Code is the supported editor. Choose one workflow per project.

### Edit directly on the Pi

The dashboard's **Code** page fills these instructions with this Pi's real
username, hostname, and IP. The username is the account created in Raspberry
Pi Imager; it is not the hostname.

1. In VS Code, open Extensions, install Microsoft's **Remote - SSH** extension,
   then press `Ctrl+Shift+P`.
2. Choose **Remote-SSH: Add New SSH Host…** and paste the full command:

```bash
ssh YOUR_PI_USER@motionmodule.local
```

3. Choose the first SSH configuration file offered. Press `Ctrl+Shift+P` again,
   choose **Remote-SSH: Connect to Host…**, and select the robot.
4. Choose **Linux** if asked, accept the first-connection fingerprint, and
   enter the Pi password created in Raspberry Pi Imager.
5. When VS Code's bottom-left corner says `SSH: motionmodule`, choose **File →
   Open Folder…** and open `/home/YOUR_PI_USER/MotionModule/robots/PROJECT_NAME`.
6. Edit the project, then use the VS Code terminal to reload and inspect it:

```bash
motionmodule restart
motionmodule logs
```

If `motionmodule.local` does not work, the network is probably blocking mDNS
name discovery. Open **Debug**, copy the Pi's current IP, and add the same host
using `ssh YOUR_PI_USER@IP_ADDRESS`. The username and password stay the same.
Do not use `YOUR_PI_USER.local`; the part before `.local` is always the hostname.

### Edit locally, then push

Open a local clone of this repository in VS Code. Copy `examples/Mecanum` to a
new folder such as `robots/MyRobot`, then edit it locally. Local code cannot
move robot hardware.

Choose **Terminal → Run Task → MotionModule: Push robot project**, or run:

```bash
python tools/push_robot.py robots/MyRobot --host YOUR_PI_USER@motionmodule.local
```

The push filters development caches, uploads through SSH, rejects unsafe
archives and Python syntax errors, backs up an existing Pi project, activates
the new copy, restarts MotionModule, and verifies that the service stays
running. Only the successfully installed copy runs on the robot.

## How the system works together

```text
Browser on the robot network
        │ HTTP
        ▼
Nginx on port 80
        │ local proxy
        ▼
MotionModule dashboard service
        ├── loads ~/MotionModule/active/robot.py
        ├── calls the project's drive(...) and stop()
        ├── exposes guarded test and status APIs
        └── owns the hardware controller
                    ├── GPIO PWM → four H-bridges → eight motor outputs
                    └── I2C → PCA9685 board(s) → servo channels
```

The system service starts the selected project at boot and restarts it after a
project switch or code deployment. The hardware controller applies inversion,
reversal deadtime, pulse limits, watchdog shutdown, and final cleanup. The
persistent TOML file describes hardware; the selected project describes robot
behavior. Updating the versioned runtime does not overwrite either one.

The separate network service asks NetworkManager to use saved Wi-Fi first. If
no saved network connects within 30 seconds, it starts the protected robot
hotspot. Nginx remains the stable browser entry point regardless of which
runtime version is active.

## Debugging and the web terminal

Use this order when something does not work:

1. Open **Debug** and read the hardware warnings, generic driver wiring, servo
   detection, current network addresses, and service log.
2. Run `motionmodule doctor`. It checks software, GPIO configuration, services,
   and I2C without intentionally moving a motor or servo.
3. Run `motionmodule pinout` and compare every physical wire before applying
   motor or servo power.
4. Raise the robot and use the guarded Motor Bench Test at low power. The
   H-bridge boards do not report whether a motor is physically connected, so a
   controlled pulse is the real connection/direction test.
5. Use the Servo Pulse Test to select the exact board, channel, and servo
   behavior. PCA9685 boards acknowledge over I2C, so the dashboard can report a
   missing board before movement.
6. Run `motionmodule logs` after a code change. Import errors, exceptions, and
   service startup failures appear there.

The web terminal is at the bottom of **Code**. It is a real Bash shell running
as the normal Pi user, but it is deliberately locked by default. Enable a
temporary grant over SSH:

```bash
motionmodule terminal enable       # 15 minutes
motionmodule terminal enable 30    # custom duration, 1–120 minutes
motionmodule terminal status
```

Enter the printed access code in the page. The grant expires, is bound to the
current boot, and an idle shell closes after five minutes. Disable it early
with:

```bash
motionmodule terminal disable
```

Useful terminal commands include:

| Command | Purpose |
| --- | --- |
| `motionmodule status` | Show the system service state |
| `motionmodule doctor` | Run non-moving system and hardware checks |
| `motionmodule pinout` | Print the physical wiring map |
| `motionmodule restart` | Stop outputs and reload the active project |
| `motionmodule logs` | Follow live service output and Python errors |
| `motionmodule project list` | List robot folders; `*` marks the active one |
| `motionmodule project NAME` | Select another project and restart |
| `motionmodule versions` | List installed runtime versions |
| `motionmodule rollback` | Activate the previous runtime |
| `motionmodule hotspot status` | Show standalone-network state |

The dashboard uses ordinary HTTP on the robot network. Do not enter reusable
passwords, access tokens, or other secrets in the web terminal, and never
expose the dashboard directly to the public internet. Use normal SSH for
privileged administration.

## Wi-Fi and standalone mode

At boot, the Pi tries the Wi-Fi saved by Raspberry Pi Imager or the most
recently selected network. If none connects within 30 seconds, MotionModule
creates this fallback network:

```text
SSID: MotionModule
Initial password: motionrobot
Dashboard: http://10.42.0.1
```

Debug can scan nearby networks, save personal or PEAP credentials, display the
Pi username, hostname, exact SSH target and current addresses, rename the Pi,
reconnect preferred Wi-Fi, or start the hotspot for the current boot. A valid
new hostname contains only letters, numbers, and hyphens; the change survives
reboot and becomes the new `HOSTNAME.local` address. Every network/identity
change stops motor output first. A reboot always tries saved Wi-Fi before
falling back again.

## Projects, updates, and rollback

Every direct folder under `~/MotionModule/robots` that contains `robot.py` is a
robot project. List or activate them without reinstalling:

```bash
motionmodule project list
motionmodule project Swerve
```

Runtime updates are always explicit:

```bash
motionmodule versions
motionmodule install main
motionmodule rollback
```

Updates replace the dashboard and core runtime together while preserving robot
projects and hardware configuration. Local pushes back up the previous copy of
the named robot project under `~/MotionModule/backups`.

For detailed references, see:

- **[Setup and commissioning](docs/SETUP.md)**
- **[Coding guide](docs/CODING.md)**
- **[Pinout](docs/PINOUT.md)**
- **[Architecture](docs/ARCHITECTURE.md)**
- **[Bill of materials](BOM.md)**

## Development without robot hardware

The core tests and simulated dashboard run on a normal development computer:

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
python -m motion_module pinout
python -m motion_module doctor
```

Set `MOTIONMODULE_MOCK=1` on a Pi to run without claiming GPIO or I2C hardware.

## Repository layout

```text
MotionModule repository/
├── core/motion_module/        # Motor, servo, safety, deploy, and web runtime
├── installer/                 # Pi setup, services, Wi-Fi, versions, rollback
├── config/default.toml        # Eight-output and PCA9685 hardware defaults
├── docs/                      # Pinout, setup, coding, and architecture
├── examples/                  # Copyable robot projects; not core system code
│   └── Mecanum/
├── tools/push_robot.py        # Local VS Code-to-robot deployment helper
├── tests/                     # Hardware-independent validation
├── .vscode/tasks.json         # Interactive local push task
├── BOM.md                     # Reference hardware list
├── install.sh                 # One-line and local installation entry point
├── requirements.txt
└── pyproject.toml
```

The repository root contains the complete reusable MotionModule system.
`core/motion_module` is hardware and service infrastructure, while `examples`
and user-created robot folders contain robot-specific behavior.

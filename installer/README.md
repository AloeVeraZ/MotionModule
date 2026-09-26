# Installer behavior

## Upgrading to 0.12.1 (install this, not 0.12.0)

0.12.0 removed the old `GigaIMU` declaration. A robot folder that the
installer kept because it was edited could still import it, and then the
robot's web page would not start (nginx showed "502 Bad Gateway"). 0.12.1
fixes that, so skip 0.12.0 and install 0.12.1 or later:

- Old `sensors.py` files load again. `GigaIMU(...)` from `motion_module.imu`
  or `motion_module.sensor_bridge` now means the one built-in IMU, the MPU6500
  on the Pi, and the service log says so. `module.giga(imus=...)` is accepted
  and ignored; Arduino IMUs are no longer read and report no heading. No other
  IMU driver came back.
- Untouched copies of every Mecanum sample ever shipped are recognised and
  updated automatically; edited robot folders are kept exactly as they are.
- If a robot project still cannot load, the dashboard opens in **recovery
  mode** instead of failing. It shows the real error, stops every output,
  turns the servo outputs off and refuses driving, motor, servo and autonomous
  commands. Logs, Debug checks, Code → Deploy and Update keep working, so a
  fixed folder or a newer release can be installed from the browser.
- On a Raspberry Pi 5 the installer turns on the Pi's own fan control (see
  "Pi 5 fan cooling" below).

When you next edit a customized `sensors.py`, replace the old lines with:

```python
from motion_module.imu import IMUConfig
IMU = IMUConfig("Main IMU", address=0x68)
```

`module.local_imu(IMU)` and `module.local_imu()` both read the MPU6500.
Motor, PCA9685 and IMU wiring are unchanged (IMU GND on physical pin 6, AD0
on physical pin 20).

After installing and restarting, run Debug's checks, keep the robot still
until the Driver Station reports Ready, and zero heading. The software tests
simulate the IMU; confirm calibration, turn direction and live heading on the
physical robot before using IMU-guided driving.

For a source archive, extract it and run `bash install.sh` from the extracted
folder on the Pi. This installs the files in that folder. A wheel alone does
not include the installer, robot samples or Arduino firmware bundle.

## Pi 5 fan cooling

The Pi 5 active cooler plugs into the board's own four-pin FAN connector, not
the 40-pin GPIO header. On a Pi 5 the installer adds one marked `[pi5]` block
to `/boot/firmware/config.txt` (or `/boot/config.txt`) near the top, before
any `dtoverlay=` line, and keeps a dated backup of the file it changed:

| CPU temperature | Fan |
| --- | --- |
| below 50 °C | off (after running, it stops once below 45 °C) |
| 50 °C | level 1, PWM 75 of 255 |
| 60 °C | level 2, PWM 125 |
| 67.5 °C | level 3, PWM 175 |
| 75 °C | level 4, PWM 250 |

These are the firmware's `cooling_fan` and `fan_temp0`-`fan_temp3` settings
(with 5 °C `_hyst` each), so the Pi's firmware and kernel run the fan. It keeps
cooling when MotionModule, the dashboard or the robot project is stopped or
broken. Running the installer again changes nothing; fan settings you wrote
yourself outside the block are left in charge. The change takes effect after
the reboot at the end of the install.

The dashboard's CPU temperature card and Debug checks show the temperature,
the fan level the kernel chose and, when the Pi reports it, the fan's RPM. A
fan that is off while the Pi is below 50 °C is normal. If the Pi is hot and the
fan is asked to run but stays still, switch the Pi off, check the fan's small
plug is pushed fully into the FAN connector, and power on again.

## Running the installer

Run the repository entry point:

```bash
bash install.sh --hostname motionmodule-01
```

Or install a published ref:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --version main --hostname motionmodule-01
```

| Option | Meaning |
| --- | --- |
| `--version REF` | Explicit Git branch, tag, or fetchable commit |
| `--hostname NAME` | Set the Pi's mDNS/browser hostname |
| `--robot PROJECT` | Initial bundled example; defaults to `Mecanum` |
| `--no-hostname` | Preserve the current hostname |
| `--no-start` | Enable without starting services |
| `--no-reboot` | Skip the default final reboot |

The bootstrap downloads the requested ref to a temporary directory. The main
installer adds system dependencies, copies source into a new release, builds a
per-release virtual environment, runs the unit tests, and marks the release
complete. Only then does the `current` link change. Failure before activation
leaves the previous runtime selected.

## Installing replaces MotionModule

An install replaces the MotionModule software instead of adding a version next
to the old ones. That is what makes the `main` and `testing` branches
interchangeable: a Pi on either one can install the other, in either
direction, as often as needed.

```bash
motionmodule install testing   # from main
motionmodule install main      # back again
```

Once the new release is active and its service has stayed up for a few
seconds, the installer removes what older installs left behind:

- every other release in `~/.local/share/motionmodule/releases`;
- MotionModule scripts in `/usr/local/sbin`, sudo rules, systemd services,
  nginx sites, and udev rules that this version does not ship, disabling a
  stale service before deleting it;
- leftover upload archives and any temporary web terminal access code.

It never removes the robot's own files: the projects in
`~/MotionModule/robots`, their backups in `~/MotionModule/backups`, the
`active` project link, the pin names in `~/.config/motionmodule/hardware.py`
(and an older `config.toml`), or the Wi-Fi, hotspot, and hostname settings.

Two releases can remain after an install:

- When the release it replaced came from the same branch, tag, or commit, that
  release stays as the offline `motionmodule rollback` target. A release from
  another branch is always removed, so branches never mix.
- When the new service could not be confirmed running (it crashed, or
  `--no-start` was used), the release it replaced stays, whatever branch it
  came from, as the way back. The next install removes it.

`motionmodule install REF` downloads that ref's own bootstrap, falling back to
`main`'s, so each branch installs with its own scripts even after they
change.

For optional Arduino GIGA R1 WiFi USB GPIO expansion, the installer also installs
`dfu-util`, adds the user to the `dialout` group (its USB serial port) and the
`plugdev` group, and writes `/etc/udev/rules.d/motionmodule-giga.rules`, which
lets that user flash the GIGA's firmware with `motionmodule giga flash`
without sudo. Reboot once after the first install so the groups apply.

Bundled examples are copied into `~/MotionModule/robots` on the first install.
A later install replaces one of those folders only while every file in it is
still a copy MotionModule shipped, so a fix to a sample reaches the robot; the
folder it replaces is kept under `~/MotionModule/backups`, and a folder with
any file of its own is never overwritten. The `active` symlink selects the
project loaded by the dashboard. A project may include its own data-only `hardware.py`;
otherwise the installed `~/.config/motionmodule/hardware.py` supplies the pins
and names. Installs made before that file existed keep using their
`~/.config/motionmodule/config.toml`.

The browser Driver Station accepts one local Python project folder. Deployment
validates paths, size, file types, Python syntax, `robot.py`, and any
`hardware.py`, stops output, backs up an existing target, installs it
atomically, switches
`active`, and cleanly restarts the service. Nginx allows the bounded multipart
upload and exposes the dashboard on port 80.

The installer also configures the root-owned constrained NetworkManager helper
and `motionmodule-network.service`. The helper records active Imager Wi-Fi.
After boot, saved networks receive 30 seconds to connect before the protected
fallback hotspot starts. Browser network changes invoke only fixed helper
actions.

The Code-page Bash terminal remains locked until the Pi user runs
`motionmodule terminal enable [MINUTES]` during an admin SSH session. Its
mode-0600 access grant is temporary and boot-scoped; the terminal receives no
extra sudo access.

After activation, the installer runs the non-moving Doctor check and reboots so
GPIO/I2C membership and boot configuration take effect. Its final printed
message is the GitHub pinout link. Use `--no-reboot` only when provisioning
still has more work to do.

No update service or timer is installed, and nothing installs itself. The
dashboard's update card reads `INSTALL_REF` and `INSTALL_COMMIT` from the
release root, compares them against `git ls-remote` for `main` and `testing`,
and, when you press the button, runs `/usr/local/sbin/motionmodule-update REF`
through the `motionmodule-update` sudoers rule. That helper starts a transient
`systemd-run` unit so the install survives its service restarts, logs to
`/var/log/motionmodule-update.log`, and leaves the installer's default final
Pi reboot enabled. The installer also recognizes that dedicated unit and
overrides the obsolete `--no-reboot` supplied by older dashboard helpers, so
the first update to this behavior reboots too. When `sudo` asks the Pi user for
a password, the dashboard asks for it, checks it with `sudo -S -k`, and passes
it to the helper on stdin. The helper keeps it in a root-only file under
`/run/motionmodule-update` while that update runs, with `SUDO_ASKPASS` set to
`/usr/local/sbin/motionmodule-askpass`. That script fetches it through
`motionmodule-update password`, which the rule also allows, and the helper
answers only processes inside the update's own unit. A second transient unit
deletes the file when the update ends. Runtime changes otherwise require
an explicit `motionmodule install REF`, `motionmodule activate NAME`, or
`motionmodule rollback`. Rollback returns to the earlier release of the same
branch when one is kept; switching branches is always `motionmodule install`.

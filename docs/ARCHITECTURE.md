# Runtime and update architecture

## Control path

```text
browser → nginx :80 → versioned dashboard :8080
                           │
                           ├── browser project deployment
active robot folder ───────┤
                           ├── GPIO PWM → four dual H-bridges → eight motors
                           ├── unused Pi GPIO → digital sensor inputs
                           ├── I2C → PCA9685 board(s) → servos
                           ├── USB serial → Arduino GIGA → IMUs and sensor pins
                           ├── dfu-util → GIGA bootloader (firmware installs)
                           └── time-limited PTY Bash terminal
```

All motor writes share a lock. A logical sign reversal coasts all motors for
the configured deadtime, and a watchdog stops all output after the configured
period without a control heartbeat. GPIO starts low and is forced low on normal
shutdown and handled Python exceptions. Software safety does not replace a
fused power system and physical cutoff.

## Runtime and project separation

```text
~/.local/share/motionmodule/
├── current -> releases/main-...
├── previous -> releases/main-...        # only an earlier release of the same branch
└── releases/

~/MotionModule/
├── active -> robots/Mecanum/
├── robots/
│   ├── Mecanum/
│   │   ├── robot.py
│   │   ├── hardware.py
│   │   ├── sensors.py
│   │   ├── autonomous.py
│   │   └── dashboard.py
│   └── AnotherRobot/
└── backups/

~/.config/motionmodule/hardware.py       # installed pin and name definitions
~/.config/motionmodule/config.toml       # pre-hardware.py installs only
~/.config/motionmodule/terminal-access.json
```

Installing a tag, branch, or commit builds and tests a new release before the
`current` link changes. It does not overwrite robot projects. Once the new
release is running, the install replaces the old MotionModule software: other
releases and stale MotionModule system files are removed, so `main` and
`testing` can replace each other in either direction. Only an earlier release
of the same branch is kept, for rollback. Rollback switches the runtime links,
not the student folders. See [installer/README.md](../installer/README.md) for
exactly what is removed and what is kept.

The service follows `~/MotionModule/active/robot.py` and auto-loads an optional
sibling `dashboard.py` for the separate full Driver Station's camera, IMU, Pi
input, and USB-controller telemetry. GPIO and servo
configuration is resolved in one order: the active project's data-only
`hardware.py`, then the installed `~/.config/motionmodule/hardware.py`, then the
copy shipped inside the runtime. Installs predating that file keep their TOML
configuration, which is still read for compatibility.

## Browser deployment boundary

The Code page sends a browser-selected directory as multipart files to the
local dashboard. The backend:

1. requires the unguessable per-page dashboard token;
2. accepts a single safe root folder with Python, Arduino sketches, and text documentation only;
3. enforces count, individual-file, and total-size limits;
4. rejects path traversal, links, binary data, caches, and build output;
5. compiles every `.py`, verifies `create_drive(module)`, verifies
   `create_dashboard(module, drive)` when `dashboard.py` exists, and, when the
   folder ships one, parses `hardware.py` with `ast.literal_eval` without
   importing it;
6. stops outputs before writing project state;
7. moves an existing target to `backups`, atomically installs the staged
   folder, and atomically updates `active`; and
8. exits so systemd restarts the dashboard on the new project.

The service uses `Restart=always`, so a deliberate clean exit after deployment
returns through the same launcher. Nginx stays the stable port-80 front door.

## Connectivity

```text
boot
  │
  ├── saved Wi-Fi connects within 30 seconds → hostname.local + DHCP IP
  │
  └── no saved connection → MotionModule hotspot → http://10.42.0.1
```

Ethernet also reaches the same dashboard. A root-owned NetworkManager helper
exposes only fixed status, scan, connect, preferred-network, hotspot, and
hostname operations to the unprivileged service. A manual hotspot is for the
current boot; the next boot tries saved client Wi-Fi again.

## Hardware discovery limits

PCA9685 boards acknowledge on I2C. USB devices expose descriptors in Linux
sysfs, so the dashboard can list identity, topology, driver binding, device
node, and permission status. The Arduino GIGA R1 WiFi is matched by its
official USB VID/PID: 2341:0266 running a sketch, 2341:0366 in its bootloader.
USB discovery alone cannot identify which physical sensor is wired to a pin.

## Arduino GIGA sensor bridge

```text
firmware/giga_sensor_bridge/giga_sensor_bridge.ino   the firmware, generic
firmware/giga_sensor_bridge.bin                      prebuilt, flashed by the Pi
firmware/giga_sensor_bridge.json                     version and checksums
firmware/build.py                                    rebuilds the binary (arduino-cli)
core/motion_module/imu.py                            the sensor drivers, on the Pi
```

The firmware only moves bytes: it reads the pins and I2C registers it is told
to, at the interval it is told, and answers one-off reads, writes and bus
scans. The project's `sensors.py` declares pins and IMUs; `module.giga()`
creates one `GigaR1Bridge` for the process (never opened in simulation), and
its reader thread sends `MM3 CONFIG <id> <ms> <pins> <streams>` after every
connection. The GIGA answers with one JSON line of readings per interval,
tagged with that id, so readings meant for another configuration are never
used. The original `MM1 CONFIG` pins-only protocol is still understood in both
directions, so older MotionModule software and the original sketch keep
working; firmware whose protocol this version cannot use is reported as
needing a flash rather than guessed at.

Nothing about a particular sensor lives on the GIGA. `motion_module.imu`
holds the drivers: each writes its chip's set-up registers through one-off
`MM3 I2C` commands (written as a generator of reads, writes and waits, so the
reader thread never blocks), declares the registers to repeat, and decodes
them. A BNO055 is put in fusion mode and its heading is unwrapped on the Pi;
an LSM6-family 6-axis IMU is fused on the Pi, with the gyro bias measured
while still and re-measured whenever the robot rests, and yaw integrated about
the measured up direction so tilt never reads as turning. Readings carry the
GIGA's own millisecond clock, so integration does not depend on USB timing.
Yaw counts up counter-clockwise, as `rotate` does.

`motionmodule giga flash` and Debug's Install firmware button run
`motion_module.giga_firmware`: the reader releases the port, a 1200-baud touch
restarts the board into its bootloader, `dfu-util` writes the bundled binary at
0x08040000, and the board's version is checked once it restarts. The installer
provides `dfu-util`, the `dialout` and `plugdev` groups, and a udev rule for the
GIGA's USB IDs. `tests/firmware/harness.cpp` runs the real firmware against
simulated I2C chips, and `tests/fake_giga.py` runs the real drivers against a
simulated board, so both sides are tested without hardware.

The reference GPIO H-bridges and PWM servo signal have no return channel.
MotionModule can validate their configured pins and safely pulse an output, but
it cannot electronically prove a driver, motor, or servo is attached.

## Web terminal

The terminal API requires the per-page dashboard token and a second temporary
access code created by `motionmodule terminal enable`. The code is stored with
mode 0600, expires, and is tied to the current Linux boot ID. The backend owns
one unprivileged PTY at a time, caps retained output and input, and closes idle
sessions.

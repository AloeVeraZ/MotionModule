# Runtime and update architecture

## Control path

```text
browser → nginx :80 → versioned dashboard :8080
                           │
                           ├── browser project deployment
active robot folder ───────┤
                           ├── GPIO PWM → four dual H-bridges → eight motors
                           ├── I2C → PCA9685 board(s) → servos
                           ├── sysfs → read-only USB inventory
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
├── previous -> releases/v0.8.1-...
└── releases/

~/MotionModule/
├── active -> robots/Mecanum/
├── robots/
│   ├── Mecanum/
│   │   ├── robot.py
│   │   ├── hardware.py
│   │   └── mecanum.py
│   └── AnotherRobot/
└── backups/

~/.config/motionmodule/config.toml       # older-project fallback
~/.config/motionmodule/terminal-access.json
```

Installing a tag, branch, or commit builds and tests a new release before the
`current` link changes. It does not overwrite robot projects. Rollback switches
the runtime links, not the student folders.

The service follows `~/MotionModule/active/robot.py`. For a current project,
its data-only `hardware.py` is the source of GPIO and servo configuration. An
older installed project without that file continues to use the persistent TOML
fallback.

## Browser deployment boundary

The Code page sends a browser-selected directory as multipart files to the
local dashboard. The backend:

1. requires the unguessable per-page dashboard token;
2. accepts a single safe root folder and Python/text documentation only;
3. enforces count, individual-file, and total-size limits;
4. rejects path traversal, links, binary data, caches, and build output;
5. compiles every `.py`, verifies `create_drive(module)`, and parses
   `hardware.py` with `ast.literal_eval` without importing it;
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
node, and permission status without probing or writing to the device.

The reference GPIO H-bridges and PWM servo signal have no return channel.
MotionModule can validate their configured pins and safely pulse an output, but
it cannot electronically prove a driver, motor, or servo is attached.

## Web terminal

The terminal API requires the per-page dashboard token and a second temporary
access code created by `motionmodule terminal enable`. The code is stored with
mode 0600, expires, and is tied to the current Linux boot ID. The backend owns
one unprivileged PTY at a time, caps retained output and input, and closes idle
sessions.

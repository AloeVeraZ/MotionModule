# Runtime and update architecture

## Control path

```text
browser ---> nginx :80 ---> versioned dashboard :8080
                              |
student Mecanum/robot.py ---- drive hook
        |
        v
motion_module.MotionModule
   |                     |
   v                     v
lgpio 1 kHz PWM          I2C bus 1
16 direction legs        PCA9685 0x40, 0x41, ...
   |                     |
4 dual H-bridges         16 servos per board
   |
8 brushed motors
```

All motor writes go through one lock. A logical sign reversal stops every motor,
waits 15 ms, and applies the new directions together. A separate watchdog thread
stops all output after 500 ms without a control heartbeat. GPIO starts low and
is forced low again during normal shutdown and handled Python exceptions. A
physical main cutoff remains required because software cannot guarantee safety
through OS lockups, regulator faults, broken wiring, or failed power electronics.

## Files that updates can and cannot change

```text
~/.local/share/motionmodule/
├── current -> releases/main-...        # service follows this link
├── previous -> releases/v0.1.0-...
└── releases/                            # immutable installed copies

~/MotionModule/Mecanum/                 # persistent student-owned code
~/.config/motionmodule/config.toml      # persistent hardware calibration
```

Installing a new Git tag/ref builds and tests a new release before switching
`current`. It does not pull in the background and does not overwrite student
code/config. `motionmodule rollback` swaps `current` and `previous` and restarts
the service. Rollback changes the backend runtime, not student files; students
should also use Git in `~/MotionModule` when they need revisions of robot code.
The stable service launcher detects releases from before Dashboard 0.2.0 and
runs their original project-hosted server, so Nginx and explicit rollback stay
compatible across that boundary.

## Connectivity choice

Systemcore's strongest usability idea is that deployment works over USB,
Ethernet, or Wi‑Fi with a stable network identity. For an ordinary Raspberry Pi,
Ethernet/Wi‑Fi SSH provides that same editing surface without a custom desktop
toolchain:

- VS Code Remote‑SSH edits and runs code directly on the Pi;
- mDNS supplies a friendly `motionmodule.local` address;
- Ethernet is available for reliable bench work;
- a root-owned NetworkManager helper exposes only fixed scan/connect/hotspot
  actions to the browser service;
- `motionmodule-network.service` waits 30 seconds for client Wi-Fi, then creates
  a direct robot hotspot when no LAN exists;
- the robot browser UI uses the same address and requires no app installation.

```text
boot
  |
  v
saved Raspberry Pi Imager / preferred Wi-Fi ---- connected ----> .local + DHCP IP
  |
  | no connection for 30 seconds
  v
MotionModule hotspot ----> http://10.42.0.1
```

Nginx is the stable front door on port 80, so a beginner can enter the bare Pi
IP or `.local` name. The dashboard application listens on port 8080 behind that
proxy and owns the live APIs. It is packaged with each versioned release; the
student drive hook is loaded from the persistent project.

The hotspot profile has autoconnect disabled. A manual hotspot therefore stays
active for the current boot, while a reboot always gives saved client Wi-Fi the
first 30-second opportunity. Network changes are queued after an HTTP response
and stop all motor output before the adapter changes roles.

Bluetooth serial and automatic USB gadget mode were intentionally left out.
They add platform-specific pairing/drivers and provide a worse beginner coding
experience than SSH. USB Ethernet gadget support can be added later for a
specific Pi model without changing the Python hardware API.

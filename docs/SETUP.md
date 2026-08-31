# Raspberry Pi installation and commissioning

## 1. Prepare Raspberry Pi OS

Use Raspberry Pi Imager to install a current Raspberry Pi OS release on a
Raspberry Pi 5, the current tested hardware target. The
64-bit Lite image is sufficient; Desktop also works. In Imager customization:

- create a normal username and strong password;
- enable SSH;
- configure a 2.4/5 GHz Wi-Fi network or plan to use Ethernet;
- give every classroom Pi a unique hostname if possible;
- set the correct locale and timezone.

Before motor power is ever attached, add the input pull-downs described in
[PINOUT.md](PINOUT.md). Software cannot control a GPIO during the Pi's early
boot or while it has no power.

Ethernet is the most dependable first-install connection. Normal Wi-Fi is the
most convenient everyday editing connection. Bluetooth is not used because it
does not provide a consistent SSH/deployment path, and USB gadget networking is
not the default because support and cabling differ across Pi models.

## 2. Install MotionModule

SSH into the Pi, then run the installer as that normal user:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --hostname motionmodule-01
```

The script requests sudo only for APT, GPIO/I2C groups, SSH/mDNS, hostname, and
the systemd service. It performs these operations in order:

1. installs `lgpio`, I2C, Python, NetworkManager, Nginx, SSH, and mDNS packages;
2. enables I2C and adds the installing user to the `gpio`/`i2c` groups;
3. copies the requested code into a new timestamped release directory;
4. creates an isolated Python environment and runs the complete unit test suite;
5. copies each repository example into `~/MotionModule/robots` only when that project does not already exist;
6. points `~/MotionModule/active` at the selected project and creates the persistent config;
7. switches the `current` symlink only after validation succeeds;
8. records the active Raspberry Pi Imager Wi-Fi as the preferred network;
9. enables the dashboard/runtime, port-80 proxy, and 30-second Wi-Fi failover service;
10. runs the non-moving `motionmodule doctor` check and prints its results;
11. links to the GitHub pinout as its final message, then reboots automatically.

The SSH connection closes when the automatic reboot begins. Wait for the Pi to
come back online before reconnecting. For a provisioning workflow that still
has additional work to do, skip only the reboot with:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --no-reboot
```

## 3. Non-moving checks

The installer already ran `doctor` before reboot. After wiring against
[PINOUT.md](PINOUT.md), reconnect and run the checks again before applying motor
power:

```bash
motionmodule status
motionmodule doctor
motionmodule pinout
```

`doctor` can confirm the config, GPIO access, SPI conflicts, service, and every
configured PCA9685 I2C address. The H-bridge boards have no return data line, so
their presence cannot be detected without moving a motor or adding current/
encoder feedback hardware.

If the PCA9685 is absent—as expected during early development—`doctor` reports a
warning and motor service remains usable. Install the board later and rerun the
same check.

## 4. Raised-wheel motor commissioning

Read [PINOUT.md](PINOUT.md), raise the chassis, and keep the cutoff nearby.
Normal robot code must be stopped so two processes cannot claim GPIO:

```bash
motionmodule stop
motionmodule test-motor 1
motionmodule test-motor 2
```

The diagnostic requires typing `RAISED`, limits power to 25% and duration to two
seconds, and stops through a `finally`/context cleanup path. Test all eight
channels. Missing motor/driver wiring produces no software discovery error; the
physical channel simply will not move.

For a wheel that runs opposite its semantic direction, edit only its
`inverted = true/false` value:

```bash
nano ~/.config/motionmodule/config.toml
motionmodule start
```

## 5. Servo commissioning

Set the external servo regulator with a multimeter before attaching a servo.
Start with mechanical linkage disconnected and a centered generic command:

```bash
motionmodule stop
motionmodule test-servo 0 --board 0 --angle 90
```

If the board is not found, run `i2cdetect -y 1`. The default board should appear
at `40`. Check SDA/SCL orientation, 3.3 V logic VCC, common ground, and address
pads. A servo may still fail to move with a detected board if its separate V+
rail is absent.

The dashboard **Debug → Servo pulse test** provides board selection and all 16
PCA9685 outputs, numbered `0` through `15`. Choose the servo behavior before
sending a pulse:

| Dashboard profile | Command range | PWM range |
| --- | ---: | ---: |
| goBILDA 25-2 positional | 0–300° | 500–2500 µs |
| goBILDA 25-2 5-turn positional | 0–1800° | 500–2500 µs |
| goBILDA 25-2 continuous | −100% to +100%; 0% stops | 900–2100 µs |
| Generic positional | 0–180° or 0–360° | Configured servo pulse range |

The profiles follow goBILDA's published specifications for the
[300° Dual Mode Servo](https://www.gobilda.com/2000-series-dual-mode-servo-25-2-torque/)
and [5-Turn Dual Mode Servo](https://www.gobilda.com/2000-series-5-turn-dual-mode-servo-25-2-torque/).
Continuous behavior works only after the servo itself has been changed into
continuous mode with the supported programmer. The **Zero servo** button sends
0° for a positional profile or the neutral 0% command for continuous mode. For
a positional servo, 0° can be a mechanical endpoint—disconnect the linkage and
confirm the full travel path first. Every dashboard command automatically
releases the PCA9685 output after 1.5 seconds.

The profile changes only PWM behavior; it does not set supply voltage or
reprogram the servo. Both linked goBILDA models specify 4.8–7.4 V, so set and
verify the separate regulated V+ rail for the actual servo before connecting
it. Do not choose the generic 360° positional profile for a continuous-rotation
servo—continuous PWM represents direction and speed, not an absolute angle.

## 6. Student editing

Install VS Code and the Microsoft Remote - SSH extension on the laptop. Connect
to `YOUR_USER@motionmodule-01.local`, open
`~/MotionModule/robots/Mecanum`, and edit that robot folder. The included
default is `Mecanum`. Restart and watch logs
from the VS Code terminal:

```bash
motionmodule restart
motionmodule logs
```

### Browser terminal

At the bottom of the dashboard Code page is a PTY-backed Bash terminal. It runs
as the normal Pi user in the active robot project, so it can run scripts and
normal shell commands but cannot silently bypass Linux permissions.

It is deliberately locked until enabled from SSH:

```bash
motionmodule terminal enable       # 15 minutes
motionmodule terminal enable 30    # choose 1–120 minutes
motionmodule terminal status
motionmodule terminal disable
```

Enter the printed access code in the Code page. The file containing that code
is readable only by the Pi user, expires at the selected time, and includes the
Linux boot ID so it cannot be reused after reboot. An active shell closes when
the page is left, when access is disabled or expires, or after five minutes
without browser activity. `Interrupt · Ctrl-C` stops a running command.

The robot dashboard is HTTP, not end-to-end HTTPS. Use this terminal only on a
trusted/private robot network, never expose port 80 to the public internet, and
do not enter reusable passwords, access tokens, or other secrets. Use SSH for
`sudo` and other privileged administration. Running `motionmodule restart`
inside the page intentionally disconnects the terminal while the service
restarts.

To add another robot, create `~/MotionModule/robots/Swerve/robot.py` (or another
project-named folder), then select it:

```bash
motionmodule project list
motionmodule project Swerve
```

The dashboard's Code page shows the active project. Reinstalling or updating
the runtime does not overwrite any existing robot project folder.

The complete dashboard is `http://motionmodule-01.local`; the Pi's current IP
address also works directly without adding a port. A network
disconnect stops motor output after 500 ms even if the browser stop request
never reaches the Pi. Open **Debug** for the pin diagram, live PCA9685
detection, guarded motor/servo tests, Doctor warnings, service logs, active
network, IP addresses, Wi-Fi scan, and hotspot controls. Every network change
stops the motors. **Code** contains editing help and guarded manual drive.

## 7. Wi-Fi and automatic standalone hotspot

On every boot, NetworkManager first tries the Wi-Fi profiles already saved on
the Pi. The installer records whichever client Wi-Fi is active—normally the one
entered in Raspberry Pi Imager—as MotionModule's preferred profile. If the Pi
does not have a working client connection within 30 seconds, it creates:

- SSID: `MotionModule`
- password: `motionrobot` on a fresh install
- robot address: `http://10.42.0.1`

Change the hotspot name/password from the browser Settings screen before using
it in a shared classroom. Settings can also scan and join open, WPA personal,
or PEAP/MSCHAPv2 enterprise networks. Enterprise setup requires the username,
password, and authentication server's full DNS domain so the Pi can validate
the server certificate. Use `nmtui` through SSH for other school configurations.

Press **Switch to robot hotspot** to leave the current LAN and start the access
point immediately. That manual choice applies to the current boot only. At the
next boot, the Pi again tries preferred Wi-Fi for 30 seconds first. The matching
terminal commands remain available:

```bash
motionmodule hotspot on MotionModule-01 choose-a-password
motionmodule hotspot off
motionmodule hotspot status
```

`hotspot off` reconnects the saved preferred profile. Ethernet can remain
connected while the Wi-Fi adapter serves the hotspot.

### Finding the address after changing Wi-Fi

The Debug page shows every current IPv4 address and the stable mDNS name
`http://HOSTNAME.local`. When the Pi switches away from its hotspot, the
old browser loses contact before it can learn the new DHCP address; that is a
normal one-radio handoff. Join the destination Wi-Fi on the laptop and open the
`.local` name. If `.local` is unavailable on that laptop/network, find the Pi in
the router's client list or SSH in and run `hostname -I`.

## Troubleshooting

### Service repeatedly restarts

```bash
motionmodule status
sudo journalctl -u motionmodule.service -n 100 --no-pager
```

A syntax error in student `robot.py`, a GPIO already claimed by another process,
or active SPI on expansion pins are common causes.

### The Pi is online but the dashboard does not open

Use `http://` rather than `https://`, then check both services:

```bash
sudo systemctl status nginx motionmodule.service --no-pager
curl http://127.0.0.1:8080/healthz
sudo nginx -t
```

Port 8080 is the private dashboard process; Nginx exposes it as normal port 80.

### `.local` address does not resolve

Use the IP shown by `hostname -I`, your router, or `10.42.0.1` in hotspot mode.
Confirm `systemctl status avahi-daemon` on the Pi.

### The hotspot never appears

Wait at least 30 seconds after boot, then check Ethernet and the saved Wi-Fi—any
working client connection intentionally prevents fallback. Inspect the monitor
with `sudo systemctl status motionmodule-network.service` and
`sudo journalctl -u motionmodule-network.service -n 100 --no-pager`.

### Permission denied for GPIO/I2C

Reboot after installation. Confirm `groups` includes `gpio` and `i2c`, and that
`/dev/gpiochip0` and `/dev/i2c-1` exist.

### The robot moves briefly and stops

The 500 ms watchdog is working. Long-running code must refresh motor commands or
call `module.feed_watchdog()` faster than the configured timeout. Do not disable
the watchdog to hide a blocked control loop.

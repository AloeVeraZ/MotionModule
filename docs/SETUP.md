# Raspberry Pi setup and commissioning

## 1. Image the Pi

Use current Raspberry Pi OS in Raspberry Pi Imager. In its customization page:

- create a normal username and a strong password;
- enter the Wi-Fi the robot should normally use;
- set the correct Wi-Fi country; and
- enable SSH for installation and future administration.

The Wi-Fi saved here is the first preferred network. MotionModule can add or
replace preferred networks later from Debug.

## 2. Install MotionModule

Boot the Pi and connect to it once. Then run as the normal user, without putting
`sudo` before the command:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | bash
```

For multiple robots, give each a distinct hostname:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --hostname motionmodule-01
```

The installer creates versioned software, the persistent robot workspace,
system services, Nginx, I2C/GPIO access, mDNS, and Wi-Fi failover. It runs
MotionModule Doctor automatically, prints the pinout link last, and reboots.

## 3. Open the dashboard

After reboot, put the laptop on the same Wi-Fi and open:

```text
http://motionmodule.local
```

Use the Pi IP if `.local` discovery is blocked. If no saved Wi-Fi connects
within 30 seconds, join `MotionModule` with initial password `motionrobot` and
open `http://10.42.0.1`.

Debug shows all current IP addresses and lets you rename the hostname, scan and
join Wi-Fi, or start the robot hotspot for this boot. After a network switch,
join the same destination network on the laptop and reopen the hostname. The
next reboot always tries saved client Wi-Fi first.

## 4. Wire and inspect hardware

Read [PINOUT.md](PINOUT.md) and [the bill of materials](../BOM.md) before
applying motor or servo power.

- Motor battery positive goes only to the fused motor rail and H-bridges.
- PCA9685 VCC is Pi-side logic power; servo V+ comes from a separate fused
  5–6 V supply.
- Connect all signal grounds.
- Keep motor power off through boot and confirm the outputs stay still.
- Keep a physical motor-power cutoff reachable.

Open Debug. Its header and H-bridge labels are generic Driver 1A through 4B,
independent of the selected robot style. PCA9685 boards are checked through
I2C. USB devices appear with their IDs, Pi ports, drivers, and access state.
Basic H-bridge and servo outputs cannot identify attached hardware.

With all wheels raised, use the guarded Motor Bench Test at low power. Test
servos one channel at a time after selecting the correct voltage and behavior.

## 5. Create and deploy robot code

Open **Code → Deploy** and download the Mecanum sample. Unzip it and
rename the folder for the robot. Every browser-deployed folder contains:

```text
MyRobot/
├── robot.py
├── hardware.py
└── any_other_python_files.py
```

Edit the local folder in any editor. `hardware.py` owns this robot's pins,
inversion, PWM, watchdog, and servo board list. `robot.py` defines
`create_drive(module)`. See [CODING.md](CODING.md) for the APIs and examples.

Return to Code, choose the whole folder, review its files, accept the output
stop/restart confirmation, and press **Deploy and run**. The Pi validates it,
backs up an older same-named folder, makes the new copy active, restarts, and
automatically reconnects the page. A failed check does not replace the working
project.

## 6. Test the active project

Start with the speed limit low and the robot raised. Enable keyboard drive
deliberately:

- W/S: forward/backward
- A/D: strafe
- Q/E: rotate
- Space: stop

Releasing a key, disabling drive, leaving the page, or losing communication
sends or causes a stop. The 500 ms default hardware watchdog protects against a
lost browser command, but it does not replace the physical cutoff.

## 7. Use Doctor, logs, and terminal

Useful commands are explained inside Debug:

```bash
motionmodule doctor
motionmodule pinout
motionmodule status
motionmodule logs
motionmodule restart
motionmodule project list
```

The web terminal is an unprivileged real Bash shell and is locked by default.
Create a temporary access code during an admin SSH session:

```bash
motionmodule terminal enable
```

Enter that code at the bottom of Code. It expires after 15 minutes by default,
is invalid after reboot, and its shell closes after five idle minutes. Revoke it
with `motionmodule terminal disable`. Do not enter reusable secrets because the
local robot dashboard uses HTTP.

## 8. Update MotionModule

A Pi with internet access checks GitHub by itself. Open **Debug -> Checks &
logs**; *MotionModule updates* is the first card.

1. The main line is green when this robot already runs its newest version and
   red when an update is waiting. The card shows the commit the Pi has against
   the one on GitHub.
2. **Update now** asks once, then stops the motors and installs in the
   background. The output appears under the card. MotionModule restarts, so
   the dashboard reconnects on its own after a minute or two; keep the robot
   powered until it does.

Robot folders, `hardware.py`, and the active project are kept, the tests run
before the new version is switched on, and a version that will not start is
rolled back. Checks repeat every 15 minutes; **Check now** asks straight away.
Nothing is ever installed without pressing the button.

## Troubleshooting

### The update card says the helper is missing

Updating from the dashboard needs `/usr/local/sbin/motionmodule-update`, which
only installs from this version onwards. Update once over SSH:

```bash
motionmodule install main
```

The button works from then on.

### The update card cannot reach GitHub

The Pi is on Wi-Fi with no route to the internet, which is normal on its own
hotspot. Join a network with internet access, or update over SSH. The card
never guesses; it says so instead.

### The Pi is online but the website does not open

Use `http://`, not `https://`, and try the numeric IP. On the Pi:

```bash
sudo systemctl status nginx motionmodule.service --no-pager
curl http://127.0.0.1:8080/healthz
sudo nginx -t
```

### A deployment is rejected

The selected folder must contain a top-level `robot.py` and may contain only
`.py`, `.ino`, `.md`, and `.txt` files. A `hardware.py` is optional, but when present it
must hold literal data only. Read the exact Driver Station message: syntax and
hardware-map failures are rejected before anything is replaced.

### The service repeatedly restarts after a deployment

The static checks cannot prove that every imported third-party package exists
or that import-time student code succeeds. Open Debug's service log or run:

```bash
sudo journalctl -u motionmodule.service -n 100 --no-pager
```

Correct the local folder and deploy it again. Previous copies are retained in
`~/MotionModule/backups`.

### The hotspot never appears

Wait at least 30 seconds. Any working saved Wi-Fi intentionally prevents the
fallback. Inspect `motionmodule-network.service` if necessary.

### GPIO or I2C says permission denied

Reboot after installation. Confirm the user belongs to `gpio` and `i2c` and
that `/dev/gpiochip0` and `/dev/i2c-1` exist.

### A motor moves briefly and stops

The watchdog is working. Robot logic that maintains nonzero output must refresh
commands faster than the configured timeout.

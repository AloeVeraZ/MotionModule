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

With all wheels raised, use the guarded Motor Bench Test at half power. Test
servos one channel at a time after selecting the correct voltage and behavior.

## 5. Connect the Pi IMU

The reference Mecanum setup keeps its motors, servo controller and MPU6500
on the Pi. The IMU uses the independent bus shown in **Debug → Wiring**:
VCC to physical pin 17, GND to 6 and AD0 to 20, SDA to 11 and SCL to 12.
Follow the [complete MPU6500 guide](PINOUT.md#optional-mpu6500-six-axis-imu),
including the board's I2C mode and pull-up notes.

The Pi installer adds this under `[all]` in `/boot/firmware/config.txt` and
reboots. If setting up without the installer, add it yourself and reboot:

```ini
dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18
```

Use `i2cdetect -l` to confirm the independent adapter exists, then run
**Debug → Checks & logs**. The sample's `sensors.py` reads the MPU6500 on that
bus automatically. It does not use the servo bus or an Arduino for heading.
Without the IMU the robot still drives, with heading unavailable.

### Optional USB GPIO expansion

For additional sensors, an Arduino **GIGA R1 WiFi** may be connected to the
Pi by a USB-C data cable as extra GPIO inputs. This is an experimental extra
and may need troubleshooting on your hardware. The reference sample declares
no additional sensors. Uno and Mega boards cannot use the bundled GIGA firmware.

The existing USB discovery code recognizes the GIGA. Install its bridge
firmware from **Debug → Checks & logs → Install firmware**, or run:

```bash
motionmodule giga flash
motionmodule giga status
```

Flashing replaces the board's sketch, stops motors and restarts the GIGA.
The Pi uses the bundled firmware and `dfu-util`; no Arduino IDE is needed.
After flashing, declare only the extra inputs you actually wire, using
[the Python GPIO API](CODING.md#optional-usb-gpio-expansion). Board detection
does not identify attached sensors. The Pi sends your declarations on each
connection; a pin-list change does not require reflashing. GIGA GPIO takes
3.3 V maximum. The robot's MPU6500 stays connected directly to the Pi.

## 6. Create and deploy robot code

Open **Code → Deploy** and download the Mecanum sample. Unzip it and
rename the folder for the robot. The sample folder contains:

```text
MyRobot/
├── robot.py
├── hardware.py
├── sensors.py
├── autonomous.py
├── dashboard.py
└── any_other_python_files.py
```

Edit the local folder in any editor. `hardware.py` owns this robot's pins,
inversion, PWM, watchdog, and servo board list. `robot.py` defines
`create_drive(module)` and imports `sensors.py`, which reads the Pi-connected
MPU6500. See [CODING.md](CODING.md) for the APIs and examples.

Return to Code, choose the whole folder, review its files, accept the output
stop/restart confirmation, and press **Deploy and run**. The Pi validates it,
backs up an older same-named folder, makes the new copy active, restarts, and
automatically reconnects the page. A failed check does not replace the working
project.

## 7. Test the active project

Start with the speed limit low and the robot raised. Enable keyboard drive
deliberately:

- W/S: forward/backward
- A/D: strafe
- Q/E: rotate
- Space: stop

Releasing a key, disabling drive, leaving the page, or losing communication
sends or causes a stop. The 500 ms default hardware watchdog protects against a
lost browser command, but it does not replace the physical cutoff.

## 8. Use Doctor, logs, and terminal

Useful commands are explained inside Debug:

```bash
motionmodule doctor
motionmodule pinout
motionmodule status
motionmodule logs
motionmodule restart
motionmodule project list
motionmodule giga status
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

## 9. Update MotionModule

A Pi with internet access checks GitHub by itself. Open **Debug -> Checks &
logs**; *MotionModule updates* is the first card.

1. Each branch gets a line. Green means this robot already runs the newest
   version of it, red means an update is waiting, and the card says which
   commit the Pi has against the one on GitHub.
2. A Pi installed from `testing` sees both lines: its own, and `main` with
   **Switch to the main line** for going back to stable. A Pi installed from
   `main` sees only `main`.
3. **Update now** asks once, then stops the motors and installs in the
   background. The output appears under the card. After a successful install,
   the whole Pi reboots automatically and the dashboard reconnects on its own
   after a minute or two; keep the robot powered until it does.
4. If `sudo` on the Pi asks for your password, a **Password required for
   update** popup asks for it first. It is the password of the Pi user you
   installed MotionModule as. A wrong one is refused before anything starts;
   the right one is used for this update only and deleted when it ends. A Pi
   whose `sudo` needs no password never shows the popup.

Robot folders, `hardware.py`, the active project, and Wi-Fi settings are kept,
the tests run before the new version is switched on, and a version that will
not start is rolled back. Checks repeat every 15 minutes; **Check now** asks
straight away. Nothing is ever installed without pressing the button.

## Troubleshooting

### The update card says the helper is missing

Updating from the dashboard needs `/usr/local/sbin/motionmodule-update`, which
only installs from this version onwards. Update once over SSH:

```bash
motionmodule install testing
```

The button works from then on.

### The update says its helper is too old to pass on a password

`sudo` on this Pi asks for a password, and the Pi was set up before the update
button could ask for one. Update once over SSH, where `sudo` asks in the
terminal:

```bash
motionmodule install testing
```

From then on the dashboard shows the password popup instead. Use SSH rather
than the Code-page terminal for this: that terminal belongs to the MotionModule
service, which restarts partway through the install.

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

### The Pi resets or the whole robot loses power at high motor output

Do not repeatedly reproduce a full-power shutdown. A software watchdog cannot
keep a Pi alive after its supply disappears. The motor commands are PWM duty
cycles, not measured amperes: 100% requests continuous drive, and neither the
H-bridges nor this code report battery voltage or motor current.

**Debug → Checks & logs → Run checks** and `motionmodule doctor` now read
`vcgencmd get_throttled` without moving anything. The Pi can report current
undervoltage and undervoltage recorded during this boot. These firmware flags
are not a battery gauge. They reset on reboot, and a fast supply cutoff can
leave no warning, so a clean reading does not establish that the power system
is adequate. Missing or unsupported diagnostics are reported as unavailable,
not as a good supply. See the [official flag definitions](https://www.raspberrypi.com/documentation/computers/os.html#get_throttled).

Inspect the actual battery, fuse markings, switch/connectors, driver ratings,
and the Pi's 12 V-to-5 V converter with actuator power disconnected. A driver
board's amp rating is not necessarily the main fuse rating. Do not bypass or
increase a fuse to hide the symptom. A conventional blown blade fuse stays
open; automatic recovery suggests another mechanism, such as converter
protection or a voltage dip, rather than proving the fuse blew.

Acceleration ramps can reduce startup transients but change acceleration and
do not protect against sustained overload. Power caps reduce available output.
Neither has been enabled automatically. Keeping full requested motor output
while guaranteeing Pi power requires an adequately sized, protected supply
system; software alone cannot create that current capacity. Hardware changes
must be reviewed by the owner and must not alter the locked pinout.

### The hotspot never appears

Wait at least 30 seconds. Any working saved Wi-Fi intentionally prevents the
fallback. Inspect `motionmodule-network.service` if necessary.

### GPIO or I2C says permission denied

Reboot after installation. Confirm the user belongs to `gpio` and `i2c` and
that `/dev/gpiochip0` and `/dev/i2c-1` exist.

### Optional GIGA expansion is not found, or readings stay empty

- `motionmodule giga status` should list it. If not, try another cable: many
  USB-C cables only carry power.
- *Permission denied* opening `/dev/ttyACM0`: the installer adds the user to
  `dialout` and `plugdev`. Reboot once after installing.
- The Driver Station says it runs the original bridge sketch, or a different
  firmware version: install the firmware again from Debug.
- A flash that says the GIGA did not enter its bootloader: press the GIGA's
  RESET button twice quickly, so its green light pulses, and install again.

### A motor moves briefly and stops

The watchdog is working. Robot logic that maintains nonzero output must refresh
commands faster than the configured timeout.

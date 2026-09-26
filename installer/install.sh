#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR=""
VERSION_REF="${MOTIONMODULE_VERSION:-main}"
TARGET_HOSTNAME="__default__"
START_SERVICE=true
REBOOT_SYSTEM=true
ROBOT_PROJECT="${MOTIONMODULE_ROBOT_PROJECT:-Mecanum}"
ROBOT_EXPLICIT=false

if [ -n "${MOTIONMODULE_ROBOT_PROJECT:-}" ]; then
    ROBOT_EXPLICIT=true
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --source)
            SOURCE_DIR="$2"
            shift 2
            ;;
        --version)
            VERSION_REF="$2"
            shift 2
            ;;
        --hostname)
            TARGET_HOSTNAME="$2"
            shift 2
            ;;
        --robot)
            ROBOT_PROJECT="$2"
            ROBOT_EXPLICIT=true
            shift 2
            ;;
        --no-hostname)
            TARGET_HOSTNAME=""
            shift
            ;;
        --no-start)
            START_SERVICE=false
            shift
            ;;
        --no-reboot)
            REBOOT_SYSTEM=false
            shift
            ;;
        *)
            printf '[MotionModule ERROR] Unknown installer option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

# Dashboard helpers shipped before automatic update reboots passed
# --no-reboot. The downloaded installer is already running inside the
# dashboard's dedicated transient service, so recognize that trusted path and
# restore the reboot for this first update as well as all later ones. An
# explicit --no-reboot still works for every normal terminal/provisioning run.
if [ "$REBOOT_SYSTEM" = false ] \
    && grep -Eq ':/system\.slice/motionmodule-update\.service$' /proc/self/cgroup 2>/dev/null; then
    REBOOT_SYSTEM=true
fi

say() { printf '\n\033[1;36m[MotionModule]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[MotionModule ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
trap 'fail "Installation stopped on line $LINENO. Read the error above and rerun the same command."' ERR

[ "$(id -u)" -ne 0 ] || fail "Run this as the normal Pi user, without sudo."
[ -n "$SOURCE_DIR" ] || fail "The installer source directory was not provided. Run the repository install.sh."
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
[ -f "$SOURCE_DIR/pyproject.toml" ] || fail "pyproject.toml is missing from $SOURCE_DIR"
[ -f "$SOURCE_DIR/core/motion_module/hardware.py" ] || fail "The default hardware definition file is missing."
[ -f "$SOURCE_DIR/installer/runtime_cleanup.sh" ] || fail "installer/runtime_cleanup.sh is missing from $SOURCE_DIR"
# shellcheck source=runtime_cleanup.sh
. "$SOURCE_DIR/installer/runtime_cleanup.sh"
if ! printf '%s' "$ROBOT_PROJECT" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'; then
    fail "Invalid robot project name: $ROBOT_PROJECT"
fi
[ -f "$SOURCE_DIR/examples/$ROBOT_PROJECT/robot.py" ] || fail "Robot example $ROBOT_PROJECT is missing robot.py."
[ -f "$SOURCE_DIR/examples/$ROBOT_PROJECT/hardware.py" ] || fail "Robot example $ROBOT_PROJECT is missing hardware.py."
command -v sudo >/dev/null || fail "sudo is required for Raspberry Pi setup."

INSTALL_ROOT="${MOTIONMODULE_INSTALL_ROOT:-$HOME/.local/share/motionmodule}"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
PREVIOUS_LINK="$INSTALL_ROOT/previous"
PROJECT_DIR="${MOTIONMODULE_PROJECT_DIR:-$HOME/MotionModule}"
ROBOT_DIR="${MOTIONMODULE_ROBOT_DIR:-$PROJECT_DIR/robots}"
CONFIG_DIR="${MOTIONMODULE_CONFIG_DIR:-$HOME/.config/motionmodule}"
CONFIG_FILE="$CONFIG_DIR/hardware.py"
LEGACY_CONFIG_FILE="$CONFIG_DIR/config.toml"

if [ "$TARGET_HOSTNAME" = "__default__" ]; then
    if [ -L "$CURRENT_LINK" ]; then
        TARGET_HOSTNAME=""
    else
        TARGET_HOSTNAME="motionmodule"
    fi
fi

safe_ref="$(printf '%s' "$VERSION_REF" | tr -c 'A-Za-z0-9._-' '-')"
release_id="${safe_ref}-$(date +%Y%m%d-%H%M%S)"
release_dir="$RELEASES_DIR/$release_id"

apt_get() {
    local attempt=1
    local output
    output="$(mktemp)"
    while true; do
        if sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 "$@" 2>&1 | tee "$output"; then
            rm -f "$output"
            return 0
        fi
        if ! grep -Eq 'Could not get lock|Unable to (acquire|lock)|is another process using it' "$output"; then
            rm -f "$output"
            return 1
        fi
        [ "$attempt" -lt 20 ] || fail "APT stayed busy. Wait for system updates, then rerun the installer."
        say "Another update owns APT; retrying in 15 seconds ($attempt/20)..."
        sleep 15
        attempt=$((attempt + 1))
        : > "$output"
    done
}

say "Installing Raspberry Pi, GPIO, I2C, SSH, web, and Python dependencies..."
apt_get update
apt_get install -y \
    avahi-daemon \
    ca-certificates \
    curl \
    dfu-util \
    git \
    i2c-tools \
    iproute2 \
    network-manager \
    nginx \
    openssh-server \
    python3 \
    python3-lgpio \
    python3-pip \
    python3-setuptools \
    python3-smbus \
    python3-venv \
    python3-wheel

if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_i2c 0
fi

# The IMU uses a separate software I2C bus; the hardware bus above belongs
# to the PCA9685. Enable the reference pins once, even when no IMU is fitted.
imu_overlay='dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18'
boot_config=/boot/firmware/config.txt
if [ ! -f "$boot_config" ]; then
    boot_config=/boot/config.txt
fi
[ -f "$boot_config" ] || fail "Raspberry Pi boot config was not found; cannot enable the IMU bus."
if ! sudo grep -Fqx "$imu_overlay" "$boot_config"; then
    printf '\n[all]\n%s\n' "$imu_overlay" | sudo tee -a "$boot_config" >/dev/null
    say "Enabled the independent IMU I2C bus on GPIO17/18 for the next reboot."
fi

# The Pi 5 active cooler plugs into the board's own FAN connector, not the GPIO
# header. Firmware/kernel fan control runs at 75% from 47 C and 100% from
# 50 C, stopping below 45 C. Cooling never depends on MotionModule running.
# cooling.py writes one marked [pi5] block, keeps a backup, and leaves fan
# settings someone wrote themselves in charge.
if tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -q 'Raspberry Pi 5'; then
    if cooling_message="$(sudo python3 "$SOURCE_DIR/core/motion_module/cooling.py" configure "$boot_config" 2>&1)"; then
        say "$cooling_message"
    else
        say "Could not set up Pi 5 fan cooling; the rest of the install continues: $cooling_message"
    fi
fi

# dialout opens the Arduino GIGA's USB serial port; plugdev lets the udev rule
# below give the same user its bootloader for firmware installs.
for group in gpio i2c dialout plugdev; do
    if getent group "$group" >/dev/null; then
        sudo usermod -aG "$group" "$USER"
    fi
done

sudo systemctl enable --now ssh avahi-daemon

say "Building isolated release $release_id..."
mkdir -p "$RELEASES_DIR"
mkdir "$release_dir"
release_commit="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
cp -a "$SOURCE_DIR/." "$release_dir/"
rm -rf -- "$release_dir/.git" "$release_dir/.venv" "$release_dir/__pycache__"
printf '%s\n' "$VERSION_REF" > "$release_dir/INSTALL_REF"
# The commit this release was built from, so the dashboard's update check can
# compare it with the branch on GitHub.
printf '%s\n' "$release_commit" > "$release_dir/INSTALL_COMMIT"

python3 -m venv --system-site-packages "$release_dir/.venv"
# No pip download cache: every release builds its own environment, and a cache
# would only pile up on the SD card between installs.
"$release_dir/.venv/bin/python" -m pip install --no-cache-dir --upgrade pip setuptools wheel
"$release_dir/.venv/bin/python" -m pip install --no-cache-dir --no-build-isolation -e "$release_dir"
(
    cd "$release_dir"
    ./.venv/bin/python -m unittest discover -s tests -v
)
touch "$release_dir/.complete"

say "Creating the persistent student workspace and robot projects..."
mkdir -p "$PROJECT_DIR" "$ROBOT_DIR" "$CONFIG_DIR"

# Version 0.3 stored projects directly in ~/MotionModule. Move those folders
# into the dedicated robots workspace while preserving the active project name.
previous_active_name=""
if [ -L "$PROJECT_DIR/active" ]; then
    previous_active_target="$(readlink -f "$PROJECT_DIR/active" 2>/dev/null || true)"
    [ -n "$previous_active_target" ] && previous_active_name="$(basename "$previous_active_target")"
fi
for old_robot_file in "$PROJECT_DIR"/*/robot.py; do
    [ -f "$old_robot_file" ] || continue
    old_robot_template="$(dirname "$old_robot_file")"
    old_robot_name="$(basename "$old_robot_template")"
    [ "$old_robot_name" = "active" ] && continue
    if [ ! -e "$ROBOT_DIR/$old_robot_name" ]; then
        mv "$old_robot_template" "$ROBOT_DIR/$old_robot_name"
        say "Moved existing robot project to $ROBOT_DIR/$old_robot_name."
    else
        say "Keeping $ROBOT_DIR/$old_robot_name; the older $old_robot_template folder was left unchanged."
    fi
done

for robot_file in "$release_dir"/examples/*/robot.py; do
    [ -f "$robot_file" ] || continue
    robot_template="$(dirname "$robot_file")"
    robot_name="$(basename "$robot_template")"
    if [ ! -e "$ROBOT_DIR/$robot_name" ]; then
        cp -a "$robot_template" "$ROBOT_DIR/$robot_name"
        say "Created robot project $ROBOT_DIR/$robot_name. Future installs keep the work you do in it."
    fi
done

# A robot folder nobody has edited still holds the sample an earlier release
# put there, so fixes to a sample never reached the robot. Give those folders
# the sample this release ships, keeping the copy replaced under backups. A
# folder with its own work keeps every existing file; a missing Mecanum
# autonomous.py is added so both default modes are available. The module
# core/motion_module/shipped_samples.py explains how it tells them apart.
released_with=()
if [ -L "$CURRENT_LINK" ] && [ -d "$CURRENT_LINK/examples" ]; then
    released_with=(--released-with "$(readlink -f "$CURRENT_LINK")/examples")
fi
while IFS= read -r message; do
    say "$message"
done < <("$release_dir/.venv/bin/python" -m motion_module.shipped_samples \
    "$ROBOT_DIR" "$PROJECT_DIR/backups" "${released_with[@]}")

[ -f "$ROBOT_DIR/$ROBOT_PROJECT/robot.py" ] || fail "Selected robot project was not created: $ROBOT_PROJECT"

ACTIVE_LINK="$PROJECT_DIR/active"
if [ -e "$ACTIVE_LINK" ] && [ ! -L "$ACTIVE_LINK" ]; then
    fail "$ACTIVE_LINK must be a managed symlink; rename that file or directory and rerun the installer."
fi
active_is_valid=false
if [ -L "$ACTIVE_LINK" ]; then
    candidate_target="$(readlink -f "$ACTIVE_LINK" 2>/dev/null || true)"
    case "$candidate_target" in
        "$(readlink -f "$ROBOT_DIR")"/*)
            [ -f "$candidate_target/robot.py" ] && active_is_valid=true
            ;;
    esac
fi
if [ "$ROBOT_EXPLICIT" != true ] && [ "$active_is_valid" != true ] && [ -n "$previous_active_name" ] && [ -f "$ROBOT_DIR/$previous_active_name/robot.py" ]; then
    ROBOT_PROJECT="$previous_active_name"
fi
if [ "$ROBOT_EXPLICIT" = true ] || [ "$active_is_valid" != true ]; then
    ln -s "$ROBOT_DIR/$ROBOT_PROJECT" "$PROJECT_DIR/active.new.$$"
    mv -Tf "$PROJECT_DIR/active.new.$$" "$ACTIVE_LINK"
fi
active_target="$(readlink -f "$ACTIVE_LINK")"
case "$active_target" in
    "$(readlink -f "$ROBOT_DIR")"/*) ;;
    *) fail "The active robot project points outside $ROBOT_DIR" ;;
esac
ACTIVE_PROJECT="$(basename "$active_target")"
# hardware.py is the one editable pin-definition file. Preserve older custom
# pin maps when upgrading, and keep config.toml for older release rollbacks.
if [ -f "$CONFIG_FILE" ]; then
    say "Keeping the existing hardware definitions at $CONFIG_FILE."
elif [ -f "$LEGACY_CONFIG_FILE" ]; then
    "$release_dir/.venv/bin/python" - "$LEGACY_CONFIG_FILE" "$CONFIG_FILE" <<'PY'
import sys
from pathlib import Path
from motion_module.config import hardware_source, load_config

config = load_config(sys.argv[1])
with Path(sys.argv[2]).open("x", encoding="utf-8") as output:
    output.write(hardware_source(config))
PY
    say "Converted the existing pin map to $CONFIG_FILE; kept $LEGACY_CONFIG_FILE for rollback."
else
    install -m 0644 "$release_dir/core/motion_module/hardware.py" "$CONFIG_FILE"
    say "Installed the default pin and name definitions at $CONFIG_FILE."
fi

# A pin map an earlier release left on the wiring the robot had before it was
# rewired drives the wrong pins. Move it onto the locked wiring (AGENTS.md) and
# keep the old file beside it; a pin map with any other pins stays as it is.
while IFS= read -r message; do
    say "$message"
done < <("$release_dir/.venv/bin/python" -m motion_module.retired_wiring "$ROBOT_DIR" "$CONFIG_FILE")

# Legacy Mecanum code can still use the installed map because its folder has
# no hardware.py. Preserve that code and copy its settings with only 1B/2B
# inverted; otherwise sample changes never reach either motor-control path.
"$release_dir/.venv/bin/python" -m motion_module.mecanum_hardware "$active_target" "$CONFIG_FILE"

if [ ! -f "$PROJECT_DIR/README.md" ] || grep -q '^# MotionModule student workspace$' "$PROJECT_DIR/README.md"; then
cat > "$PROJECT_DIR/README.md" <<EOF
# MotionModule student workspace

Every editable robot project has its own folder under \`robots/\`. The installer
starts with \`robots/$ACTIVE_PROJECT\`. Edit that folder, then run:

\`\`\`bash
motionmodule restart
motionmodule logs
motionmodule project list
\`\`\`

A robot folder needs only \`robot.py\`. Open the dashboard Code page, download
the sample, edit that folder on any computer, then choose the folder under
Driver Station. The robot validates, backs up, and activates it, then runs it
directly through the robot website.

An update gives a folder you have not edited the newest sample and keeps the
copy it replaced in \`backups/\`. A folder you have edited is your work, and
no install changes it.

Motors and servos are addressed by name: \`module.motor("motor_1")\`. Those
names live in \`$CONFIG_FILE\`. To rename them for one robot, copy that file
into the robot folder as \`hardware.py\` and edit it there.

Run \`motionmodule pinout\` and \`motionmodule doctor\` before powered testing.
EOF
fi

say "Installing the dashboard, service, management command, and Wi-Fi failover controller..."
# Every file this install writes outside the release is recorded, so the sweep
# further down can tell it apart from files an older install left behind.
installed_system_files=()
install_system_file() {
    sudo install -m "$1" "$2" "$3"
    installed_system_files+=("$3")
}

install_system_file 0755 "$release_dir/installer/motionmodule" /usr/local/bin/motionmodule
install_system_file 0755 "$release_dir/installer/network_manager.py" /usr/local/sbin/motionmodule-network
install_system_file 0755 "$release_dir/installer/hotspot.sh" /usr/local/sbin/motionmodule-hotspot
install_system_file 0755 "$release_dir/installer/dashboard_launcher" /usr/local/sbin/motionmodule-dashboard
install_system_file 0755 "$release_dir/installer/update.sh" /usr/local/sbin/motionmodule-update
install_system_file 0755 "$release_dir/installer/askpass.sh" /usr/local/sbin/motionmodule-askpass

sudoers_temp="$(mktemp)"
systemctl_path="$(command -v systemctl)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/motionmodule-network *\n' "$USER" > "$sudoers_temp"
printf '%s ALL=(root) NOPASSWD: %s restart motionmodule.service\n' "$USER" "$systemctl_path" >> "$sudoers_temp"
sudo visudo -cf "$sudoers_temp" >/dev/null
install_system_file 0440 "$sudoers_temp" /etc/sudoers.d/motionmodule-network
rm -f "$sudoers_temp"

# The dashboard's update button, restricted to these exact command lines.
# "password" gives a running update the sudo password it was started with;
# the helper answers only processes inside that update.
update_sudoers_temp="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/motionmodule-update main\n' "$USER" > "$update_sudoers_temp"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/motionmodule-update testing\n' "$USER" >> "$update_sudoers_temp"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/motionmodule-update password\n' "$USER" >> "$update_sudoers_temp"
sudo visudo -cf "$update_sudoers_temp" >/dev/null
install_system_file 0440 "$update_sudoers_temp" /etc/sudoers.d/motionmodule-update
rm -f "$update_sudoers_temp"

say "Saving the Raspberry Pi Imager Wi-Fi as the preferred startup network..."
sudo /usr/local/sbin/motionmodule-network init >/dev/null

network_service_temp="$(mktemp)"
cat > "$network_service_temp" <<'EOF'
[Unit]
Description=MotionModule Wi-Fi monitor and automatic hotspot fallback
After=NetworkManager.service
Wants=NetworkManager.service
Before=motionmodule.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/motionmodule-network watch --timeout 30
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
install_system_file 0644 "$network_service_temp" /etc/systemd/system/motionmodule-network.service
rm -f "$network_service_temp"

nginx_temp="$(mktemp)"
cat > "$nginx_temp" <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 12m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 65s;
    }
}
EOF
install_system_file 0644 "$nginx_temp" /etc/nginx/sites-available/motionmodule
rm -f "$nginx_temp"
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/motionmodule /etc/nginx/sites-enabled/motionmodule
installed_system_files+=(/etc/nginx/sites-enabled/motionmodule)

service_temp="$(mktemp)"
cat > "$service_temp" <<EOF
[Unit]
Description=MotionModule robot dashboard and runtime
After=motionmodule-network.service
Wants=motionmodule-network.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/active
Environment=PYTHONUNBUFFERED=1
Environment=MOTIONMODULE_CONFIG=$CONFIG_FILE
Environment=MOTIONMODULE_ACTIVE_PROJECT=$PROJECT_DIR/active
ExecStart=/usr/local/sbin/motionmodule-dashboard "$CURRENT_LINK" "$PROJECT_DIR/active/robot.py"
Restart=always
RestartSec=2
KillSignal=SIGINT
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOF
install_system_file 0644 "$service_temp" /etc/systemd/system/motionmodule.service
rm -f "$service_temp"

# The Arduino GIGA R1 WiFi reads the robot's sensors. This lets the MotionModule
# user flash its firmware over USB without sudo, whether it is running a sketch
# (2341:0266) or waiting in its bootloader (2341:0366).
udev_temp="$(mktemp)"
cat > "$udev_temp" <<'RULES'
# Installed by MotionModule: Arduino GIGA R1 WiFi sensor firmware installs.
SUBSYSTEM=="usb", ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0266|0366", MODE="0660", GROUP="plugdev"
RULES
install_system_file 0644 "$udev_temp" /etc/udev/rules.d/motionmodule-giga.rules
rm -f "$udev_temp"
sudo udevadm control --reload-rules >/dev/null 2>&1 || true
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2341 --action=change >/dev/null 2>&1 || true

# Scripts, sudo rules, services, web server sites, and device rules that an
# older install wrote but this version does not ship. Removing them means a
# file one branch installs never lingers after switching to a branch without it.
while IFS= read -r stale; do
    case "$stale" in
        /etc/systemd/system/*.service)
            sudo systemctl disable --now "${stale##*/}" >/dev/null 2>&1 || true
            ;;
    esac
    sudo rm -f -- "$stale"
    say "Removed $stale, left by an older MotionModule install."
done < <(
    { sudo find /usr/local/sbin /etc/sudoers.d /etc/systemd/system /etc/nginx/sites-available /etc/nginx/sites-enabled \
        /etc/udev/rules.d \
        -maxdepth 1 -name 'motionmodule*' \( -type f -o -type l \) 2>/dev/null || true; } \
        | unlisted_paths "${installed_system_files[@]}"
)

sudo nginx -t
sudo systemctl enable nginx.service
sudo systemctl daemon-reload
sudo systemctl enable motionmodule-network.service motionmodule.service

if [ -n "$TARGET_HOSTNAME" ]; then
    if ! printf '%s' "$TARGET_HOSTNAME" | grep -Eq '^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$'; then
        fail "Invalid hostname: $TARGET_HOSTNAME"
    fi
    TARGET_HOSTNAME="$(printf '%s' "$TARGET_HOSTNAME" | tr '[:upper:]' '[:lower:]')"
    printf '{"hostname":"%s"}\n' "$TARGET_HOSTNAME" | \
        sudo /usr/local/sbin/motionmodule-network hostname >/dev/null
fi

say "Activating the new release..."
old_target=""
if [ -L "$CURRENT_LINK" ] && [ -e "$CURRENT_LINK/.complete" ]; then
    old_target="$(readlink -f "$CURRENT_LINK")"
fi
ln -s "$release_dir" "$INSTALL_ROOT/current.new.$$"
mv -Tf "$INSTALL_ROOT/current.new.$$" "$CURRENT_LINK"

new_release_running=false
if [ "$START_SERVICE" = true ]; then
    sudo systemctl restart motionmodule-network.service
    if ! sudo systemctl restart motionmodule.service; then
        if [ -n "$old_target" ]; then
            ln -s "$old_target" "$INSTALL_ROOT/current.restore.$$"
            mv -Tf "$INSTALL_ROOT/current.restore.$$" "$CURRENT_LINK"
            sudo systemctl restart motionmodule.service || true
        else
            sudo systemctl stop motionmodule.service || true
        fi
        sudo systemctl restart nginx.service || true
        fail "The new service did not start; the previous release was restored when available. Check journalctl."
    fi
    sudo systemctl restart nginx.service
    # A restart returns as soon as the process launches. Before the release it
    # replaced is deleted, confirm the same process is still running a few
    # seconds later rather than crashing and being restarted.
    started_at="$(systemctl show -p ActiveEnterTimestampMonotonic --value motionmodule.service 2>/dev/null || true)"
    sleep 8
    if systemctl is-active --quiet motionmodule.service \
        && [ "$(systemctl show -p ActiveEnterTimestampMonotonic --value motionmodule.service 2>/dev/null || true)" = "$started_at" ]; then
        new_release_running=true
    fi
fi

# ---- Replace the old software, keep the robot --------------------------------
# An install replaces MotionModule rather than stacking versions beside each
# other, so main and testing (or any tag or commit) can replace one another in
# either direction. The rules live in runtime_cleanup.sh. Robot projects and
# their backups, the active project, hardware.py pin names, and the Wi-Fi and
# hotspot settings are never removed.
keep_release="$(rollback_candidate "$old_target" "$VERSION_REF")"
if [ -n "$old_target" ] && [ "$new_release_running" != true ]; then
    # Until the new release has been seen running, the one it replaced stays
    # as the way back, whichever branch it came from.
    keep_release="$old_target"
    say "Keeping $(basename "$old_target") for motionmodule rollback until the new release is confirmed running; the next install removes it."
elif [ -n "$keep_release" ]; then
    say "Keeping $(basename "$keep_release") from the same branch ($VERSION_REF) for motionmodule rollback."
fi
if [ -n "$keep_release" ]; then
    ln -sfn "$keep_release" "$PREVIOUS_LINK"
else
    rm -f -- "$PREVIOUS_LINK"
fi
while IFS= read -r removed; do
    say "Removed older MotionModule release $removed."
done < <(remove_other_releases "$RELEASES_DIR" "$release_dir" "$keep_release")
rm -f -- "$INSTALL_ROOT"/current.new.* "$INSTALL_ROOT"/current.restore.* "$PROJECT_DIR"/active.new.*
rm -rf -- "$PROJECT_DIR/.uploads"
rm -f -- "$CONFIG_DIR/terminal-access.json"
say "Kept the robot's own files: $ROBOT_DIR, $PROJECT_DIR/backups, the active project, $CONFIG_FILE, and the Wi-Fi settings."

say "Running the automatic non-moving hardware check..."
if ! /usr/local/bin/motionmodule doctor; then
    say "Doctor found a problem. The installation will finish and reboot; review the result above before applying motor or servo power."
fi

say "Installation complete. No automatic updater was enabled."
printf 'Active release: %s\n' "$release_id"
printf 'Active robot:   %s/%s\n' "$ROBOT_DIR" "$ACTIVE_PROJECT"
printf 'Configuration:  %s\n' "$CONFIG_FILE"
printf 'Robot dashboard: http://%s.local (or type the Pi IP directly)\n' "${TARGET_HOSTNAME:-$(hostname)}"
printf 'Admin SSH:       ssh %s@%s.local\n' "$USER" "${TARGET_HOSTNAME:-$(hostname)}"
printf 'Wi-Fi fallback: MotionModule hotspot after 30 seconds offline\n'
if [ "$REBOOT_SYSTEM" = true ]; then
    say "Rebooting automatically in 3 seconds so GPIO/I2C group membership and boot settings take effect."
else
    say "Automatic reboot skipped. Reboot manually before the first hardware test."
fi
printf '\nCheck GitHub for the proper pinout before wiring the robot: https://github.com/AloeVeraZ/MotionModule/blob/main/docs/PINOUT.md\n'

if [ "$REBOOT_SYSTEM" = true ]; then
    sleep 3
    sudo systemctl reboot
fi

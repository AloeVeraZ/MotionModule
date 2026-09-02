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

say() { printf '\n\033[1;36m[MotionModule]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[MotionModule ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
trap 'fail "Installation stopped on line $LINENO. Read the error above and rerun the same command."' ERR

[ "$(id -u)" -ne 0 ] || fail "Run this as the normal Pi user, without sudo."
[ -n "$SOURCE_DIR" ] || fail "The installer source directory was not provided. Run the repository install.sh."
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
[ -f "$SOURCE_DIR/pyproject.toml" ] || fail "pyproject.toml is missing from $SOURCE_DIR"
[ -f "$SOURCE_DIR/config/default.toml" ] || fail "The default hardware configuration is missing."
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
CONFIG_FILE="$CONFIG_DIR/config.toml"

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

for group in gpio i2c; do
    if getent group "$group" >/dev/null; then
        sudo usermod -aG "$group" "$USER"
    fi
done

sudo systemctl enable --now ssh avahi-daemon

say "Building isolated release $release_id..."
mkdir -p "$RELEASES_DIR"
mkdir "$release_dir"
cp -a "$SOURCE_DIR/." "$release_dir/"
rm -rf -- "$release_dir/.git" "$release_dir/.venv" "$release_dir/__pycache__"
printf '%s\n' "$VERSION_REF" > "$release_dir/INSTALL_REF"

python3 -m venv --system-site-packages "$release_dir/.venv"
"$release_dir/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"$release_dir/.venv/bin/python" -m pip install --no-build-isolation -e "$release_dir"
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
        say "Created robot project $ROBOT_DIR/$robot_name. Future installs will not overwrite it."
    else
        say "Keeping existing robot project $ROBOT_DIR/$robot_name."
    fi
done
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
if [ ! -f "$CONFIG_FILE" ]; then
    install -m 0644 "$release_dir/config/default.toml" "$CONFIG_FILE"
else
    say "Keeping the existing hardware configuration at $CONFIG_FILE."
fi

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

New robot folders keep their pins and electrical setup in \`hardware.py\` next
to \`robot.py\`. Open the dashboard Code page, download the sample, edit that
folder on any computer, then choose the folder under Driver Station. The robot
validates, backs up, activates, and runs it directly through the robot website.

Older projects without \`hardware.py\` continue to use \`$CONFIG_FILE\`.
Run \`motionmodule pinout\` and \`motionmodule doctor\` before powered testing.
EOF
fi

say "Installing the dashboard, service, management command, and Wi-Fi failover controller..."
sudo install -m 0755 "$release_dir/installer/motionmodule" /usr/local/bin/motionmodule
sudo install -m 0755 "$release_dir/installer/network_manager.py" /usr/local/sbin/motionmodule-network
sudo install -m 0755 "$release_dir/installer/hotspot.sh" /usr/local/sbin/motionmodule-hotspot
sudo install -m 0755 "$release_dir/installer/dashboard_launcher" /usr/local/sbin/motionmodule-dashboard

sudoers_temp="$(mktemp)"
systemctl_path="$(command -v systemctl)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/motionmodule-network *\n' "$USER" > "$sudoers_temp"
printf '%s ALL=(root) NOPASSWD: %s restart motionmodule.service\n' "$USER" "$systemctl_path" >> "$sudoers_temp"
sudo visudo -cf "$sudoers_temp" >/dev/null
sudo install -m 0440 "$sudoers_temp" /etc/sudoers.d/motionmodule-network
rm -f "$sudoers_temp"

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
sudo install -m 0644 "$network_service_temp" /etc/systemd/system/motionmodule-network.service
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
sudo install -m 0644 "$nginx_temp" /etc/nginx/sites-available/motionmodule
rm -f "$nginx_temp"
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/motionmodule /etc/nginx/sites-enabled/motionmodule
sudo nginx -t
sudo systemctl enable nginx.service

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
sudo install -m 0644 "$service_temp" /etc/systemd/system/motionmodule.service
rm -f "$service_temp"
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

say "Activating the new release without deleting older versions..."
old_target=""
if [ -L "$CURRENT_LINK" ] && [ -e "$CURRENT_LINK/.complete" ]; then
    old_target="$(readlink -f "$CURRENT_LINK")"
    ln -sfn "$old_target" "$PREVIOUS_LINK"
fi
ln -s "$release_dir" "$INSTALL_ROOT/current.new.$$"
mv -Tf "$INSTALL_ROOT/current.new.$$" "$CURRENT_LINK"

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
fi

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

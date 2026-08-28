#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR=""
VERSION_REF="${MOTIONMODULE_VERSION:-main}"
TARGET_HOSTNAME="__default__"
START_SERVICE=true

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
        --no-hostname)
            TARGET_HOSTNAME=""
            shift
            ;;
        --no-start)
            START_SERVICE=false
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
[ -f "$SOURCE_DIR/Mecanum/robot.py" ] || fail "The Mecanum example is missing."
command -v sudo >/dev/null || fail "sudo is required for Raspberry Pi setup."

INSTALL_ROOT="${MOTIONMODULE_INSTALL_ROOT:-$HOME/.local/share/motionmodule}"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
PREVIOUS_LINK="$INSTALL_ROOT/previous"
PROJECT_DIR="${MOTIONMODULE_PROJECT_DIR:-$HOME/MotionModule}"
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

say "Installing Raspberry Pi, GPIO, I2C, SSH, and Python dependencies..."
apt_get update
apt_get install -y \
    avahi-daemon \
    ca-certificates \
    curl \
    git \
    i2c-tools \
    iproute2 \
    network-manager \
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
"$release_dir/.venv/bin/python" -m unittest discover -s "$release_dir/tests" -v
touch "$release_dir/.complete"

say "Creating the persistent student workspace..."
mkdir -p "$PROJECT_DIR" "$CONFIG_DIR"
if [ ! -e "$PROJECT_DIR/Mecanum" ]; then
    cp -a "$release_dir/Mecanum" "$PROJECT_DIR/Mecanum"
    say "Created $PROJECT_DIR/Mecanum. Future installs will not overwrite student code there."
else
    say "Keeping the existing student code at $PROJECT_DIR/Mecanum."
fi
if [ ! -f "$CONFIG_FILE" ]; then
    install -m 0644 "$release_dir/config/default.toml" "$CONFIG_FILE"
else
    say "Keeping the existing hardware configuration at $CONFIG_FILE."
fi

if [ ! -f "$PROJECT_DIR/README.md" ]; then
cat > "$PROJECT_DIR/README.md" <<EOF
# MotionModule student workspace

Edit \`Mecanum/robot.py\` and \`Mecanum/mecanum.py\`, then run:

\`\`\`bash
motionmodule restart
motionmodule logs
\`\`\`

Hardware configuration lives at \`$CONFIG_FILE\` and is intentionally outside
the versioned runtime. Run \`motionmodule pinout\` and \`motionmodule doctor\`
before the first powered test.
EOF
fi

say "Installing the service, management command, and Wi-Fi failover controller..."
sudo install -m 0755 "$release_dir/installer/motionmodule" /usr/local/bin/motionmodule
sudo install -m 0755 "$release_dir/installer/network_manager.py" /usr/local/sbin/motionmodule-network
sudo install -m 0755 "$release_dir/installer/hotspot.sh" /usr/local/sbin/motionmodule-hotspot

sudoers_temp="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/motionmodule-network *\n' "$USER" > "$sudoers_temp"
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

service_temp="$(mktemp)"
cat > "$service_temp" <<EOF
[Unit]
Description=MotionModule student robot runtime
After=motionmodule-network.service
Wants=motionmodule-network.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/Mecanum
Environment=PYTHONUNBUFFERED=1
Environment=MOTIONMODULE_CONFIG=$CONFIG_FILE
ExecStart=$CURRENT_LINK/.venv/bin/python -m motion_module.runner $PROJECT_DIR/Mecanum/robot.py
Restart=on-failure
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
    if ! printf '%s' "$TARGET_HOSTNAME" | grep -Eq '^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$'; then
        fail "Invalid hostname: $TARGET_HOSTNAME"
    fi
    sudo hostnamectl set-hostname "$TARGET_HOSTNAME"
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
        fail "The new service did not start; the previous release was restored when available. Check journalctl."
    fi
fi

say "Installation complete. No automatic updater was enabled."
printf 'Active release: %s\n' "$release_id"
printf 'Student code:   %s/Mecanum\n' "$PROJECT_DIR"
printf 'Configuration:  %s\n' "$CONFIG_FILE"
printf 'Browser drive:  http://%s.local:8080\n' "${TARGET_HOSTNAME:-$(hostname)}"
printf 'SSH / VS Code:  ssh %s@%s.local\n' "$USER" "${TARGET_HOSTNAME:-$(hostname)}"
printf 'Wi-Fi fallback: MotionModule hotspot after 30 seconds offline\n'
printf '\nRun "motionmodule doctor", then reboot before the first hardware test.\n'

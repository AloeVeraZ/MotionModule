# Installer behavior

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

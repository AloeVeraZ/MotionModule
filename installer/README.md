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

Bundled examples are copied once into `~/MotionModule/robots`; existing robot
folders are never overwritten. The `active` symlink selects the project loaded
by the dashboard. Current projects include a data-only `hardware.py`; older
projects may continue using `~/.config/motionmodule/config.toml`.

The browser Driver Station accepts one local Python project folder. Deployment
validates paths, size, file types, Python syntax, `robot.py`, and `hardware.py`,
stops output, backs up an existing target, installs it atomically, switches
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

No update service or timer is installed. Runtime changes require an explicit
`motionmodule install REF`, `motionmodule activate NAME`, or
`motionmodule rollback`.

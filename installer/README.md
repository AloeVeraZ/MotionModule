# Installer behavior

Run the repository entry point, not this file directly:

```bash
bash install.sh --hostname motionmodule-01
```

Or after the repository is published:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --version main --hostname motionmodule-01
```

Options:

| Option | Meaning |
| --- | --- |
| `--version REF` | Explicit Git branch, tag, or fetchable commit to install |
| `--hostname NAME` | Set the Pi's mDNS hostname |
| `--robot PROJECT` | Select a folder from repository `examples/`; defaults to `Mecanum` |
| `--no-hostname` | Preserve the current hostname |
| `--no-start` | Install and enable the service without starting it |
| `--no-reboot` | Skip the default automatic reboot |

The bootstrap downloads the requested ref to a temporary directory. The main
installer installs system dependencies, copies that source into a new release,
creates a per-release virtual environment, runs unit tests, and marks the
release complete. Only then is `current` switched. An error before activation
leaves the previous service target unchanged.

The repository keeps reusable system code at its root and copyable robot styles
under `examples/`. Each example is copied once into
`~/MotionModule/robots/PROJECT_NAME`, while `~/MotionModule/active` selects the
project loaded by the service. Existing robot folders are never overwritten.
Version 0.4 also moves projects created by the earlier direct-folder layout
into `robots/`. After installation, use `motionmodule project list` and
`motionmodule project PROJECT_NAME` to inspect or switch them.

It also installs the root-owned constrained network helper and
`motionmodule-network.service`. The helper records the active Imager-created
Wi-Fi during installation. At boot, the service allows saved client Wi-Fi 30
seconds to connect before starting the protected `MotionModule` hotspot. The
versioned dashboard can invoke only the helper's fixed status, scan, connect,
preferred-network, and hotspot operations through a dedicated sudoers rule.

Nginx is installed as a port-80 reverse proxy to the dashboard on
`127.0.0.1:8080`. This makes both `http://HOSTNAME.local` and a bare Pi IP work
without asking students to remember a port number.
The stable dashboard launcher falls back to the original `motion_module.runner`
for pre-0.2.0 releases, preserving explicit rollback after the service unit has
been upgraded.

The Code-page Bash terminal is installed with the dashboard but remains locked
until the Pi user runs `motionmodule terminal enable [MINUTES]` over SSH. That
command creates a mode-0600, boot-scoped access grant under
`~/.config/motionmodule`; `motionmodule terminal disable` revokes it. The shell
runs as the service user and receives no additional sudo permission.

After activation, the installer automatically runs the non-moving
`motionmodule doctor` check, prints its results, and reboots so the new GPIO/I2C
group membership and boot configuration take effect. Its final message links
directly to the GitHub pinout. Use `--no-reboot` only when another provisioning
step must run before rebooting.

The first install defaults to hostname `motionmodule`. Later installs preserve
the active hostname unless `--hostname` is explicitly supplied.

No automatic update service or timer is installed. Use
`motionmodule install REF`, inspect `motionmodule versions`, and use
`motionmodule rollback` or `motionmodule activate NAME` explicitly.

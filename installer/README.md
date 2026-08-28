# Installer behavior

Run the repository entry point, not this file directly:

```bash
bash install.sh --hostname motionmodule-01
```

Or after the repository is published:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | \
  bash -s -- --version v0.1.0 --hostname motionmodule-01
```

Options:

| Option | Meaning |
| --- | --- |
| `--version REF` | Explicit Git branch, tag, or fetchable commit to install |
| `--hostname NAME` | Set the Pi's mDNS hostname |
| `--no-hostname` | Preserve the current hostname |
| `--no-start` | Install and enable the service without starting it |

The bootstrap downloads the requested ref to a temporary directory. The main
installer installs system dependencies, copies that source into a new release,
creates a per-release virtual environment, runs unit tests, and marks the
release complete. Only then is `current` switched. An error before activation
leaves the previous service target unchanged.

It also installs the root-owned constrained network helper and
`motionmodule-network.service`. The helper records the active Imager-created
Wi-Fi during installation. At boot, the service allows saved client Wi-Fi 30
seconds to connect before starting the protected `MotionModule` hotspot. The
student web process can invoke only the helper's fixed status, scan, connect,
preferred-network, and hotspot operations through a dedicated sudoers rule.

The first install defaults to hostname `motionmodule`. Later installs preserve
the active hostname unless `--hostname` is explicitly supplied.

No automatic update service or timer is installed. Use
`motionmodule install REF`, inspect `motionmodule versions`, and use
`motionmodule rollback` or `motionmodule activate NAME` explicitly.

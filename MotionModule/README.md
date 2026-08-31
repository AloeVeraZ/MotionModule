# MotionModule system folder

This directory is the complete installable MotionModule system. The repository
root keeps only the public README and the small `install.sh` bootstrap that
downloads and starts `installer/install.sh` from here.

```text
MotionModule/
├── core/motion_module/   reusable Python runtime and web dashboard
├── installer/            Raspberry Pi setup and service scripts
├── Mecanum/              default robot project
├── config/               persistent hardware-config template
├── docs/                 setup, wiring, coding, and architecture
├── tests/                hardware-independent test suite
├── requirements.txt
└── pyproject.toml
```

The folders `core`, `installer`, `config`, `docs`, and `tests` make the system
work. A direct child folder containing `robot.py` is a selectable robot project.
That means `Swerve/robot.py` or `WalkingRobot/robot.py` can be added beside
`Mecanum` without copying or rewriting the core.

On a Raspberry Pi, use the repository-root installer:

```bash
curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/main/install.sh | bash
```

For local development from this directory:

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
```

See [docs/SETUP.md](docs/SETUP.md), [docs/CODING.md](docs/CODING.md), and the
required [docs/PINOUT.md](docs/PINOUT.md).

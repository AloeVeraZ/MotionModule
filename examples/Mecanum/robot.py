"""Student-editable drive hook loaded by the MotionModule dashboard."""

from mecanum import MecanumDrive


def create_drive(module):
    """Return the drive object used by the dashboard's Code/Drive section.

    Keep this tiny while getting started. ``hardware.py`` owns pins and
    electrical setup; ``mecanum.py`` owns the wheel math and channel mapping.
    You can return any object with ``drive(...)`` and ``stop()`` methods.
    """

    return MecanumDrive(module)

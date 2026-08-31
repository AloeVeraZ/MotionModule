"""Student-editable drive hook loaded by the MotionModule dashboard."""

from mecanum import MecanumDrive


def create_drive(module):
    """Return the drive object used by the dashboard's Drive page.

    Keep this tiny while getting started. You can change the channel mapping in
    ``mecanum.py`` or return your own object with ``drive(...)`` and ``stop()``
    methods as the robot project grows.
    """

    return MecanumDrive(module)

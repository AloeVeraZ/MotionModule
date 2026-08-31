"""MotionModule exceptions."""


class MotionModuleError(Exception):
    """Base exception for expected MotionModule failures."""


class ConfigurationError(MotionModuleError):
    """The pin or runtime configuration is unsafe or invalid."""


class HardwareUnavailable(MotionModuleError):
    """Requested hardware is missing or cannot be accessed."""


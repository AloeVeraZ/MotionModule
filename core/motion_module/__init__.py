"""Public student-facing MotionModule API."""

from .config import ModuleConfig, load_config
from .controller import MotionModule
from .errors import ConfigurationError, HardwareUnavailable, MotionModuleError

__all__ = [
    "ConfigurationError",
    "HardwareUnavailable",
    "ModuleConfig",
    "MotionModule",
    "MotionModuleError",
    "load_config",
]

__version__ = "0.8.1"

"""Public MotionModule API used by robot projects."""

from .config import ModuleConfig, ServoSlot, default_config, load_config, load_hardware_file
from .controller import MotionModule
from .errors import ConfigurationError, HardwareUnavailable, MotionModuleError

__all__ = [
    "ConfigurationError",
    "HardwareUnavailable",
    "ModuleConfig",
    "MotionModule",
    "MotionModuleError",
    "ServoSlot",
    "default_config",
    "load_config",
    "load_hardware_file",
]

__version__ = "0.10.0"

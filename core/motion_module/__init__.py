"""Public MotionModule API used by robot projects."""

from .config import ModuleConfig, ServoSlot, default_config, load_config, load_hardware_file
from .controller import MotionModule
from .errors import ConfigurationError, HardwareUnavailable, MotionModuleError
from .input import DigitalInput, available_input_gpios

__all__ = [
    "ConfigurationError",
    "DigitalInput",
    "HardwareUnavailable",
    "ModuleConfig",
    "MotionModule",
    "MotionModuleError",
    "ServoSlot",
    "available_input_gpios",
    "default_config",
    "load_config",
    "load_hardware_file",
]

__version__ = "0.11.0"

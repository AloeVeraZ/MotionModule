"""Pins and electrical behavior that travel with this robot project.

MotionModule reads this file as literal Python data before starting robot.py.
Do not add imports, function calls, or calculated values here.
"""

HARDWARE = {
    "module": {
        "pwm_hz": 1000,
        "deadtime_ms": 15,
        "watchdog_ms": 500,
    },
    "motors": {
        1: {"name": "front_left", "forward_gpio": 12, "reverse_gpio": 6, "inverted": True},
        2: {"name": "rear_left", "forward_gpio": 19, "reverse_gpio": 16, "inverted": True},
        3: {"name": "front_right", "forward_gpio": 20, "reverse_gpio": 21, "inverted": True},
        4: {"name": "rear_right", "forward_gpio": 26, "reverse_gpio": 13, "inverted": True},
        5: {"name": "driver3_a", "forward_gpio": 5, "reverse_gpio": 25, "inverted": False},
        6: {"name": "driver3_b", "forward_gpio": 9, "reverse_gpio": 11, "inverted": False},
        7: {"name": "driver4_a", "forward_gpio": 8, "reverse_gpio": 7, "inverted": False},
        8: {"name": "driver4_b", "forward_gpio": 23, "reverse_gpio": 24, "inverted": False},
    },
    "servos": {
        "enabled": True,
        "i2c_bus": 1,
        "frequency_hz": 50,
        "addresses": [0x40],
        "minimum_pulse_us": 500,
        "maximum_pulse_us": 2500,
    },
}

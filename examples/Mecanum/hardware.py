"""Pin and name definitions for this Mecanum robot.

This is a copy of the hardware.py that ships with MotionModule, with the four
drive motors renamed. Everything else is unchanged. Keep this file with the
sample robot.py because its drive code uses these wheel names. A robot that
uses the built-in names (driver_1a ... driver_4b, servo_0 ... servo_15) can
omit it.

Rename a motor here and use that same name in robot.py. If a wheel spins the
wrong way, flip only that motor's `inverted` value — never the drive math.

MotionModule reads this file as data. No imports, `if` statements, or function
calls. Validation checks the map before the robot uses it.
"""

HARDWARE = {
    "module": {
        "pwm_hz": 1000,      # Motor PWM frequency sent to the H-bridge inputs.
        "deadtime_ms": 15,   # Coast time inserted before a motor reverses.
        "watchdog_ms": 500,  # All motors stop if no new command arrives in time.
    },

    # Each driver owns a short run of header positions with its own ground
    # inside the run, so one driver is one small bundle of wires.
    #
    # channel  name          driver / output   IN1 wire        IN2 wire
    # -------  ------------  ---------------   -------------   -------------
    #    1     front_left    Driver 1 · A      pin 37/GPIO26   pin 35/GPIO19
    #    2     rear_left     Driver 1 · B      pin 33/GPIO13   pin 31/GPIO6
    #    3     front_right   Driver 2 · A      pin 40/GPIO21   pin 38/GPIO20
    #    4     rear_right    Driver 2 · B      pin 36/GPIO16   pin 32/GPIO12
    #    5-8   spare         Drivers 3 and 4   see docs/PINOUT.md
    #
    # Every wheel starts uninverted. Test each one raised, then set `inverted`
    # True on any wheel that turns the wrong way.
    "motors": {
        1: {"name": "front_left", "forward_gpio": 26, "reverse_gpio": 19, "inverted": False},
        2: {"name": "rear_left", "forward_gpio": 13, "reverse_gpio": 6, "inverted": False},
        3: {"name": "front_right", "forward_gpio": 21, "reverse_gpio": 20, "inverted": False},
        4: {"name": "rear_right", "forward_gpio": 16, "reverse_gpio": 12, "inverted": False},
        5: {"name": "driver_3a", "forward_gpio": 11, "reverse_gpio": 9, "inverted": False},
        6: {"name": "driver_3b", "forward_gpio": 7, "reverse_gpio": 8, "inverted": False},
        7: {"name": "driver_4a", "forward_gpio": 22, "reverse_gpio": 27, "inverted": False},
        8: {"name": "driver_4b", "forward_gpio": 24, "reverse_gpio": 23, "inverted": False},
    },

    # One PCA9685 board on I2C: SDA pin 3, SCL pin 5, VCC pin 1, GND pin 6.
    # Servo power (V+) comes from its own regulated 5-6 V supply, never the Pi.
    "servos": {
        "enabled": True,
        "i2c_bus": 1,
        "frequency_hz": 50,
        "addresses": [0x40],
        # OE (output enable) on the servo board, wired to physical pin 7.
        # Active low: MotionModule holds it low to enable the outputs and
        # drives it high to cut all 16 of them at once, without needing the
        # I2C bus to still be working. Set this to None if you leave OE
        # unconnected; the board pulls it low on its own.
        "output_enable_gpio": 4,
        "minimum_pulse_us": 500,
        "maximum_pulse_us": 2500,
        "channels": {
            0: {"name": "servo_0", "board": 0},
            1: {"name": "servo_1", "board": 0},
            2: {"name": "servo_2", "board": 0},
            3: {"name": "servo_3", "board": 0},
            4: {"name": "servo_4", "board": 0},
            5: {"name": "servo_5", "board": 0},
            6: {"name": "servo_6", "board": 0},
            7: {"name": "servo_7", "board": 0},
            8: {"name": "servo_8", "board": 0},
            9: {"name": "servo_9", "board": 0},
            10: {"name": "servo_10", "board": 0},
            11: {"name": "servo_11", "board": 0},
            12: {"name": "servo_12", "board": 0},
            13: {"name": "servo_13", "board": 0},
            14: {"name": "servo_14", "board": 0},
            15: {"name": "servo_15", "board": 0},
        },
    },
}

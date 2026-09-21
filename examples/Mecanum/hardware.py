"""Pin and name definitions for this Mecanum robot.

LOCKED WIRING: the robot is wired exactly like this, and that wiring works.
Never change a GPIO in this file, motor or servo, and never move a wheel to
another channel. Renaming channels 5-8 and flipping `inverted` are fine.
AGENTS.md at the repository root explains, and tests/test_wiring_lock.py
fails if a pin here moves.

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
    # inside the run, so one driver is one small bundle of wires. On each
    # board, IN1 and IN2 drive MOTOR_A (output A) and IN3 and IN4 drive
    # MOTOR_B (output B). Driver 1 sits beside the Pi's USB ports and
    # Driver 2 above it.
    #
    # channel  name          driver / output   forward wire        reverse wire
    # -------  ------------  ---------------   -----------------   -----------------
    #    1     front_left    Driver 1 · A      IN1 pin 37/GPIO26   IN2 pin 35/GPIO19
    #    2     rear_left     Driver 1 · B      IN3 pin 33/GPIO13   IN4 pin 31/GPIO6
    #    3     front_right   Driver 2 · A      IN1 pin 40/GPIO21   IN2 pin 38/GPIO20
    #    4     rear_right    Driver 2 · B      IN3 pin 36/GPIO16   IN4 pin 32/GPIO12
    #    5-8   spare         Drivers 3 and 4   see docs/PINOUT.md
    #
    # The raised-wheel motor bench confirms that all four drivetrain motors
    # need their logical direction flipped: Hold + then turns every wheel
    # toward the front of the robot. Test each wheel raised, then flip only
    # that wheel's `inverted` value if its motor leads are mounted differently.
    "motors": {
        1: {"name": "front_left", "forward_gpio": 26, "reverse_gpio": 19, "inverted": True},
        2: {"name": "rear_left", "forward_gpio": 13, "reverse_gpio": 6, "inverted": True},
        3: {"name": "front_right", "forward_gpio": 21, "reverse_gpio": 20, "inverted": True},
        4: {"name": "rear_right", "forward_gpio": 16, "reverse_gpio": 12, "inverted": True},
        5: {"name": "driver_3a", "forward_gpio": 11, "reverse_gpio": 9, "inverted": True},
        6: {"name": "driver_3b", "forward_gpio": 7, "reverse_gpio": 8, "inverted": False},
        7: {"name": "driver_4a", "forward_gpio": 22, "reverse_gpio": 27, "inverted": True},
        8: {"name": "driver_4b", "forward_gpio": 24, "reverse_gpio": 23, "inverted": False},
    },

    # One PCA9685 board on I2C: VCC pin 1, SDA pin 3, SCL pin 5, OE pin 7,
    # GND pin 9.
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

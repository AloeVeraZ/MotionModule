"""MotionModule default hardware definition — the one file that names every pin.

This file ships with MotionModule. It holds all the hardware definitions
your robot.py needs to move motors and servos. Copy it into your own robot
folder when you want to rename something or change a pin.

WHAT THIS FILE DOES
    It turns raw Raspberry Pi pin numbers into names you can use in code.
    Instead of remembering that GPIO12 and GPIO6 are the two direction inputs
    of output A on the second H-bridge board, you write:

        left = module.motor("motor_1")
        left.set(0.5)

    Every motor and servo below has a "name". Change a name here and that new
    name is what your robot code uses. Nothing else has to change.

HOW TO USE IT
    Do nothing, and every MotionModule robot uses the names below.
    To customize, put a copy of this file named `hardware.py` next to your
    `robot.py`, rename the motors and servos to match your machine
    ("front_left", "intake", "claw", ...), and deploy the folder.

RULES FOR EDITING
    * Names use lowercase letters, numbers, and underscores: front_left, arm_2.
    * Every name must be unique across all motors and all servos.
    * `forward_gpio` / `reverse_gpio` are BCM GPIO numbers, not header pins.
      The physical header pin for each one is in the comment on its line.
    * Two motors may never share a GPIO.
    * `inverted` flips which way positive power turns that one motor. If a
      wheel spins backward, change `inverted` here — never the drive math.
    * This file holds data only. No imports, `if` statements, or function
      calls: MotionModule reads it without running it and checks the map
      before the robot uses it.

WIRING
    docs/PINOUT.md has the full wiring map and power rules. BOM.md lists the
    exact parts. Never connect motor battery positive or the servo V+ rail to
    a Raspberry Pi header pin.
"""

HARDWARE = {
    # ------------------------------------------------------------------
    # How the whole module behaves.
    # ------------------------------------------------------------------
    "module": {
        "pwm_hz": 1000,      # Motor PWM frequency sent to the H-bridge inputs.
        "deadtime_ms": 15,   # Coast time inserted before a motor reverses.
        "watchdog_ms": 500,  # All motors stop if no new command arrives in time.
    },

    # ------------------------------------------------------------------
    # Eight brushed-motor outputs: four dual H-bridge boards, two each.
    #
    # channel  name      driver / output   IN1 wire        IN2 wire        driver ground
    # -------  --------  ---------------   -------------   -------------   -------------
    #    1     motor_1   Driver 2 · A      pin 32/GPIO12   pin 31/GPIO6    pin 34
    #    2     motor_2   Driver 2 · B      pin 35/GPIO19   pin 36/GPIO16   pin 34
    #    3     motor_3   Driver 1 · A      pin 38/GPIO20   pin 40/GPIO21   pin 39
    #    4     motor_4   Driver 1 · B      pin 37/GPIO26   pin 33/GPIO13   pin 39
    #    5     motor_5   Driver 3 · A      pin 29/GPIO5    pin 22/GPIO25   pin 20
    #    6     motor_6   Driver 3 · B      pin 21/GPIO9    pin 23/GPIO11   pin 20
    #    7     motor_7   Driver 4 · A      pin 24/GPIO8    pin 26/GPIO7    pin 25
    #    8     motor_8   Driver 4 · B      pin 16/GPIO23   pin 18/GPIO24   pin 25
    #
    # Channels 1-4 are the four drive positions on the reference chassis and
    # are wired so that `inverted` is True. Channels 5-8 are free for
    # intakes, arms, lifts, and other mechanisms.
    # ------------------------------------------------------------------
    "motors": {
        1: {"name": "motor_1", "forward_gpio": 12, "reverse_gpio": 6, "inverted": True},
        2: {"name": "motor_2", "forward_gpio": 19, "reverse_gpio": 16, "inverted": True},
        3: {"name": "motor_3", "forward_gpio": 20, "reverse_gpio": 21, "inverted": True},
        4: {"name": "motor_4", "forward_gpio": 26, "reverse_gpio": 13, "inverted": True},
        5: {"name": "motor_5", "forward_gpio": 5, "reverse_gpio": 25, "inverted": False},
        6: {"name": "motor_6", "forward_gpio": 9, "reverse_gpio": 11, "inverted": False},
        7: {"name": "motor_7", "forward_gpio": 8, "reverse_gpio": 7, "inverted": False},
        8: {"name": "motor_8", "forward_gpio": 23, "reverse_gpio": 24, "inverted": False},
    },

    # ------------------------------------------------------------------
    # Sixteen servo outputs on one PCA9685 board.
    #
    # The board talks to the Pi over I2C, not over motor GPIO:
    #     SDA -> pin 3 / GPIO2      VCC (logic) -> pin 1 / 3.3 V
    #     SCL -> pin 5 / GPIO3      GND         -> pin 6
    #     V+  -> its own regulated 5-6 V servo supply, never a Pi pin.
    #
    # "channels" names each physical output on the board. `board` is the
    # index into "addresses" below. Each dictionary key is the 0-15 number
    # printed on the board unless an explicit "channel" value overrides it.
    #
    # To add a second board: solder its A0 pad for address 0x41, chain
    # SDA/SCL/VCC/GND, set "addresses": [0x40, 0x41], and add channel entries
    # using unique dictionary keys (16-31), "board": 1, and "channel": 0-15.
    # ------------------------------------------------------------------
    "servos": {
        "enabled": True,
        "i2c_bus": 1,
        "frequency_hz": 50,
        "addresses": [0x40],
        "minimum_pulse_us": 500,
        "maximum_pulse_us": 2500,
        "channels": {
            0: {"name": "servo_1", "board": 0},
            1: {"name": "servo_2", "board": 0},
            2: {"name": "servo_3", "board": 0},
            3: {"name": "servo_4", "board": 0},
            4: {"name": "servo_5", "board": 0},
            5: {"name": "servo_6", "board": 0},
            6: {"name": "servo_7", "board": 0},
            7: {"name": "servo_8", "board": 0},
            8: {"name": "servo_9", "board": 0},
            9: {"name": "servo_10", "board": 0},
            10: {"name": "servo_11", "board": 0},
            11: {"name": "servo_12", "board": 0},
            12: {"name": "servo_13", "board": 0},
            13: {"name": "servo_14", "board": 0},
            14: {"name": "servo_15", "board": 0},
            15: {"name": "servo_16", "board": 0},
        },
    },
}

"""MotionModule default hardware definition — the one file that names every pin.

This file ships with MotionModule. It holds all the hardware definitions
your robot.py needs to move motors and servos. Copy it into your own robot
folder when you want to rename something or change a pin.

WHAT THIS FILE DOES
    It turns raw Raspberry Pi pin numbers into names you can use in code.
    Instead of remembering that GPIO26 and GPIO19 are the two direction inputs
    of output A on the first H-bridge board, you write:

        left = module.motor("driver_1a")
        left.set(0.5)

    Every motor and servo below has a "name". Out of the box those names
    describe the hardware position: `driver_1a` is output A on driver board 1,
    and `servo_0` is channel 0 printed on the servo board. Change a name here
    and that new name is what your robot code uses, and what the dashboard
    shows. Nothing else has to change.

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
    # Each driver owns a run of neighbouring header positions with its own
    # ground inside the run, so one driver is one short bundle of wires:
    #
    #   Driver 1  pins 31 33 35 37, ground 39   (left column, bottom)
    #   Driver 2  pins 32 34 36 38 40          (right column, bottom;
    #                                           ground 34 sits between
    #                                           output B's two inputs)
    #   Driver 3  pins 21 23 + 24 26, ground 25 (facing pairs)
    #   Driver 4  pins 13 15 + 16 18, ground 14 (facing pairs)
    #
    # The default name is the driver position, so nothing has to be looked up
    # to wire the robot: `driver_3b` is output B on the third driver board.
    # Rename them to match your machine ("front_left", "intake", ...) and the
    # dashboard follows along.
    #
    # Each board's control header reads IN1 IN2 IN3 IN4 GND. IN1 and IN2
    # drive its MOTOR_A terminal (output A); IN3 and IN4 drive MOTOR_B
    # (output B). `forward_gpio` is the first of the pair, `reverse_gpio`
    # the second.
    #
    # channel  name        driver / output   forward wire        reverse wire        driver ground
    # -------  ----------  ---------------   -----------------   -----------------   -------------
    #    1     driver_1a   Driver 1 · A      IN1 pin 37/GPIO26   IN2 pin 35/GPIO19   pin 39
    #    2     driver_1b   Driver 1 · B      IN3 pin 33/GPIO13   IN4 pin 31/GPIO6    pin 39
    #    3     driver_2a   Driver 2 · A      IN1 pin 40/GPIO21   IN2 pin 38/GPIO20   pin 34
    #    4     driver_2b   Driver 2 · B      IN3 pin 36/GPIO16   IN4 pin 32/GPIO12   pin 34
    #    5     driver_3a   Driver 3 · A      IN1 pin 23/GPIO11   IN2 pin 21/GPIO9    pin 25
    #    6     driver_3b   Driver 3 · B      IN3 pin 26/GPIO7    IN4 pin 24/GPIO8    pin 25
    #    7     driver_4a   Driver 4 · A      IN1 pin 15/GPIO22   IN2 pin 13/GPIO27   pin 14
    #    8     driver_4b   Driver 4 · B      IN3 pin 18/GPIO24   IN4 pin 16/GPIO23   pin 14
    #
    # Every motor starts uninverted. Run the raised-wheel test in
    # Debug -> Test outputs, and set `inverted` True on any motor that
    # turns the wrong way. Never fix direction in the drive math.
    # ------------------------------------------------------------------
    "motors": {
        1: {"name": "driver_1a", "forward_gpio": 26, "reverse_gpio": 19, "inverted": False},
        2: {"name": "driver_1b", "forward_gpio": 13, "reverse_gpio": 6, "inverted": False},
        3: {"name": "driver_2a", "forward_gpio": 21, "reverse_gpio": 20, "inverted": False},
        4: {"name": "driver_2b", "forward_gpio": 16, "reverse_gpio": 12, "inverted": False},
        5: {"name": "driver_3a", "forward_gpio": 11, "reverse_gpio": 9, "inverted": False},
        6: {"name": "driver_3b", "forward_gpio": 7, "reverse_gpio": 8, "inverted": False},
        7: {"name": "driver_4a", "forward_gpio": 22, "reverse_gpio": 27, "inverted": False},
        8: {"name": "driver_4b", "forward_gpio": 24, "reverse_gpio": 23, "inverted": False},
    },

    # ------------------------------------------------------------------
    # Sixteen servo outputs on one PCA9685 board.
    #
    # Five wires run from the Pi to the board, and they sit in one unbroken
    # run down the top of the header's left column, so it is a single bundle:
    #
    #     pin 1 / 3.3 V    -> VCC   logic power for the chip only (~10 mA)
    #     pin 3 / GPIO2    -> SDA   commands for all 16 outputs
    #     pin 5 / GPIO3    -> SCL   the clock those commands ride on
    #     pin 7 / GPIO4    -> OE    output enable, active low (see below)
    #     pin 9 / GND      -> GND   the reference SDA and SCL are measured against
    #
    # Pins 8 and 10 are the serial console and are deliberately left alone.
    #
    # V+ NEVER TOUCHES THE PI. The V+ header pin and the two-screw power
    # terminal are the same copper on this board, so the servo supply is
    # already present on that pin. Wiring it to a Pi 5 V pin would push the
    # whole servo rail - 12 V, in this build - straight into the Pi.
    # Feed V+ from its own regulated supply and join the negatives at the
    # common ground point instead.
    #
    # "channels" names each physical output on the board. `board` is the
    # index into "addresses" below. Each dictionary key is the 0-15 number
    # printed on the board unless an explicit "channel" value overrides it.
    # The default names match those printed numbers, so `servo_0` is the
    # channel labelled 0 on the board itself.
    #
    # OE is how MotionModule enables and disables the outputs. The board pulls
    # OE low by itself, so the outputs are enabled whenever the Pi is not
    # driving that pin - including through boot. That is safe because the
    # PCA9685 powers up with every channel off, but it does mean OE is an
    # enable line, not a substitute for the physical power cutoff.
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

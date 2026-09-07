"""Canonical Raspberry Pi 40-pin header mapping used by diagnostics and docs."""

PHYSICAL_BY_BCM = {
    0: 27,
    1: 28,
    2: 3,
    3: 5,
    4: 7,
    5: 29,
    6: 31,
    7: 26,
    8: 24,
    9: 21,
    10: 19,
    11: 23,
    12: 32,
    13: 33,
    14: 8,
    15: 10,
    16: 36,
    17: 11,
    18: 12,
    19: 35,
    20: 38,
    21: 40,
    22: 15,
    23: 16,
    24: 18,
    25: 22,
    26: 37,
    27: 13,
}

# Motor channels run straight down the drivers: 1/2 on Driver 1, 3/4 on
# Driver 2, and so on. Each driver's four inputs are grouped on the header.
DRIVER_ASSIGNMENTS = {
    1: (1, "A"),
    2: (1, "B"),
    3: (2, "A"),
    4: (2, "B"),
    5: (3, "A"),
    6: (3, "B"),
    7: (4, "A"),
    8: (4, "B"),
}
DRIVER_GROUNDS = {1: 39, 2: 34, 3: 25, 4: 14}

HEADER_FUNCTIONS = {
    1: "3.3 V", 2: "5 V", 3: "GPIO2 / SDA", 4: "5 V", 5: "GPIO3 / SCL",
    6: "GND", 7: "GPIO4", 8: "GPIO14 / TXD", 9: "GND", 10: "GPIO15 / RXD",
    11: "GPIO17", 12: "GPIO18", 13: "GPIO27", 14: "GND", 15: "GPIO22",
    16: "GPIO23", 17: "3.3 V", 18: "GPIO24", 19: "GPIO10 / MOSI", 20: "GND",
    21: "GPIO9 / MISO", 22: "GPIO25", 23: "GPIO11 / SCLK", 24: "GPIO8 / CE0",
    25: "GND", 26: "GPIO7 / CE1", 27: "GPIO0 / ID_SD", 28: "GPIO1 / ID_SC",
    29: "GPIO5", 30: "GND", 31: "GPIO6", 32: "GPIO12", 33: "GPIO13",
    34: "GND", 35: "GPIO19", 36: "GPIO16", 37: "GPIO26", 38: "GPIO20",
    39: "GND", 40: "GPIO21",
}

GROUND_ROLES = {
    6: "Available signal ground",
    9: "Servo controller logic ground",
    14: "Driver 4 signal ground",
    20: "Available signal ground",
    25: "Driver 3 signal ground",
    30: "Available signal ground",
    34: "Driver 2 signal ground",
    39: "Driver 1 signal ground",
}


def motor_rows(config) -> list[dict]:
    rows = []
    for motor in config.motors:
        driver, output = DRIVER_ASSIGNMENTS[motor.channel]
        rows.append(
            {
                "driver": driver,
                "ground_physical": DRIVER_GROUNDS[driver],
                "output": output,
                "motor": motor.channel,
                "name": motor.name,
                "in1_bcm": motor.forward_gpio,
                "in1_physical": PHYSICAL_BY_BCM[motor.forward_gpio],
                "in2_bcm": motor.reverse_gpio,
                "in2_physical": PHYSICAL_BY_BCM[motor.reverse_gpio],
                "inverted": motor.inverted,
            }
        )
    return rows


def header_rows(config) -> list[dict]:
    """Return every Pi header pin with its configured MotionModule role."""

    enabled = config.servos.enabled
    servo_state = "" if enabled else " (servos disabled)"
    roles: dict[int, tuple[str, str]] = {
        1: (f"PCA9685 VCC (3.3 V logic){servo_state}", "servo"),
        2: ("5 V — do not use for servo power", "power"),
        3: (f"PCA9685 SDA{servo_state}", "servo"),
        4: ("5 V — do not use for servo power", "power"),
        5: (f"PCA9685 SCL{servo_state}", "servo"),
        8: ("Reserved UART transmit — no MotionModule connection", "reserved"),
        10: ("Reserved UART receive — no MotionModule connection", "reserved"),
        17: ("3.3 V available", "power"),
        27: ("Reserved ID EEPROM — leave disconnected", "reserved"),
        28: ("Reserved ID EEPROM — leave disconnected", "reserved"),
    }
    motor_connections = motor_rows(config)
    active_drivers = {row["driver"] for row in motor_connections}
    details = {
        1: "Connect to PCA9685 VCC for 3.3 V logic only. The servo V+ rail has a separate regulated supply.",
        2: "Pi 5 V power rail. Not used by the reference harness; never connect the motor battery or servo V+ here.",
        3: "I2C data to PCA9685 SDA. All configured servo boards share this wire. Reserved for I2C even with servos disabled.",
        4: "Pi 5 V power rail. Not used by the reference harness; never connect the motor battery or servo V+ here.",
        5: "I2C clock to PCA9685 SCL. All configured servo boards share this wire. Reserved for I2C even with servos disabled.",
        9: "Connect to PCA9685 GND. This completes the five-wire bundle on pins 1-9 and gives SDA and SCL a reference. The servo supply negative joins common ground separately; its load current must not return through the Pi.",
        8: "GPIO14 is the UART TX signal. The default harness leaves it disconnected for serial access; no sensor is configured here.",
        10: "GPIO15 is the UART RX signal. The default harness leaves it disconnected for serial access; no sensor is configured here.",
        17: "Unused 3.3 V logic supply. Not a motor or servo power source.",
        27: "GPIO0 / ID_SD is the Raspberry Pi HAT identification EEPROM data pin. MotionModule rejects motor assignments here.",
        28: "GPIO1 / ID_SC is the Raspberry Pi HAT identification EEPROM clock pin. MotionModule rejects motor assignments here.",
    }
    configured_pins = {1, 3, 5, 9} if enabled else set()
    oe_gpio = config.servos.output_enable_gpio if enabled else None
    if oe_gpio is not None:
        oe_physical = PHYSICAL_BY_BCM.get(oe_gpio)
        if oe_physical is not None:
            roles[oe_physical] = (f"PCA9685 OE (output enable){servo_state}", "servo")
            details[oe_physical] = (
                f"GPIO{oe_gpio} drives the servo board's OE pad. OE is active low: MotionModule "
                "holds it low to enable all 16 outputs and drives it high to cut them, which works "
                "even if the I2C bus stops answering. The board pulls OE low on its own, so the "
                "outputs are enabled whenever the Pi is not driving this pin."
            )
            configured_pins.add(oe_physical)
    for physical, function in HEADER_FUNCTIONS.items():
        if function == "GND":
            roles[physical] = ("Available signal ground — not connected in reference harness", "ground")
            details.setdefault(physical, "Pi signal ground, currently unused. High-current motor and servo returns go to the power distribution ground.")
    if enabled:
        roles[9] = (f"Servo controller logic ground{servo_state}", "ground")
    for driver in active_drivers:
        physical = DRIVER_GROUNDS[driver]
        roles[physical] = (f"Driver {driver} signal ground", "ground")
        details[physical] = f"Connect to Driver {driver} signal ground. Connect its heavy power negative directly to the battery ground distribution, not through this Pi pin."
        configured_pins.add(physical)
    for row in motor_connections:
        label = f"{row['name']} · Driver {row['driver']}{row['output']}"
        roles[row["in1_physical"]] = (f"{label} IN1", "motor")
        roles[row["in2_physical"]] = (f"{label} IN2", "motor")
        for signal in ("in1", "in2"):
            physical = row[f"{signal}_physical"]
            details[physical] = (
                f"Connect to Driver {row['driver']}, output {row['output']}, {signal.upper()} for {row['name']} (motor {row['motor']}). "
                "This is a 3.3 V control signal, not a motor output. It carries direction and speed to the driver; the motor's own two wires go to that driver's output pair."
            )
            if row[f"{signal}_bcm"] in {7, 8, 9, 10, 11}:
                details[physical] += " Disable SPI before using this pin for the motor driver."
            if row[f"{signal}_bcm"] in {14, 15}:
                details[physical] += " Disable the serial console and any UART use of this pin first."
            configured_pins.add(physical)

    bcm_by_physical = {physical: bcm for bcm, physical in PHYSICAL_BY_BCM.items()}
    rows = []
    for physical in range(1, 41):
        role, category = roles.get(physical, ("Unused GPIO — no configured device", "unused"))
        function = HEADER_FUNCTIONS[physical]
        if function in {"3.3 V", "5 V"} and physical not in roles:
            category = "power"
        elif function == "GND" and physical not in roles:
            category = "ground"
        rows.append(
            {
                "physical": physical,
                "function": function,
                "role": role,
                "category": category,
                "bcm": bcm_by_physical.get(physical),
                "configured": physical in configured_pins,
                "connection": role,
                "detail": details.get(physical, "Not used by the active motor map. It can be claimed as a digital sensor with module.digital_input() when it is not otherwise reserved."),
            }
        )
    return rows


def servo_rows(config) -> list[dict]:
    """Return every named servo output with the board that carries it."""

    addresses = config.servos.addresses
    return [
        {
            "name": slot.name,
            "board": slot.board,
            "channel": slot.channel,
            "address": f"0x{addresses[slot.board]:02x}"
            if 0 <= slot.board < len(addresses)
            else "unconfigured",
        }
        for slot in config.servos.channels
    ]

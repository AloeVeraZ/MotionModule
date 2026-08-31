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

# The tested harness is intentionally not ordered by motor channel. Channels
# 1/2 live on Driver 2 while channels 3/4 live on Driver 1.
DRIVER_ASSIGNMENTS = {
    1: (2, "A"),
    2: (2, "B"),
    3: (1, "A"),
    4: (1, "B"),
    5: (3, "A"),
    6: (3, "B"),
    7: (4, "A"),
    8: (4, "B"),
}
DRIVER_GROUNDS = {1: 39, 2: 34, 3: 20, 4: 25}

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
    6: "Servo controller logic ground",
    20: "Driver 3 signal ground",
    25: "Driver 4 signal ground",
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

    roles: dict[int, tuple[str, str]] = {
        1: ("PCA9685 VCC (3.3 V logic)", "servo"),
        2: ("5 V — do not use for servo power", "power"),
        3: ("PCA9685 SDA", "servo"),
        4: ("5 V — do not use for servo power", "power"),
        5: ("PCA9685 SCL", "servo"),
        17: ("3.3 V available", "power"),
        27: ("Reserved ID EEPROM — leave disconnected", "reserved"),
        28: ("Reserved ID EEPROM — leave disconnected", "reserved"),
    }
    for physical, role in GROUND_ROLES.items():
        roles[physical] = (role, "ground")
    for row in motor_rows(config):
        roles[row["in1_physical"]] = (
            f"Driver {row['driver']} {row['output']} IN1 · Motor {row['motor']}", "motor"
        )
        roles[row["in2_physical"]] = (
            f"Driver {row['driver']} {row['output']} IN2 · Motor {row['motor']}", "motor"
        )

    rows = []
    for physical in range(1, 41):
        role, category = roles.get(physical, ("Available / not assigned", "unused"))
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
            }
        )
    return rows

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


def motor_rows(config) -> list[dict]:
    rows = []
    for motor in config.motors:
        driver = (motor.channel - 1) // 2 + 1
        output = "A" if motor.channel % 2 else "B"
        rows.append(
            {
                "driver": driver,
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


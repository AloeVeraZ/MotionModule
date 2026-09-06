"""Bundled build reference for the dashboard; works without a GitHub connection.

Part selections come from BOM.md and the reference harness from docs/PINOUT.md.
Live names, GPIOs, board addresses and enabled state come from ModuleConfig.
This describes configured wiring, never an inventory of detected motors/servos.
"""

from __future__ import annotations

from .pinout import motor_rows, servo_rows


def _part(quantity, name, selection, purpose, status="required", url=None):
    return {
        "quantity": quantity, "name": name, "selection": selection,
        "purpose": purpose, "status": status, "url": url,
    }


def parts_groups() -> list[dict]:
    """The complete reference BOM, including unspecified purchasing choices."""

    return [
        {
            "id": "controllers", "title": "Controller & control boards", "items": [
                _part("1", "Raspberry Pi 5", "40-pin GPIO header; 4 GB is sufficient", "Runs robot code, the dashboard and network", "selected"),
                _part("1", "microSD card", "32 GB or larger; A2 recommended", "Stores Raspberry Pi OS, runtime and robot projects"),
                _part("1", "Pi 5 cooler or fan case", "Active cooling", "Prevents thermal throttling", url="https://www.raspberrypi.com/products/active-cooler/"),
                _part("4", "GODIYMODULES dual H-bridge", "DC 3–18 V dual PWM motor driver", "Two brushed motors per board; eight channels total", "selected", "https://www.amazon.com/dp/B0FKH352D2"),
                _part("1 installed", "AITRIP PCA9685", "16-channel servo board from the two-board pack; default address 0x40", "Converts two I2C signal wires into 16 servo control signals", "selected", "https://www.amazon.com/dp/B07WS5XY63"),
                _part("1 spare / optional", "Second PCA9685", "The other board from the pack; change its address before connecting", "Optional 16 extra servo outputs; not part of the default configuration", "optional"),
            ],
        },
        {
            "id": "power", "title": "Motors, servos & power", "items": [
                _part("Up to 8", "Brushed DC gearmotors", "Exact model, voltage and stall current not recorded", "Match battery voltage and the driver operating range", "needs_spec"),
                _part("As needed", "Hobby servos", "Exact model, quantity, voltage and stall current not recorded", "Connect to outputs 0–15 on the servo board", "needs_spec"),
                _part("1", "Robot battery", "Choose after motor and total-load measurements", "Supplies the motor rail and regulators", "needs_spec"),
                _part("1", "Pi power converter", "Stable Pi-rated 5 V supply with protected USB-C connection", "Powers the Pi independently of motor/servo load changes", "needs_spec"),
                _part("1", "Servo BEC / regulator", "Normally 5–6 V, matched to every connected servo; current rating still required", "Separate servo V+ power rail", "needs_spec"),
                _part("1", "Main fuse or circuit breaker", "Size below battery, connector, wire and distribution limits", "Protects the main power path", "needs_spec"),
                _part("4", "Motor-driver branch fuses", "Size from motor stall current and branch ratings", "One protected battery branch per dual driver", "needs_spec"),
                _part("1", "Main switch / physical cutoff", "DC-rated for the robot battery and maximum load", "Disconnects robot power physically"),
                _part("1", "Power distribution block", "Separate fused Pi, servo and motor branches", "Distributes power without carrying load current through Pi pins"),
            ],
        },
        {
            "id": "wiring", "title": "Wiring & protection", "items": [
                _part("16", "10 kΩ pull-down resistors", "One at every H-bridge input, to signal ground", "Holds motor commands low while the Pi boots"),
                _part("1 set", "40-pin GPIO harness / breakout", "Physical pin labels and strain relief", "Connects the Pi to driver signals"),
                _part("4 sets", "Driver signal connectors", "Four signals plus a low-current ground reference per board", "Connects both motor channels on each driver"),
                _part("8 sets", "Motor output connectors", "Rated two-wire connection per motor", "Connects each motor to its own output pair"),
                _part("As needed", "Motor and battery wire", "Stranded copper sized for stall/fault current and length", "Carries high-current power", "needs_spec"),
                _part("As needed", "Servo extensions / distribution", "Rated for combined servo current", "Distributes V+, GND and each servo signal", "needs_spec"),
                _part("As needed", "Signal wire", "Stranded 22–26 AWG is typical for short GPIO/I2C runs", "Carries low-current control signals"),
                _part("1 set", "Common-ground distribution", "Planned connection between all supply negatives and signal grounds", "Gives control signals a shared voltage reference"),
                _part("As needed", "Terminations & strain relief", "Ferrules, heat-shrink, loom and secure connectors", "Prevents shorts, loose strands and pulled wires"),
                _part("4", "Driver cooling provisions", "Heatsinks or directed airflow as indicated by heat testing", "Manages motor-driver temperature"),
            ],
        },
        {
            "id": "tools", "title": "Tools for setup", "items": [
                _part("1", "Digital multimeter", "Continuity and DC-voltage modes", "Verifies pin-to-pin wiring and regulator voltage"),
                _part("1 if available", "Current-limited bench supply", "Appropriate voltage and current range", "Helps with first electrical tests", "optional"),
                _part("1 set", "Crimp tool & terminals", "Match the chosen connectors", "Makes secure electrical connections"),
                _part("1", "Robot stand", "Stable support with every wheel off the floor", "Holds the robot during motor tests"),
                _part("1 set", "Hand tools & fuses", "Small screwdrivers, wire stripper and fuse assortment", "Assembly and commissioning"),
            ],
        },
    ]


def hardware_guide(config) -> dict:
    """Build a display-ready guide for the actual active configuration."""

    motors = motor_rows(config)
    slots = {(row["board"], row["channel"]): row["name"] for row in servo_rows(config)}
    servo = config.servos
    logic_connections = [
        {"label": "SDA · data", "from": "Pi physical 3 / GPIO2", "to": "PCA9685 SDA", "purpose": "Carries commands for all 16 outputs over I2C."},
        {"label": "SCL · clock", "from": "Pi physical 5 / GPIO3", "to": "PCA9685 SCL", "purpose": "Times the I2C communication; shared by every configured board."},
        {"label": "VCC · logic power", "from": "Pi physical 1 / 3.3 V", "to": "PCA9685 VCC", "purpose": "Powers only the control chip; it does not power the servos."},
        {"label": "GND · logic reference", "from": "Pi physical 6 / GND", "to": "PCA9685 GND", "purpose": "Provides a common reference for the data and clock signals."},
    ]
    servo_connections = [
        {"label": "V+ · servo power", "from": "Separate regulated servo supply +", "to": "PCA9685 V+ screw terminal", "purpose": "Feeds the power pin on all 16 output headers. Set voltage for your servo model before connecting."},
        {"label": "GND · servo return", "from": "Servo regulator negative / common ground", "to": "PCA9685 power-terminal GND", "purpose": "Returns servo current to its supply, not through a Pi ground wire."},
        {"label": "OE · output enable", "from": "Board enable circuit; no Pi GPIO assigned", "to": "PCA9685 OE", "purpose": "Active low: low enables PWM; high disables the signals. MotionModule does not control OE. Verify the fitted board's pull-down; do not leave OE floating or treat it as a power cutoff."},
        {"label": "A0–A5 · address pads", "from": "Board solder pads", "to": "Configured I2C address", "purpose": "Default 0x40 has all pads open. Each extra board needs a unique address, matching hardware.py."},
        {"label": "Side headers · chaining", "from": "Existing board SDA / SCL / VCC / GND", "to": "Next board with a unique address", "purpose": "Repeated labels are the same electrical nets, not extra Pi pins. Size servo power separately; do not daisy-chain bank current through thin leads."},
    ]
    boards = []
    for index, address in enumerate(servo.addresses):
        closed = [f"A{bit}" for bit in range(6) if (address - 0x40) & (1 << bit)]
        boards.append({
            "index": index,
            "label": f"Servo board {index + 1}",
            "address": f"0x{address:02x}",
            "enabled": servo.enabled,
            "frequency_hz": servo.frequency_hz,
            "address_pads": "Close " + ", ".join(closed) + "; leave other pads open" if closed else "All A0–A5 pads open",
            "outputs": [
                {
                    "channel": channel,
                    "name": slots.get((index, channel)),
                    "configured": (index, channel) in slots,
                    "signal": f"PWM signal {channel}",
                    "power": "V+ · regulated servo supply",
                    "ground": "GND · servo supply return",
                }
                for channel in range(16)
            ],
        })
    return {
        "reference": "MotionModule reference build · BOM.md + docs/PINOUT.md",
        "summary": "Eight motor channels and sixteen servo outputs in the reference build. The Pi header map shows controller connections; the servo output headers are on the PCA9685 board.",
        "capacity": {"motors": 8, "servos_per_board": 16, "configured_motors": len(motors), "configured_servo_boards": len(boards), "servo_enabled": servo.enabled},
        "inventory_note": "Parts below describe the reference build, not detected inventory. Exact motor, servo and power component models still need to be recorded. No sensors are implemented.",
        "parts_groups": parts_groups(),
        "missing_specs": [
            {"name": "Motor model & load", "needed": "Record rated voltage and stall current for each motor."},
            {"name": "Servo model & quantity", "needed": "Record voltage, pulse range, behavior and stall current for each servo."},
            {"name": "Battery & power protection", "needed": "Record battery chemistry/voltage/discharge rating, regulator ratings, fuse sizes and wire/connector limits."},
        ],
        "wiring": {
            "summary": "Four Pi connections serve the PCA9685 logic: two signals, 3.3 V and ground. The board then provides 16 separate three-pin servo outputs; servo power arrives from another supply.",
            "motor_connections": motors,
            "logic_connections": logic_connections,
            "servo_connections": servo_connections,
            "servo_boards": boards,
            "power_domains": [
                {"name": "Pi logic", "source": "Pi-rated 5 V supply / converter", "destination": "Pi USB-C power input", "note": "Separate supply branch; the Pi header is for logic connections."},
                {"name": "Motor power", "source": "Robot battery through main cutoff and fuses", "destination": "Each H-bridge power input", "note": "Heavy positive and negative wires go to power distribution. Use one motor per output pair."},
                {"name": "Servo power", "source": "Regulated supply matched to your servos", "destination": "PCA9685 V+ and power GND", "note": "Normally 5–6 V; size from simultaneous servo current. V+ must never connect to Pi VCC or a header power pin."},
            ],
            "notes": [
                "Use physical pin numbers to locate the connector, and BCM/GPIO numbers in hardware.py. They are different numbering systems.",
                "Pins 27/28 belong to the Pi ID EEPROM interface and must stay disconnected. Default UART pins 8/10 are left for serial use. Unused GPIO pins have no configured sensor or device.",
                "Every motor input needs a 10 kΩ pull-down at the driver. SPI must be disabled for the reference GPIO7/8/9/11 motor connections.",
                "Join all supply negatives at a planned common-ground point. Motor and servo load currents return directly to their supplies.",
                "Use the labels printed on your servo board and the servo connector specification to orient signal, V+ and GND. Header diagrams show function, not physical board orientation.",
                "I2C can verify the controller chip responds; it cannot detect an attached servo. Motor drivers and motors also provide no attachment feedback.",
            ],
        },
        "checklist": [
            {"title": "Start with actuator power off", "detail": "Disconnect the motor battery and servo supply before moving wires."},
            {"title": "Match every connection", "detail": "Check BCM and physical numbers, each motor's two inputs, common ground and pull-down resistors with a meter."},
            {"title": "Check the power rails", "detail": "Set servo regulator voltage before attaching servos. Keep motor battery and V+ away from Pi header pins."},
            {"title": "Power the Pi and run checks", "detail": "Open Checks & logs and run MotionModule Doctor. Verify the configured I2C board addresses respond."},
            {"title": "Test one output at a time", "detail": "Raise every wheel, keep the physical cutoff in reach, then use Debug motor and servo tests. Choose the actual servo's behavior and pulse limits."},
            {"title": "Name it and use it", "detail": "Label the physical mechanism, edit its name in hardware.py, deploy and confirm the name in this wiring guide."},
        ],
        "glossary": [
            {"term": "Physical pin", "meaning": "Position 1–40 on the Pi connector. Use this to find where a wire goes."},
            {"term": "BCM / GPIO", "meaning": "The Pi's software signal number. GPIO12 is physical pin 32."},
            {"term": "H-bridge", "meaning": "A motor driver that lets a brushed motor turn in either direction. Each selected board has outputs A and B."},
            {"term": "PWM", "meaning": "A repeating control signal. Motors use its duty cycle for power; servos use its pulse width for their commanded behavior."},
            {"term": "I2C address", "meaning": "A board's identity on the shared data and clock wires. The first PCA9685 defaults to 0x40."},
            {"term": "VCC vs V+", "meaning": "VCC is 3.3 V controller logic in this build. V+ is the separate power rail for the servo motors."},
            {"term": "Reserved", "meaning": "Kept for a named interface, such as ID EEPROM or UART; it does not mean an attached sensor has been detected."},
            {"term": "Configured vs detected", "meaning": "Configured means named in software. Only feedback-capable devices such as the I2C controller can report a response."},
        ],
        "sources": [
            {"title": "Reference parts", "url": "https://github.com/AloeVeraZ/MotionModule/blob/main/BOM.md"},
            {"title": "Reference pinout", "url": "https://github.com/AloeVeraZ/MotionModule/blob/main/docs/PINOUT.md"},
            {"title": "PCA9685 chip datasheet", "url": "https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf"},
            {"title": "PCA9685 connector reference", "url": "https://learn.adafruit.com/16-channel-pwm-servo-driver/pinouts"},
        ],
    }

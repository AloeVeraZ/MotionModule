"""Bundled build reference for the dashboard; works without a GitHub connection.

Part selections come from BOM.md and the reference harness from docs/PINOUT.md.
Live names, GPIOs, board addresses and enabled state come from ModuleConfig.
This describes configured wiring, never an inventory of detected motors/servos.
"""

from __future__ import annotations

from .pinout import PHYSICAL_BY_BCM, motor_rows, servo_rows


# CAD for the controller stack and the power module lives in the repository.
CAD_REPO = "https://github.com/AloeVeraZ/MotionModule/tree/main/cad"


def _part(quantity, name, selection, purpose, status="required", url=None):
    return {
        "quantity": quantity, "name": name, "selection": selection,
        "purpose": purpose, "status": status, "url": url,
    }


def parts_groups() -> list[dict]:
    """The reference build.

    The first two groups are the robot: buy those and MotionModule runs.
    Everything after them is what actually moves, plus the wire to join it
    up, and those are recommendations rather than a required list.
    """

    return [
        {
            "id": "controllers", "title": "Controller & control boards",
            "requirement": "required",
            "items": [
                _part("1", "Raspberry Pi 5", "40-pin GPIO header; 4 GB is sufficient", "Runs robot code, the dashboard and network", "selected"),
                _part("1", "microSD card", "32 GB or larger; A2 recommended", "Stores Raspberry Pi OS, runtime and robot projects"),
                _part("1", "Argon THRML 30mm active cooler", "Recommended Pi 5 cooler", "Prevents thermal throttling", "selected", "https://argon40.com/products/argon-thrml-30mm-active-cooler"),
                _part("4", "GODIYMODULES dual H-bridge", "DC 3-18 V dual PWM motor driver", "Two brushed motors per board; eight channels total", "selected", "https://www.amazon.com/dp/B0FKH352D2"),
                _part("1", "AITRIP PCA9685", "16-channel servo board, address 0x40 with all pads open", "Turns two I2C wires into 16 servo control signals", "selected", "https://www.amazon.com/dp/B07WS5XY63"),
                _part("1 set", "Controller mounting CAD", "Printable mounts for the Pi, drivers and servo board", "Holds the boards together as one assembly", "placeholder", CAD_REPO),
            ],
            "note": "These five boards plus the power group are the whole controller. With them wired up, MotionModule boots, serves this dashboard and drives outputs.",
        },
        {
            "id": "power", "title": "Power module",
            "requirement": "required",
            "items": [
                _part("1", "12 V battery - goBILDA NiMH", "12 V, 3000 mAh, XT30 connector", "Powers the whole robot. Already fused, so there is no separate breaker to buy", "selected", "https://www.gobilda.com/12v-nimh-nested-battery-3000mah-mh-fc-xt30-connector/"),
                _part("or", "12 V battery - REV Slim", "12 V, 3000 mAh, XT30, with an inline 20 A replaceable ATM fuse", "The other battery in use; same job, same connector", "selected", "https://www.revrobotics.com/rev-31-1302/"),
                _part("1 pack", "XT30 pigtails", "Male and female XT30 leads on silicone wire", "Mates the battery's XT30 and gives bare wire for the Wago joins", "selected", "https://www.amazon.com/dp/B0FY2ZCR83"),
                _part("1", "12 V to 5 V USB-C converter", "Steps the 12 V rail down to a Pi-rated 5 V USB-C supply", "Powers the Raspberry Pi independently of motor load", "selected", "https://www.amazon.com/dp/B0FD735LFG"),
                _part("1", "Rocker switch", "KCD1 automotive rocker switch, DC rated", "The battery module's physical on/off cutoff", "selected", "https://www.amazon.com/DaierTek-Listed-Switches-Automotive-KCD1-5Pack/dp/B07S1MV462"),
                _part("1", "12 V/24 V to 5 V 5 A buck converter", "PlusRoc waterproof buck converter, fixed 5 V output, 5 A / 25 W max, open-wire leads, sold as a 2-pack", "Steps the 12 V battery rail down for the PCA9685 servo V+ terminal, which is rated 3.3-6 V", "selected", "https://www.amazon.com/dp/B0FYNCSV2Z"),
                _part("1 set", "Power module CAD", "Enclosure and mounting for the battery, switch and converters", "Holds the power side together as one assembly", "placeholder", CAD_REPO),
            ],
            "note": "One 12 V battery runs everything. Both batteries above ship with their own fuse, so no separate fuse or breaker is needed. The drivers take 12 V directly and the Pi gets 5 V from the USB-C converter. The servo rail is stepped down on the power module itself, by the buck converter above: the PCA9685 V+ terminal is rated 3.3-6 V, and the servos on it top out around 8.4 V, so 12 V must never reach that terminal. 5 V/5 A is 25 W total for every servo moving at once - size your servo load against that.",
        },
        {
            "id": "actuators", "title": "Motors & servos",
            "requirement": "recommended",
            "items": [
                _part("Up to 8", "Brushed DC motors", "goBILDA Yellow Jacket planetary gear motors are what we run. Any brushed DC motor rated for 12 V works", "Two motors per driver board, eight in total", "selected", "https://www.gobilda.com/yellow-jacket-planetary-gear-motors"),
                _part("Up to 8", "3.5 mm bullet lead, MH-FC to bare wire", "goBILDA GB-3800-0013-0300, 300 mm, 16 AWG", "Bullets plug straight onto the motor; the bare end screws into the driver's terminal block", "selected", "https://www.gobilda.com/3-5mm-bullet-lead-mh-fc-300mm-length/"),
                _part("Up to 16", "Axon Mini MK2 servo", "The servo we recommend. Any Axon servo is a step up: programmable range, mode and centring", "One per PCA9685 output", "selected", "https://www.gobilda.com/axon-mini-servo-mk2/"),
                _part("Alternative", "Standard three-pin servos", "Any standard 3-pin hobby servo works; match its voltage to the servo rail", "Drop-in alternative to the Axon", "optional", "https://www.gobilda.com/standard-size-servos"),
            ],
            "note": "Recommendations, not requirements. The controller runs without any of this; these are the parts known to work well on it.",
        },
        {
            "id": "pi-i2c-sensors", "title": "Pi-connected BNO055 IMU",
            "requirement": "recommended",
            "items": [
                _part("1", "BNO055 9-axis IMU breakout", "Teyleten Robot BNO055 module", "Heading, tilt and turn rate, read directly by the Pi", "selected", "https://www.amazon.com/Teyleten-Robot-Attitude-Acceleration-Geomagnetic/dp/B0D47G672B/"),
            ],
            "note": "The Mecanum IMU uses motion_module.pi_imu.LocalIMU on the independent i2c-gpio bus: VIN to physical pin 17, GND to 20, SDA to 11, SCL to 12 and AD0 to 6. Follow Debug > Wiring for the complete board guide and overlay setup. The robot can drive without heading when the IMU is absent.",
        },
        {
            "id": "sensors", "title": "Optional USB GPIO expansion",
            "requirement": "optional",
            "items": [
                _part("Optional", "Arduino GIGA R1 WiFi", "ABX00063, USB-C data cable to the Pi", "Extra GPIO inputs for future sensors; firmware and USB auto-detection are included", "optional", "https://store-usa.arduino.cc/products/giga-r1-wifi"),
            ],
            "note": "Experimental extra, not part of the Mecanum setup; verify it with your own hardware. No additional sensors are declared. The Python GigaPin API reads digital and analog inputs; GPIO takes 3.3 V maximum. Firmware targets GIGA R1 WiFi, not Uno or Mega. The reference BNO055 stays on the Pi.",
        },
        {
            "id": "wiring", "title": "Wiring",
            "requirement": "recommended",
            "items": [
                _part("As needed", "16 AWG silicone wire", "Haerkn 16 AWG silicone wire, two cores (red and black), tinned copper, 25 ft", "Carries the 12 V battery and motor current, up to the 10 A each driver draws", "selected", "https://www.amazon.com/dp/B07RRPFL3Q"),
                _part("As needed", "Jumper wires", "Multicoloured breadboard jumper set; female-to-female for the Pi header", "Carries the Pi's control signals to each driver and to the servo board", "selected", "https://www.amazon.com/Elegoo-EL-CP-004-Multicolored-Breadboard-arduino/dp/B01EV70C78"),
                _part("As needed", "Wago 221 lever connectors", "Compact splicing connectors used for every 12 V power join", "Branches the battery rail to the drivers and regulators without soldering", "selected", "https://www.amazon.com/221-2401-Compact-Splicing-Inline-Connectors/dp/B0BT8DHLJJ"),
            ],
            "note": "Signals are ordinary jumper wires from the Pi header; every 12 V and motor run is 16 AWG silicone wire, and every 12 V join is a Wago connector. Nothing else is needed - the boards, motors and servos come with their own leads.",
        },
        {
            "id": "tools", "title": "Tools for setup",
            "requirement": "recommended",
            "items": [
                _part("1", "Digital multimeter", "Continuity and DC-voltage modes", "Verifies pin-to-pin wiring and regulator voltage"),
                _part("1 if available", "Current-limited bench supply", "Appropriate voltage and current range", "Helps with first electrical tests", "optional"),
                _part("1", "Robot stand", "Stable support with every wheel off the floor", "Holds the robot during motor tests"),
                _part("1 set", "Hand tools", "Small screwdrivers and a wire stripper", "Assembly and commissioning"),
            ],
        },
    ]


def hardware_guide(config) -> dict:
    """Build a display-ready guide for the actual active configuration."""

    motors = motor_rows(config)
    slots = {(row["board"], row["channel"]): row["name"] for row in servo_rows(config)}
    servo = config.servos
    oe_gpio = servo.output_enable_gpio
    oe_physical = PHYSICAL_BY_BCM.get(oe_gpio) if oe_gpio is not None else None
    logic_connections = [
        {"label": "VCC · logic power", "from": "Pi physical 1 / 3.3 V", "to": "PCA9685 VCC",
         "purpose": "Powers only the PCA9685 chip, about 10 mA. It does not power a single servo."},
        {"label": "SDA · data", "from": "Pi physical 3 / GPIO2", "to": "PCA9685 SDA",
         "purpose": "Carries commands for all 16 outputs, and is how the dashboard knows whether the board is there at all: an answer on this bus is what turns the servo status green. Fixed by the Pi's hardware I2C; it cannot be moved."},
        {"label": "SCL · clock", "from": "Pi physical 5 / GPIO3", "to": "PCA9685 SCL",
         "purpose": "Times that data. Also fixed by the Pi's hardware I2C, and shared by every board on the bus."},
    ]
    if oe_physical is not None:
        logic_connections.append(
            {"label": "OE · output enable", "from": f"Pi physical {oe_physical} / GPIO{oe_gpio}", "to": "PCA9685 OE",
             "purpose": "Enables and disables all 16 outputs at once. Active low: MotionModule holds it low to enable, and drives it high to cut every output in hardware, which still works if the I2C bus has stopped answering. The board pulls OE low by itself, so the outputs are enabled whenever the Pi is not driving this pin - it is an enable line, not the power cutoff."}
        )
    logic_connections.append(
        {"label": "GND · shared reference", "from": "Pi physical 9 / GND", "to": "PCA9685 GND",
         "purpose": "The one ground wire the Pi needs, and it closes the run: pins 1, 3, 5, 7 and 9 are five in a row down the left column, so this is a single bundle. It gives SDA, SCL and OE something to measure against. Pins 8 and 10 stay free for the serial console."}
    )
    servo_connections = [
        {"label": "V+ · screw terminal", "from": "Servo regulator positive", "to": "PCA9685 V+ terminal",
         "purpose": "The only supply that moves servos, feeding the middle contact of all 16 outputs. The board itself will take up to 12 V here, but every servo plugged into it sees this voltage directly, and hobby servos want 5-6 V while an Axon Mini MK2 tops out at 8.4 V. Give it the stepped-down rail, not the 12 V battery."},
        {"label": "GND · screw terminal", "from": "Servo regulator negative", "to": "PCA9685 power-terminal GND",
         "purpose": "Returns servo current to its own supply. Join it to the common ground point, never through the Pi's ground wire."},
        {"label": "V+ · header pin", "from": "Nothing — already fed by the screw terminal", "to": "PCA9685 V+ header pin",
         "purpose": "This is the one pin on the board that must not go to the Pi. It is the same copper as the screw terminal, so the servo rail is already sitting on it; the pin exists to pass that rail on to another board. Wiring it to a Pi 5 V pin would connect the servo supply - 12 V in this build - straight to the Pi's 5 V rail."},
        {"label": "A0–A5 · address pads", "from": "Solder pads on the board", "to": "Its I2C address",
         "purpose": "All open gives 0x40, which is what hardware.py expects. Only close pads if you add a second board that needs a different address."},
        {"label": "Side headers · chaining", "from": "This board's SDA / SCL / VCC / GND", "to": "A second board with a unique address",
         "purpose": "The repeated labels along the edges are the same four nets again, for daisy-chaining. They are not extra Pi pins, and each added board still needs its own servo power."},
        {"label": "16 outputs · three contacts each", "from": "PCA9685 output header", "to": "One servo per column",
         "purpose": "Signal from the chip, V+ from the screw terminal, GND from the same supply. Follow the board's printed labels, not wire colour."},
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
        "inventory_note": "Parts below describe the reference build, not detected inventory. The controller and power groups are what the robot needs; motors, servos, sensors and wire are recommendations. The reference BNO055 connects directly to the Pi; Arduino GIGA R1 WiFi USB GPIO expansion is an experimental extra.",
        "parts_groups": parts_groups(),
        "missing_specs": [
            {"name": "CAD files", "needed": "The controller and power-module CAD folders in the repository are still being filled in."},
        ],
        "wiring": {
            "summary": "Four wires reach the Pi and that is all: 3.3 V, ground, SDA and SCL. Every other terminal on the board either belongs to the separate servo supply, is a chaining duplicate, or is left alone. The 16 servo outputs live on the board, not on Pi pins.",
            "motor_connections": motors,
            "logic_connections": logic_connections,
            "servo_connections": servo_connections,
            "servo_boards": boards,
            "power_domains": [
                {"name": "Pi logic", "source": "12 V battery through the 12 V to 5 V USB-C converter", "destination": "Pi USB-C power input", "note": "Separate supply branch; the Pi header is for logic connections only."},
                {"name": "Motor power", "source": "12 V battery through main cutoff and fuses", "destination": "Each H-bridge power input", "note": "12 V sits inside the driver's 3-18 V range. Wago 221 connectors branch the rail. Use one motor per output pair."},
                {"name": "Servo power", "source": "Regulated supply matched to your servos", "destination": "PCA9685 V+ and power GND", "note": "Normally 5–6 V; size from simultaneous servo current. V+ must never connect to Pi VCC or a header power pin."},
            ],
            "notes": [
                "Use physical pin numbers to locate the connector, and BCM/GPIO numbers in hardware.py. They are different numbering systems.",
                "Pins 27/28 belong to the Pi ID EEPROM interface and must stay disconnected. Default UART pins 8/10 are left for serial use. Unused GPIO pins have no configured sensor or device.",
                "SPI must be disabled for the reference GPIO7/8/9/11 motor connections.",
                "Yellow Jacket motor leads end in 3.5 mm FH-MC bullets, so the mating lead is the MH-FC one; its bare end goes straight into the driver's screw terminals. goBILDA's JST VH adaptor is for a REV Expansion Hub and is not used here. Swapping which bullet goes to which terminal reverses that motor, but set direction with `inverted` in hardware.py instead.",
                "Pi GPIO pins are inputs until Linux starts, so keep motor power switched off through boot and confirm nothing moves before trusting the outputs.",
                "Join all supply negatives at a planned common-ground point. Motor and servo load currents return directly to their supplies.",
                "Use the labels printed on your servo board and the servo connector specification to orient signal, V+ and GND. Header diagrams show function, not physical board orientation.",
                "I2C can verify the controller chip responds; it cannot detect an attached servo. Motor drivers and motors also provide no attachment feedback.",
            ],
        },
        "checklist": [
            {"title": "Start with actuator power off", "detail": "Disconnect the motor battery and servo supply before moving wires."},
            {"title": "Match every connection", "detail": "Check BCM and physical numbers, each motor's two inputs and the common ground with a meter."},
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

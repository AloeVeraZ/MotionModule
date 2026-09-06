import unittest
from dataclasses import replace
from pathlib import Path

from motion_module.config import ServoSlot, default_config
from motion_module.hardware_guide import hardware_guide
from motion_module.pinout import header_rows


class HardwareGuideTests(unittest.TestCase):
    def setUp(self):
        self.config = default_config()

    def test_every_pin_has_a_specific_role_and_inspectable_explanation(self):
        pins = header_rows(self.config)
        self.assertEqual([pin["physical"] for pin in pins], list(range(1, 41)))
        self.assertTrue(all(pin["role"] and pin["detail"] for pin in pins))
        self.assertEqual({pin["physical"] for pin in pins if pin["category"] == "reserved"}, {8, 10, 27, 28})
        self.assertIn("ID EEPROM", pins[26]["role"])
        self.assertIn("UART", pins[7]["role"])
        self.assertIsNone(pins[0]["bcm"])
        self.assertEqual(pins[31]["bcm"], 12)
        self.assertTrue(pins[5]["configured"])
        self.assertIn("Servo controller", pins[5]["role"])

    def test_header_follows_custom_pins_and_only_configured_driver_grounds(self):
        motor = replace(self.config.motors[0], name="intake", forward_gpio=14)
        config = replace(self.config, motors=(motor,))
        pins = header_rows(config)
        self.assertEqual(pins[7]["category"], "motor")
        self.assertIn("intake", pins[7]["role"])
        self.assertIn("serial console", pins[7]["detail"])
        self.assertEqual(pins[31]["category"], "unused")
        self.assertFalse(pins[38]["configured"])
        self.assertNotIn("Driver 1", pins[38]["role"])
        self.assertTrue(pins[33]["configured"])

    def test_disabled_servos_keep_i2c_reserved_without_claiming_active_wiring(self):
        config = replace(self.config, servos=replace(self.config.servos, enabled=False))
        pins = header_rows(config)
        for physical in (1, 3, 5, 6):
            self.assertFalse(pins[physical - 1]["configured"])
            self.assertIn("disabled", pins[physical - 1]["role"])
        guide = hardware_guide(config)
        self.assertFalse(guide["capacity"]["servo_enabled"])
        self.assertFalse(guide["wiring"]["servo_boards"][0]["enabled"])

    def test_servo_headers_are_separate_from_four_pi_logic_connections(self):
        guide = hardware_guide(self.config)
        self.assertEqual(len(guide["wiring"]["logic_connections"]), 4)
        outputs = guide["wiring"]["servo_boards"][0]["outputs"]
        self.assertEqual([output["channel"] for output in outputs], list(range(16)))
        for output in outputs:
            self.assertIn("PWM", output["signal"])
            self.assertIn("V+", output["power"])
            self.assertIn("GND", output["ground"])
        labels = {row["label"] for row in guide["wiring"]["servo_connections"]}
        self.assertIn("OE · output enable", labels)
        self.assertIn("A0–A5 · address pads", labels)

    def test_custom_board_addresses_and_partial_names_render_all_physical_outputs(self):
        servo = replace(
            self.config.servos,
            addresses=(0x40, 0x43),
            channels=(ServoSlot("claw", 1, 3),),
        )
        boards = hardware_guide(replace(self.config, servos=servo))["wiring"]["servo_boards"]
        self.assertEqual(len(boards), 2)
        self.assertEqual(boards[1]["address"], "0x43")
        self.assertEqual(boards[1]["address_pads"], "Close A0, A1; leave other pads open")
        self.assertEqual(boards[1]["outputs"][3]["name"], "claw")
        self.assertTrue(boards[1]["outputs"][3]["configured"])
        self.assertIsNone(boards[1]["outputs"][0]["name"])
        self.assertFalse(boards[1]["outputs"][0]["configured"])
        self.assertEqual(len(boards[0]["outputs"]), 16)

    def test_bom_selected_boards_match_repository_and_missing_models_are_explicit(self):
        guide = hardware_guide(self.config)
        bom = Path(__file__).resolve().parents[1].joinpath("BOM.md").read_text(encoding="utf-8")
        parts = [part for group in guide["parts_groups"] for part in group["items"]]
        for product_id in ("B0FKH352D2", "B07WS5XY63"):
            self.assertIn(product_id, bom)
            self.assertTrue(any(product_id in (part["url"] or "") for part in parts))
        unspecified = {part["name"] for part in parts if part["status"] == "needs_spec"}
        self.assertTrue({"Brushed DC gearmotors", "Hobby servos", "Robot battery"}.issubset(unspecified))
        self.assertIn("not detected inventory", guide["inventory_note"])
        self.assertIn("No sensors", guide["inventory_note"])


if __name__ == "__main__":
    unittest.main()

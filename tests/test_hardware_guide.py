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
        # Both UART pins stay free for the serial console.
        self.assertIn("UART", pins[9]["role"])
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
        self.assertEqual(pins[35]["category"], "unused")
        self.assertTrue(pins[38]["configured"])
        self.assertIn("Driver 1", pins[38]["role"])
        self.assertFalse(pins[33]["configured"])

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

    def test_every_selected_part_is_linked_and_also_listed_in_the_repository_bom(self):
        guide = hardware_guide(self.config)
        bom = Path(__file__).resolve().parents[1].joinpath("BOM.md").read_text(encoding="utf-8")
        parts = [part for group in guide["parts_groups"] for part in group["items"]]
        linked = [part for part in parts if part["url"] and part["status"] == "selected"]
        self.assertGreaterEqual(len(linked), 8)
        for part in linked:
            self.assertIn(part["url"].rstrip("/").rsplit("/", 1)[-1], bom, part["name"])
        self.assertIn("not detected inventory", guide["inventory_note"])
        self.assertIn("No sensors", guide["inventory_note"])

    def test_the_two_required_groups_come_first_and_the_rest_are_advice(self):
        groups = hardware_guide(self.config)["parts_groups"]
        self.assertEqual(
            [group["id"] for group in groups],
            ["controllers", "power", "actuators", "wiring", "tools"],
        )
        self.assertEqual(
            [group["requirement"] for group in groups],
            ["required", "required", "recommended", "recommended", "recommended"],
        )
        by_id = {group["id"]: group for group in groups}
        self.assertIn("recommendations, not requirements", by_id["actuators"]["note"].lower())

    def test_the_battery_is_chosen_and_carries_its_own_fuse(self):
        power = next(g for g in hardware_guide(self.config)["parts_groups"] if g["id"] == "power")
        names = " ".join(part["name"] for part in power["items"]).lower()
        self.assertIn("12 v battery", names)
        self.assertNotIn("fuse or breaker", names)
        self.assertIn("fuse", power["note"].lower())
        batteries = [part for part in power["items"] if "battery" in part["name"].lower()]
        self.assertEqual({part["status"] for part in batteries}, {"selected"})
        self.assertTrue(all(part["url"] for part in batteries))
        # The only unfinished thing in the power group is its own CAD.
        pending = {part["name"] for part in power["items"] if part["status"] == "placeholder"}
        self.assertEqual(pending, {"Power module CAD"})
        self.assertIn("3.3-6 V", power["note"])

    def test_wiring_drops_the_parts_that_ship_with_the_boards(self):
        wiring = next(g for g in hardware_guide(self.config)["parts_groups"] if g["id"] == "wiring")
        names = " ".join(part["name"] for part in wiring["items"]).lower()
        for gone in ("servo extension", "common-ground", "strain relief", "cooling", "connector pack"):
            self.assertNotIn(gone, names)
        self.assertEqual(len(wiring["items"]), 3)

    def test_only_one_servo_board_and_no_pull_down_resistors_are_listed(self):
        parts = [part for group in hardware_guide(self.config)["parts_groups"] for part in group["items"]]
        names = " ".join(part["name"] for part in parts).lower()
        self.assertNotIn("second pca9685", names)
        self.assertNotIn("pull-down", names)
        self.assertEqual(sum("pca9685" in part["name"].lower() for part in parts), 1)


if __name__ == "__main__":
    unittest.main()

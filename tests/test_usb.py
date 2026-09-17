import tempfile
import unittest
from pathlib import Path

from motion_module.usb import sensor_controllers, usb_devices


class UsbInventoryTests(unittest.TestCase):
    def test_unavailable_outside_linux_sysfs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = usb_devices(Path(directory) / "missing", Path(directory) / "dev")
        self.assertFalse(result["available"])
        self.assertEqual(result["devices"], [])

    def test_reads_identity_and_port_from_sysfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / "sys" / "1-2"
            node = root / "dev" / "001" / "007"
            device.mkdir(parents=True)
            node.parent.mkdir(parents=True)
            node.write_bytes(b"")
            values = {
                "idVendor": "2341\n",
                "idProduct": "0043\n",
                "manufacturer": "Arduino LLC\n",
                "product": "Arduino Uno\n",
                "serial": "ABC123\n",
                "busnum": "1\n",
                "devnum": "7\n",
                "speed": "12\n",
                "bDeviceClass": "00\n",
            }
            for name, value in values.items():
                (device / name).write_text(value, encoding="utf-8")
            tty = root / "sys" / "1-2_1.0" / "tty" / "ttyACM0"
            tty.mkdir(parents=True)
            serial_node = root / "tty" / "ttyACM0"
            serial_node.parent.mkdir(parents=True)
            serial_node.write_bytes(b"")
            result = usb_devices(root / "sys", root / "dev", root / "tty")
        self.assertTrue(result["available"])
        self.assertEqual(len(result["devices"]), 1)
        found = result["devices"][0]
        self.assertEqual(found["product"], "Arduino Uno")
        self.assertEqual(found["vendor_id"], "2341")
        self.assertEqual(found["product_id"], "0043")
        self.assertEqual(found["path"], "1-2")
        self.assertEqual(found["bus"], 1)
        self.assertEqual(found["device"], 7)
        self.assertEqual(found["serial_port"], str(serial_node))

    def test_giga_r1_is_recognized_as_a_supported_sensor_controller(self):
        inventory = {
            "available": True,
            "devices": [{
                "path": "1-4", "vendor_id": "2341", "product_id": "0266",
                "serial": "GIGA123", "serial_port": "/dev/ttyACM0",
                "controller": {
                    "board_id": "arduino_giga_r1_wifi", "name": "Arduino GIGA R1 WiFi",
                    "transport": "USB CDC serial", "digital_pins": ["D0", "D75"],
                    "analog_pins": ["A0", "A7"], "dac_pins": ["A12", "A13"], "adc_bits": 12,
                },
            }],
        }
        controllers = sensor_controllers(inventory)
        self.assertEqual(controllers[0]["board_id"], "arduino_giga_r1_wifi")
        self.assertEqual(controllers[0]["serial"], "GIGA123")
        self.assertEqual(controllers[0]["analog_pins"], ["A0", "A7"])

    def test_giga_in_its_bootloader_is_recognized_and_explained(self):
        from motion_module.usb import USB_CONTROLLER_PROFILES

        profile = USB_CONTROLLER_PROFILES[("2341", "0366")]
        self.assertEqual(profile["mode"], "bootloader")
        self.assertEqual(USB_CONTROLLER_PROFILES[("2341", "0266")]["mode"], "sketch")
        inventory = {"devices": [{"path": "1-4", "vendor_id": "2341", "product_id": "0366",
                                  "serial": "", "serial_port": "", "controller": dict(profile)}]}
        controller = sensor_controllers(inventory)[0]
        self.assertEqual(controller["bridge"], "bootloader")
        self.assertIn("motionmodule giga flash", controller["detail"])


if __name__ == "__main__":
    unittest.main()

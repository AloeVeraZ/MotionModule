import tempfile
import unittest
from pathlib import Path

from motion_module.usb import usb_devices


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
            result = usb_devices(root / "sys", root / "dev")
        self.assertTrue(result["available"])
        self.assertEqual(len(result["devices"]), 1)
        found = result["devices"][0]
        self.assertEqual(found["product"], "Arduino Uno")
        self.assertEqual(found["vendor_id"], "2341")
        self.assertEqual(found["product_id"], "0043")
        self.assertEqual(found["path"], "1-2")
        self.assertEqual(found["bus"], 1)
        self.assertEqual(found["device"], 7)


if __name__ == "__main__":
    unittest.main()

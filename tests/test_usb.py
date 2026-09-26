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

    def test_pi_ports_pair_companions_and_nest_hub_devices(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def device(name, bus, ports=0, product='Webcam'):
                folder = root / name
                folder.mkdir()
                for key, value in {'idVendor':'1234', 'idProduct':'5678', 'busnum':str(bus),
                                   'devnum':'1' if name.startswith('usb') else '2',
                                   'bDeviceClass':'09' if ports else '00', 'maxchild':str(ports),
                                   'product':product}.items():
                    (folder / key).write_text(value)
            for bus in range(1, 5):
                device(f'usb{bus}', bus, 2 if bus % 2 else 1, 'xHCI Host Controller')
            device('1-1', 1, 3, 'USB splitter')
            device('1-1.2', 1)
            device('3-2', 3, product='Arduino')
            # Reproduce Linux peer symlinks without requiring Windows symlink privileges.
            peer_paths = {}
            for low, high in ((1,2),(3,4)):
                a = root / f'usb{low}' / f'{low}-0:1.0' / f'usb{low}-port1'
                b = root / f'usb{high}' / f'{high}-0:1.0' / f'usb{high}-port1'
                peer_paths[str(a / 'peer')] = b
                peer_paths[str(b / 'peer')] = a
            original = Path.resolve
            def resolve(path, strict=False):
                if str(path) in peer_paths:
                    return original(peer_paths[str(path)])
                return original(path, strict=strict)
            with patch.object(Path, 'resolve', resolve):
                result = usb_devices(root, root/'dev', root/'tty')
            self.assertEqual(len(result['devices']), 3)
            self.assertEqual(len(result['host_controllers']), 4)
            self.assertEqual(len(result['ports']), 4)
            port = next(p for p in result['ports'] if '1-1' in p['paths'])
            self.assertTrue(port['paired'])
            self.assertEqual(port['buses'], [1,2])
            self.assertEqual(len(port['ports']), 3)
            self.assertEqual(port['ports'][1]['devices'][0]['product'], 'Webcam')
            self.assertFalse(port['ports'][0]['connected'])
            # Unplugging changes occupancy without deleting the socket.
            import shutil
            shutil.rmtree(root / '3-2')
            with patch.object(Path, 'resolve', resolve):
                result = usb_devices(root, root/'dev', root/'tty')
            self.assertFalse(next(p for p in result['ports'] if '3-2' in p['paths'])['connected'])

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

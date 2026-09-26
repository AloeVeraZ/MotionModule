"""AK8963 auxiliary magnetometer, read through the MPU's I2C bypass.

Register sequence and scale: InvenSense RM-000008 sections 5.3–5.13.
Initialization is paced by poll(), never sleeps or delays heading control.
Factory sensitivity adjustment is applied; these are magnetic field readings,
not a calibrated compass or a replacement for relative gyro heading.
"""

from struct import unpack


class AK8963Reader:
    ADDRESS = 0x0C

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = "probe"
        self.next_at = 0.0
        self.updated = None
        self.vector = None
        self.adjust = (1.0, 1.0, 1.0)
        self.detail = "Checking AK8963 magnetometer at 0x0C"

    def poll(self, bus, now):
        if now < self.next_at:
            return

        def read(register, length):
            data = bytes(bus.read_i2c_block_data(self.ADDRESS, register, length))
            if len(data) != length:
                raise OSError("short magnetometer read")
            return data

        def write(value):
            bus.write_i2c_block_data(self.ADDRESS, 0x0A, [value])

        try:
            if self.state == "probe":
                identity = read(0x00, 1)[0]
                if identity != 0x48:
                    raise OSError(f"AK8963 identity is 0x{identity:02X}, expected 0x48")
                write(0x00)  # power down before changing mode
                self.state = "fuse"
                self.detail = "AK8963 detected; initializing"
            elif self.state == "fuse":
                write(0x0F)
                self.state = "sensitivity"
            elif self.state == "sensitivity":
                asa = read(0x10, 3)
                if any(value in (0, 255) for value in asa):
                    raise OSError("invalid factory magnetometer sensitivity")
                self.adjust = tuple(1 + (value - 128) / 256 for value in asa)
                write(0x00)
                self.state = "continuous"
            elif self.state == "continuous":
                write(0x16)  # 16-bit output, continuous measurement at 100 Hz
                self.state = "verify"
            elif self.state == "verify":
                if read(0x0A, 1)[0] != 0x16:
                    raise OSError("magnetometer mode did not retain its setting")
                self.state = "reading"
            else:
                if not read(0x02, 1)[0] & 1:  # ST1: data ready
                    return
                data = read(0x03, 7)  # read ST2 too, releasing the sample latch
                if data[6] & 0x08:
                    self.vector = None
                    self.detail = "Magnetometer overflow; move away from strong magnetic fields"
                    return
                if not data[6] & 0x10:
                    raise OSError("magnetometer unexpectedly left 16-bit mode")
                self.vector = tuple(value * 0.15 * scale for value, scale in
                                    zip(unpack("<3h", data[:6]), self.adjust))
                self.updated = now
                self.detail = "AK8963 responding; factory-adjusted magnetic field (not compass-calibrated)"
            self.next_at = now + 0.01  # exceeds the required mode-switch delay
        except OSError as error:
            self.vector = None
            self.updated = None
            self.state = "probe"
            self.next_at = now + 2.0
            self.detail = f"Magnetometer unavailable at 0x0C: {error}"

    def reading(self, now):
        if self.updated is not None and now - self.updated > 1.0:
            return None, "Magnetometer readings are stale"
        return self.vector, self.detail

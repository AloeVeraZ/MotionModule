// Runs the real GIGA sensor bridge sketch on a development computer.
//
// The sketch talks to a simulated BNO055 and LSM6-family IMU on a simulated
// I2C bus while a script on standard input moves the "robot":
//
//   attach bno055 ADDRESS [BOOT_MS]   attach lsm6 ADDRESS WHO_AM_I   detach ADDRESS
//   spin DEGREES_PER_SECOND           tilt PITCH ROLL                bias ADDRESS X Y Z
//   noise ADDRESS PEAK_TO_PEAK        pin LABEL VALUE                host 0|1
//   send TEXT                         run MILLISECONDS               led
//
// Everything the sketch writes comes back as "OUT <ms> <line>".
// tests/test_giga_firmware.py builds this and checks the transcript.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>

#include "Arduino.h"
#include "Wire.h"

namespace sim {
uint64_t microseconds = 0;
int pinModes[128] = {};
int pinValues[128] = {};
}  // namespace sim

HarnessSerial Serial;
HarnessWire Wire;

#include "giga_sensor_bridge.ino"

namespace {

constexpr double GRAVITY = 9.80665;

// What the simulated robot is really doing.
struct Truth {
  double yaw = 0.0;   // degrees, counter-clockwise positive
  double rate = 0.0;  // degrees per second about vertical
  double pitch = 0.0;
  double roll = 0.0;
} truth;

// Unit up vector in sensor axes for a flat-mounted sensor at this tilt.
void upVector(double &x, double &y, double &z) {
  double pitch = truth.pitch / 57.29577951308232;
  double roll = truth.roll / 57.29577951308232;
  x = -sin(roll) * cos(pitch);
  y = sin(pitch);
  z = cos(roll) * cos(pitch);
}

uint8_t lowByte16(int value) { return (uint8_t)(value & 0xFF); }
uint8_t highByte16(int value) { return (uint8_t)((value >> 8) & 0xFF); }

int clamp16(double value) {
  long rounded = lround(value);
  if (rounded > 32767) return 32767;
  if (rounded < -32768) return -32768;
  return (int)rounded;
}

class SimBno055 : public SimDevice {
 public:
  explicit SimBno055(uint64_t bootMicros) : readyAt(bootMicros) {}

  bool answers(uint64_t now) override { return now >= readyAt; }

  void writeRegister(uint8_t reg, uint8_t value, uint64_t now) override {
    if (reg == 0x3D) {
      mode = value & 0x0F;
      if (mode != 0) {
        fusionYaw = truth.yaw;
        fusionStart = now;
      }
    } else if (reg == 0x3F) {
      trigger = value;
      if (value & 0x20) {  // system reset: silent for 650 ms
        readyAt = now + 650000;
        mode = 0;
        crystal = false;
      } else {
        crystal = (value & 0x80) != 0;
      }
    } else if (reg == 0x3B) {
      units = value;
    }
  }

  uint8_t readRegister(uint8_t reg, uint64_t now) override {
    if (reg == 0x00) return 0xA0;
    if (reg == 0x3D) return mode;
    if (mode == 0) return 0;
    double heading = fmod(-(truth.yaw - fusionYaw), 360.0);
    if (heading < 0) heading += 360.0;
    double upX, upY, upZ;
    upVector(upX, upY, upZ);
    int value = 0;
    switch (reg) {
      case 0x14: case 0x15: value = 0; break;                       // gyro x
      case 0x16: case 0x17: value = 0; break;                       // gyro y
      case 0x18: case 0x19: value = clamp16(truth.rate * 16); break; // gyro z
      case 0x1A: case 0x1B: value = clamp16(heading * 16); break;
      case 0x2E: case 0x2F: value = clamp16(upX * GRAVITY * 100); break;
      case 0x30: case 0x31: value = clamp16(upY * GRAVITY * 100); break;
      case 0x32: case 0x33: value = clamp16(upZ * GRAVITY * 100); break;
      case 0x34: return 25;
      case 0x35: return now - fusionStart >= 1000000 ? 0x34 : 0x00;  // gyro 3, accel 1
      case 0x39: return 5;  // fusion running
      case 0x3A: return 0;
      default: return 0;
    }
    return (reg & 1) == 0 ? lowByte16(value) : highByte16(value);
  }

  bool crystal = false;
  uint8_t units = 0x80;

 private:
  uint64_t readyAt;
  uint8_t mode = 0;
  uint8_t trigger = 0;
  double fusionYaw = 0.0;
  uint64_t fusionStart = 0;
};

class SimLsm6 : public SimDevice {
 public:
  explicit SimLsm6(uint8_t whoAmI) : who(whoAmI) { registers[0x12] = 0x04; }

  bool answers(uint64_t) override { return true; }

  void writeRegister(uint8_t reg, uint8_t value, uint64_t now) override {
    if (reg == 0x12 && (value & 0x01)) {
      resettingUntil = now + 10000;
      memset(registers, 0, sizeof(registers));
      registers[0x12] = 0x04;
      return;
    }
    registers[reg] = value;
  }

  uint8_t readRegister(uint8_t reg, uint64_t now) override {
    if (reg == 0x0F) return who;
    if (reg == 0x12) return now < resettingUntil ? (registers[0x12] | 0x01) : registers[0x12];
    if (reg == 0x1E) {
      sample(now);
      return ready ? 0x03 : 0x00;
    }
    if (reg >= 0x22 && reg <= 0x2D) {
      if (reg == 0x22) {
        latch();
        ready = false;
      }
      int value = latched[(reg - 0x22) / 2];
      return (reg & 1) == 0 ? lowByte16(value) : highByte16(value);
    }
    return registers[reg];
  }

  double biasX = 0.0, biasY = 0.0, biasZ = 0.0;
  double noise = 0.0;

 private:
  void sample(uint64_t now) {
    if ((registers[0x11] >> 4) != 6) return;  // gyro off until 416 Hz is chosen
    if (now - lastSample >= 2404) {
      lastSample = now;
      ready = true;
    }
  }

  double wobble() {
    state = state * 1103515245u + 12345u;
    return noise * (((state >> 8) & 0xFFFF) / 65535.0 - 0.5);
  }

  void latch() {
    double upX, upY, upZ;
    upVector(upX, upY, upZ);
    constexpr double dpsPerCount = 0.070;
    constexpr double countsPerG = 1000.0 / 0.122;
    latched[0] = clamp16((truth.rate * upX + biasX + wobble()) / dpsPerCount);
    latched[1] = clamp16((truth.rate * upY + biasY + wobble()) / dpsPerCount);
    latched[2] = clamp16((truth.rate * upZ + biasZ + wobble()) / dpsPerCount);
    latched[3] = clamp16(upX * countsPerG);
    latched[4] = clamp16(upY * countsPerG);
    latched[5] = clamp16(upZ * countsPerG);
  }

  uint8_t who;
  uint8_t registers[256] = {};
  uint64_t resettingUntil = 0;
  uint64_t lastSample = 0;
  bool ready = false;
  int latched[6] = {};
  uint32_t state = 12345;
};

int pinFromLabel(const std::string &label) {
  int number = atoi(label.c_str() + 1);
  return label[0] == 'A' ? A0 + number : number;
}

size_t flushed = 0;

void flushOutput() {
  std::string &text = Serial.written;
  size_t newline;
  while ((newline = text.find('\n', flushed)) != std::string::npos) {
    std::cout << "OUT " << millis() << " " << text.substr(flushed, newline - flushed) << "\n";
    flushed = newline + 1;
  }
  if (flushed > 0) {
    text.erase(0, flushed);
    flushed = 0;
  }
}

void run(unsigned long milliseconds) {
  constexpr uint64_t step = 250;  // the sketch loops about 4000 times a second
  uint64_t end = sim::microseconds + (uint64_t)milliseconds * 1000;
  while (sim::microseconds < end) {
    loop();
    flushOutput();
    sim::microseconds += step;
    truth.yaw += truth.rate * (step / 1.0e6);
  }
}

}  // namespace

int main() {
  std::ios::sync_with_stdio(false);
  setup();
  std::string text;
  while (std::getline(std::cin, text)) {
    if (!text.empty() && text.back() == '\r') text.pop_back();
    std::istringstream words(text);
    std::string command;
    words >> command;
    if (command == "attach") {
      std::string kind;
      int address = 0;
      words >> kind >> address;
      if (kind == "bno055") {
        long bootMs = 700;
        words >> bootMs;
        Wire.devices[address] = new SimBno055(sim::microseconds + (uint64_t)bootMs * 1000);
      } else {
        int who = 0x6B;
        words >> who;
        Wire.devices[address] = new SimLsm6((uint8_t)who);
      }
    } else if (command == "detach") {
      int address = 0;
      words >> address;
      Wire.devices[address] = nullptr;
    } else if (command == "spin") {
      words >> truth.rate;
    } else if (command == "tilt") {
      words >> truth.pitch >> truth.roll;
    } else if (command == "bias" || command == "noise") {
      int address = 0;
      words >> address;
      SimLsm6 *device = dynamic_cast<SimLsm6 *>(Wire.devices[address]);
      if (device != nullptr && command == "bias") words >> device->biasX >> device->biasY >> device->biasZ;
      if (device != nullptr && command == "noise") words >> device->noise;
    } else if (command == "pin") {
      std::string label;
      int value = 0;
      words >> label >> value;
      sim::pinValues[pinFromLabel(label)] = value;
    } else if (command == "host") {
      int connected = 1;
      words >> connected;
      Serial.connected = connected != 0;
    } else if (command == "send") {
      std::string line = text.size() > 5 ? text.substr(5) : "";
      for (char character : line) Serial.input.push_back(character);
      Serial.input.push_back('\n');
    } else if (command == "run") {
      unsigned long milliseconds = 0;
      words >> milliseconds;
      run(milliseconds);
    } else if (command == "led") {
      std::cout << "LED " << (sim::pinValues[LEDR] == LOW) << " " << (sim::pinValues[LEDG] == LOW) << " "
                << (sim::pinValues[LEDB] == LOW) << "\n";
    } else if (command == "truth") {
      std::cout << "TRUTH " << truth.yaw << "\n";
    } else if (command == "pinmode") {
      std::string label;
      words >> label;
      std::cout << "PINMODE " << label << " " << sim::pinModes[pinFromLabel(label)] << "\n";
    } else if (command == "crystal") {
      int address = 0;
      words >> address;
      SimBno055 *device = dynamic_cast<SimBno055 *>(Wire.devices[address]);
      std::cout << "CRYSTAL " << (device != nullptr && device->crystal) << " "
                << (device != nullptr ? (int)device->units : -1) << "\n";
    }
  }
  std::cout.flush();
  return 0;
}

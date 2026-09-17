// An I2C bus of simulated devices for the sensor bridge harness.
#pragma once

#include <deque>
#include <vector>

#include "Arduino.h"

class SimDevice {
 public:
  virtual ~SimDevice() = default;
  virtual bool answers(uint64_t now) = 0;
  virtual void writeRegister(uint8_t reg, uint8_t value, uint64_t now) = 0;
  virtual uint8_t readRegister(uint8_t reg, uint64_t now) = 0;
};

class HarnessWire {
 public:
  void begin() {}
  void setClock(unsigned long) {}

  void beginTransmission(uint8_t address) {
    target = address;
    pending.clear();
  }

  size_t write(uint8_t value) {
    pending.push_back(value);
    return 1;
  }

  // 0 is an acknowledged transfer, 2 a device that did not answer.
  uint8_t endTransmission(bool stop = true) {
    (void)stop;
    SimDevice *device = devices[target & 0x7F];
    if (device == nullptr || !device->answers(sim::microseconds)) return 2;
    if (pending.empty()) return 0;
    pointer[target & 0x7F] = pending[0];
    for (size_t index = 1; index < pending.size(); index++) {
      device->writeRegister(pointer[target & 0x7F]++, pending[index], sim::microseconds);
    }
    return 0;
  }

  size_t requestFrom(uint8_t address, size_t length) {
    SimDevice *device = devices[address & 0x7F];
    if (device == nullptr || !device->answers(sim::microseconds)) return 0;
    for (size_t index = 0; index < length; index++) {
      received.push_back(device->readRegister(pointer[address & 0x7F]++, sim::microseconds));
    }
    return length;
  }

  int available() { return (int)received.size(); }

  int read() {
    if (received.empty()) return -1;
    int value = received.front();
    received.pop_front();
    return value;
  }

  SimDevice *devices[128] = {};

 private:
  uint8_t target = 0;
  std::vector<uint8_t> pending;
  std::deque<uint8_t> received;
  uint8_t pointer[128] = {};
};

extern HarnessWire Wire;

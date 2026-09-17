// Runs the real GIGA sensor bridge firmware on a development computer.
//
// The firmware only moves bytes, so the harness gives it simulated I2C
// devices with plain register maps and a script on standard input:
//
//   attach ADDRESS        detach ADDRESS      quiet ADDRESS 0|1
//   poke ADDRESS REGISTER VALUE               peek ADDRESS REGISTER
//   pin LABEL VALUE       pinmode LABEL       host 0|1
//   send TEXT             run MILLISECONDS    led
//
// Everything the firmware writes comes back as "OUT <ms> <line>".
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

// A simulated chip: 256 registers that answer reads and remember writes.
class SimChip : public SimDevice {
 public:
  bool answers(uint64_t) override { return !quiet; }

  void writeRegister(uint8_t reg, uint8_t value, uint64_t) override { registers[reg] = value; }

  uint8_t readRegister(uint8_t reg, uint64_t) override { return registers[reg]; }

  uint8_t registers[256] = {};
  bool quiet = false;
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
  constexpr uint64_t step = 250;  // the firmware loops about 4000 times a second
  uint64_t end = sim::microseconds + (uint64_t)milliseconds * 1000;
  while (sim::microseconds < end) {
    loop();
    flushOutput();
    sim::microseconds += step;
  }
}

SimChip *chipAt(int address) { return dynamic_cast<SimChip *>(Wire.devices[address & 0x7F]); }

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
      int address = 0;
      words >> address;
      Wire.devices[address & 0x7F] = new SimChip();
    } else if (command == "detach") {
      int address = 0;
      words >> address;
      Wire.devices[address & 0x7F] = nullptr;
    } else if (command == "quiet") {
      int address = 0, quiet = 1;
      words >> address >> quiet;
      SimChip *chip = chipAt(address);
      if (chip != nullptr) chip->quiet = quiet != 0;
    } else if (command == "poke") {
      int address = 0, reg = 0, value = 0;
      words >> address >> reg >> value;
      SimChip *chip = chipAt(address);
      if (chip != nullptr) chip->registers[reg & 0xFF] = (uint8_t)value;
    } else if (command == "peek") {
      int address = 0, reg = 0;
      words >> address >> reg;
      SimChip *chip = chipAt(address);
      std::cout << "PEEK " << address << " " << reg << " "
                << (chip != nullptr ? (int)chip->registers[reg & 0xFF] : -1) << "\n";
    } else if (command == "pin") {
      std::string label;
      int value = 0;
      words >> label >> value;
      sim::pinValues[pinFromLabel(label)] = value;
    } else if (command == "pinmode") {
      std::string label;
      words >> label;
      std::cout << "PINMODE " << label << " " << sim::pinModes[pinFromLabel(label)] << "\n";
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
    }
  }
  std::cout.flush();
  return 0;
}

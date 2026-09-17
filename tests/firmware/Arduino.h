// Just enough of the Arduino API to run the GIGA sensor bridge sketch on a
// development computer, against the simulated sensors in harness.cpp.
#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <math.h>
#include <string>

constexpr int LOW = 0;
constexpr int HIGH = 1;
constexpr int INPUT = 0;
constexpr int OUTPUT = 1;
constexpr int INPUT_PULLUP = 2;
constexpr int INPUT_PULLDOWN = 3;

// The GIGA's own numbering: A0 is pin 76 and the RGB LED is 86-88.
constexpr uint8_t A0 = 76, A1 = 77, A2 = 78, A3 = 79, A4 = 80, A5 = 81, A6 = 82, A7 = 83;
constexpr int LEDR = 86;
constexpr int LEDG = 87;
constexpr int LEDB = 88;

namespace sim {
extern uint64_t microseconds;
extern int pinModes[128];
extern int pinValues[128];
}  // namespace sim

inline unsigned long millis() { return (unsigned long)(sim::microseconds / 1000); }
inline unsigned long micros() { return (unsigned long)sim::microseconds; }
inline void pinMode(int pin, int mode) { sim::pinModes[pin] = mode; }
inline int digitalRead(int pin) { return sim::pinValues[pin] ? HIGH : LOW; }
inline void digitalWrite(int pin, int value) { sim::pinValues[pin] = value; }
inline int analogRead(int pin) { return sim::pinValues[pin]; }
inline void analogReadResolution(int) {}

class HarnessSerial {
 public:
  void begin(unsigned long) {}
  int available() { return (int)input.size(); }
  int read() {
    if (input.empty()) return -1;
    int value = (unsigned char)input.front();
    input.pop_front();
    return value;
  }
  // Like the GIGA's USB serial, nothing is sent while no host has the port open.
  size_t write(const uint8_t *data, size_t length) {
    if (!connected) return 0;
    written.append((const char *)data, length);
    return length;
  }

  std::deque<char> input;
  std::string written;
  bool connected = true;
};

extern HarnessSerial Serial;

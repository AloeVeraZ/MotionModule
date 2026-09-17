/* MotionModule sensor bridge for the Arduino GIGA R1 WiFi.

   The GIGA is the robot's sensor board, and nothing more. It reads the pins
   and I2C registers the Raspberry Pi asks for and sends the numbers straight
   up the USB cable. It does no maths and knows nothing about any particular
   sensor: the Pi decides what to read, when to read it, and what the readings
   mean. One copy of this firmware therefore serves every robot, and changing
   sensors never means reflashing.

   No Arduino IDE is needed. With the GIGA plugged into the Pi, run

       motionmodule giga flash

   or press Install firmware under Debug. The Pi flashes the prebuilt copy of
   this sketch, firmware/giga_sensor_bridge.bin. The IDE still works: install
   "Arduino Mbed OS Giga Boards", pick Arduino Giga R1, and upload.

   Every message is one line. From the Pi:

     MM3 CONFIG <id> <ms> <pins or -> <streams or ->
         What to read, and how often. Pins are A0:A,D22:U; streams are I2C
         reads as ADDRESS:REGISTER:LENGTH in hex, such as 28:1A:6,6A:22:12.
         MM3 CONFIG 7 20 A0:A,D22:U 6A:22:12
     MM3 I2C <seq> <addr> R <reg> <len>      one read, answered once
     MM3 I2C <seq> <addr> W <reg> <hex>      one write, answered once
     MM3 SCAN <seq>                          which I2C addresses answer
     MM3 HELLO                               firmware version and limits
     MM1 CONFIG <pins>                       the original pins-only protocol

   Pin modes: A analog (0-4095), D digital, U digital with pull-up, N with
   pull-down. The GIGA's pins take 3.3 V at most.

   Back to the Pi: JSON lines tagged "protocol":"motionmodule-sensor-v3". A
   reading line carries the board's own millisecond clock, so the Pi can work
   out exactly how far apart two readings were taken.
*/

#include <Wire.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char BRIDGE_VERSION[] = "3.0.0";
const char BRIDGE_BOARD[] = "arduino_giga_r1_wifi";
const char PROTOCOL[] = "motionmodule-sensor-v3";

constexpr int MAX_INPUTS = 20;
constexpr int MAX_STREAMS = 6;
constexpr int MAX_STREAM_BYTES = 32;
constexpr int MAX_WRITE_BYTES = 16;
constexpr unsigned long DEFAULT_INTERVAL_MS = 20;         // 50 readings a second
constexpr unsigned long MINIMUM_INTERVAL_MS = 5;
constexpr unsigned long MAXIMUM_INTERVAL_MS = 1000;
constexpr unsigned long LEGACY_INTERVAL_MS = 100;         // the original sketch's pace
constexpr unsigned long HELLO_INTERVAL_MS = 1000;
constexpr unsigned long BUS_CLOCK_HZ = 400000;
constexpr uint8_t FIRST_I2C_ADDRESS = 0x08;
constexpr uint8_t LAST_I2C_ADDRESS = 0x77;

// Types come before any function: the Arduino build adds a declaration of
// every function above the first one, and those name these types.

struct OutputLine {
  char text[1600];
  size_t length;
  bool overflow;
};

OutputLine output;

struct InputPin {
  char label[4];  // "A0" through "D75"
  int number;
  char mode;
};

InputPin inputs[MAX_INPUTS];
int inputCount = 0;

// One I2C read the Pi wants repeated with every reading.
struct I2cStream {
  uint8_t address;
  uint8_t reg;
  uint8_t length;
  uint8_t data[MAX_STREAM_BYTES];
  bool ok;
};

I2cStream streams[MAX_STREAMS];
int streamCount = 0;

// ------------------------------------------------------------------ output

void lineStart(OutputLine &line) {
  line.length = 0;
  line.overflow = false;
  line.text[0] = '\0';
}

void lineAdd(OutputLine &line, const char *format, ...) {
  if (line.overflow) return;
  size_t room = sizeof(line.text) - line.length;
  va_list arguments;
  va_start(arguments, format);
  int written = vsnprintf(line.text + line.length, room, format, arguments);
  va_end(arguments);
  if (written < 0 || (size_t)written >= room) {
    line.overflow = true;
    return;
  }
  line.length += (size_t)written;
}

void lineAddHex(OutputLine &line, const uint8_t *data, size_t length) {
  static const char digits[] = "0123456789abcdef";
  if (line.overflow) return;
  if (line.length + length * 2 + 1 >= sizeof(line.text)) {
    line.overflow = true;
    return;
  }
  for (size_t index = 0; index < length; index++) {
    line.text[line.length++] = digits[data[index] >> 4];
    line.text[line.length++] = digits[data[index] & 0x0F];
  }
  line.text[line.length] = '\0';
}

// One write per message: printing piece by piece sends a USB packet per piece.
void lineSend(OutputLine &line) {
  lineAdd(line, "\n");
  if (line.overflow) return;  // never send half a message
  Serial.write((const uint8_t *)line.text, line.length);
}

// -------------------------------------------------------------------- pins

int resolvePin(const char *label, char mode) {
  bool analog = label[0] == 'A';
  if (!analog && label[0] != 'D') return -1;
  if ((mode == 'A') != analog) return -1;
  if (label[1] < '0' || label[1] > '9') return -1;
  if (label[2] != '\0' && (label[2] < '0' || label[2] > '9')) return -1;
  int number = atoi(label + 1);
  if (analog) {
    static const int analogPins[] = {A0, A1, A2, A3, A4, A5, A6, A7};
    return number < 8 ? analogPins[number] : -1;
  }
  return number <= 75 ? number : -1;
}

// Reads "A0:A,D22:U" into pins. Returns how many, or -1 if any entry is wrong.
int parsePins(const char *text, InputPin *pins) {
  if (strcmp(text, "-") == 0) return 0;
  int count = 0;
  const char *cursor = text;
  while (*cursor != '\0') {
    if (count == MAX_INPUTS) return -1;
    const char *comma = strchr(cursor, ',');
    size_t length = comma != nullptr ? (size_t)(comma - cursor) : strlen(cursor);
    if (length < 4 || length > 5 || cursor[length - 2] != ':') return -1;
    InputPin pin;
    memcpy(pin.label, cursor, length - 2);
    pin.label[length - 2] = '\0';
    pin.mode = cursor[length - 1];
    if (pin.mode != 'A' && pin.mode != 'D' && pin.mode != 'U' && pin.mode != 'N') return -1;
    pin.number = resolvePin(pin.label, pin.mode);
    if (pin.number < 0) return -1;
    pins[count++] = pin;
    if (comma == nullptr) break;
    cursor = comma + 1;
  }
  return count;
}

void applyPins(const InputPin *pins, int count) {
  for (int index = 0; index < count; index++) {
    inputs[index] = pins[index];
    if (pins[index].mode == 'U') pinMode(pins[index].number, INPUT_PULLUP);
    else if (pins[index].mode == 'N') pinMode(pins[index].number, INPUT_PULLDOWN);
    else if (pins[index].mode == 'D') pinMode(pins[index].number, INPUT);
  }
  inputCount = count;
}

int readPin(const InputPin &pin) {
  if (pin.mode == 'A') return analogRead(pin.number);
  return digitalRead(pin.number) == HIGH ? 1 : 0;
}

// --------------------------------------------------------------------- I2C

bool busRead(uint8_t address, uint8_t reg, uint8_t *data, size_t length) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  size_t received = Wire.requestFrom(address, length);
  if (received != length) {
    while (Wire.available() > 0) Wire.read();
    return false;
  }
  for (size_t index = 0; index < length; index++) data[index] = (uint8_t)Wire.read();
  return true;
}

bool busWrite(uint8_t address, uint8_t reg, const uint8_t *data, size_t length) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  for (size_t index = 0; index < length; index++) Wire.write(data[index]);
  return Wire.endTransmission() == 0;
}

bool busAnswers(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

int hexValue(char character) {
  if (character >= '0' && character <= '9') return character - '0';
  if (character >= 'a' && character <= 'f') return character - 'a' + 10;
  if (character >= 'A' && character <= 'F') return character - 'A' + 10;
  return -1;
}

// Reads "1a2b" into bytes. Returns how many, or -1 if it is not full bytes.
int parseHex(const char *text, uint8_t *data, int limit) {
  size_t length = strlen(text);
  if (length == 0 || length % 2 != 0 || (int)(length / 2) > limit) return -1;
  for (size_t index = 0; index < length; index += 2) {
    int high = hexValue(text[index]);
    int low = hexValue(text[index + 1]);
    if (high < 0 || low < 0) return -1;
    data[index / 2] = (uint8_t)((high << 4) | low);
  }
  return (int)(length / 2);
}

// Reads "28:1A:6,6A:22:12" into streams. Returns how many, or -1.
int parseStreams(const char *text, I2cStream *into) {
  if (strcmp(text, "-") == 0) return 0;
  int count = 0;
  const char *cursor = text;
  while (*cursor != '\0') {
    if (count == MAX_STREAMS) return -1;
    const char *comma = strchr(cursor, ',');
    size_t length = comma != nullptr ? (size_t)(comma - cursor) : strlen(cursor);
    char item[16];
    if (length == 0 || length >= sizeof(item)) return -1;
    memcpy(item, cursor, length);
    item[length] = '\0';
    char *registerText = strchr(item, ':');
    if (registerText == nullptr) return -1;
    *registerText++ = '\0';
    char *lengthText = strchr(registerText, ':');
    if (lengthText == nullptr) return -1;
    *lengthText++ = '\0';
    char *end = nullptr;
    long address = strtol(item, &end, 16);
    if (end == item || *end != '\0' || address < FIRST_I2C_ADDRESS || address > LAST_I2C_ADDRESS) return -1;
    long reg = strtol(registerText, &end, 16);
    if (end == registerText || *end != '\0' || reg < 0 || reg > 0xFF) return -1;
    long bytes = strtol(lengthText, &end, 10);
    if (end == lengthText || *end != '\0' || bytes < 1 || bytes > MAX_STREAM_BYTES) return -1;
    I2cStream stream;
    memset(&stream, 0, sizeof(stream));
    stream.address = (uint8_t)address;
    stream.reg = (uint8_t)reg;
    stream.length = (uint8_t)bytes;
    into[count++] = stream;
    if (comma == nullptr) break;
    cursor = comma + 1;
  }
  return count;
}

// ---------------------------------------------------------------- messages

char activeConfig[320] = "";
long configId = -1;
int protocolMode = 0;  // 0 until the Pi configures it, 1 original protocol, 3 current
unsigned long interval = DEFAULT_INTERVAL_MS;
unsigned long lastReading = 0;
unsigned long lastHello = 0;
unsigned long sequence = 0;

void eventStart(const char *event) {
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"%s\",\"event\":\"%s\",\"firmware\":\"%s\"", PROTOCOL, event, BRIDGE_VERSION);
}

void sendHello() {
  eventStart("hello");
  lineAdd(output, ",\"board\":\"%s\",\"streams\":%d,\"stream_bytes\":%d,\"pins\":%d}",
          BRIDGE_BOARD, MAX_STREAMS, MAX_STREAM_BYTES, MAX_INPUTS);
  lineSend(output);
}

void sendConfigured() {
  eventStart("configured");
  lineAdd(output, ",\"config\":%ld,\"pins\":%d,\"streams\":%d,\"interval\":%lu}",
          configId, inputCount, streamCount, interval);
  lineSend(output);
}

void sendError(const char *message) {
  eventStart("error");
  lineAdd(output, ",\"message\":\"%s\"}", message);
  lineSend(output);
}

void sendReadings(unsigned long now) {
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"%s\",\"firmware\":\"%s\",\"config\":%ld,\"seq\":%lu,\"ms\":%lu,\"values\":{",
          PROTOCOL, BRIDGE_VERSION, configId, ++sequence, now);
  for (int index = 0; index < inputCount; index++) {
    lineAdd(output, "%s\"%s\":%d", index ? "," : "", inputs[index].label, readPin(inputs[index]));
  }
  lineAdd(output, "},\"i2c\":{");
  for (int index = 0; index < streamCount; index++) {
    I2cStream &stream = streams[index];
    lineAdd(output, "%s\"%02x:%02x\":", index ? "," : "", (unsigned)stream.address, (unsigned)stream.reg);
    if (stream.ok) {
      lineAdd(output, "\"");
      lineAddHex(output, stream.data, stream.length);
      lineAdd(output, "\"");
    } else {
      lineAdd(output, "null");  // the sensor did not answer this time
    }
  }
  lineAdd(output, "}}");
  lineSend(output);
}

void sendLegacyReadings() {
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"motionmodule-sensor-v1\",\"board\":\"%s\",\"firmware\":\"%s\",\"values\":{",
          BRIDGE_BOARD, BRIDGE_VERSION);
  for (int index = 0; index < inputCount; index++) {
    lineAdd(output, "%s\"%s\":%d", index ? "," : "", inputs[index].label, readPin(inputs[index]));
  }
  lineAdd(output, "}}");
  lineSend(output);
}

void handleConfig(const char *arguments) {
  // The same request again, as when the Pi reconnects: nothing to change.
  if (protocolMode == 3 && strcmp(arguments, activeConfig) == 0) return sendConfigured();
  char copy[sizeof(activeConfig)];
  if (strlen(arguments) >= sizeof(copy)) return sendError("config is too long");
  strcpy(copy, arguments);
  char *idText = strtok(copy, " ");
  char *intervalText = strtok(nullptr, " ");
  char *pinText = strtok(nullptr, " ");
  char *streamText = strtok(nullptr, " ");
  if (idText == nullptr || intervalText == nullptr || pinText == nullptr || streamText == nullptr ||
      strtok(nullptr, " ") != nullptr) {
    return sendError("expected MM3 CONFIG <id> <ms> <pins> <streams>");
  }
  char *end = nullptr;
  long id = strtol(idText, &end, 10);
  if (*end != '\0' || id < 0) return sendError("config id must be a whole number");
  long milliseconds = strtol(intervalText, &end, 10);
  if (*end != '\0' || milliseconds < (long)MINIMUM_INTERVAL_MS || milliseconds > (long)MAXIMUM_INTERVAL_MS) {
    return sendError("reading interval is out of range");
  }
  InputPin pins[MAX_INPUTS];
  int pinCount = parsePins(pinText, pins);
  if (pinCount < 0) return sendError("pin list not understood");
  I2cStream parsed[MAX_STREAMS];
  int parsedCount = parseStreams(streamText, parsed);
  if (parsedCount < 0) return sendError("I2C stream list not understood");

  applyPins(pins, pinCount);
  for (int index = 0; index < parsedCount; index++) streams[index] = parsed[index];
  streamCount = parsedCount;
  interval = (unsigned long)milliseconds;
  configId = id;
  strcpy(activeConfig, arguments);
  protocolMode = 3;
  lastReading = millis();
  sendConfigured();
}

void handleLegacyConfig(const char *declaration) {
  InputPin pins[MAX_INPUTS];
  int count = parsePins(declaration, pins);
  applyPins(pins, count < 0 ? 0 : count);
  streamCount = 0;
  activeConfig[0] = '\0';
  configId = -1;
  protocolMode = 1;
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"motionmodule-sensor-v1\",\"event\":\"configured\",\"firmware\":\"%s\"}",
          BRIDGE_VERSION);
  lineSend(output);
}

// One read or write the Pi asked for, answered with the same seq it sent.
void handleI2c(char *arguments) {
  char *seqText = strtok(arguments, " ");
  char *addressText = strtok(nullptr, " ");
  char *directionText = strtok(nullptr, " ");
  char *registerText = strtok(nullptr, " ");
  char *valueText = strtok(nullptr, " ");
  if (seqText == nullptr || addressText == nullptr || directionText == nullptr ||
      registerText == nullptr || valueText == nullptr || strtok(nullptr, " ") != nullptr) {
    return sendError("expected MM3 I2C <seq> <addr> R|W <reg> <len or hex>");
  }
  char *end = nullptr;
  long seq = strtol(seqText, &end, 10);
  if (*end != '\0' || seq < 0) return sendError("I2C seq must be a whole number");
  long address = strtol(addressText, &end, 16);
  if (*end != '\0' || address < FIRST_I2C_ADDRESS || address > LAST_I2C_ADDRESS) {
    return sendError("I2C address is out of range");
  }
  long reg = strtol(registerText, &end, 16);
  if (*end != '\0' || reg < 0 || reg > 0xFF) return sendError("I2C register is out of range");

  uint8_t data[MAX_STREAM_BYTES];
  bool ok = false;
  int length = 0;
  if (directionText[0] == 'R' && directionText[1] == '\0') {
    length = (int)strtol(valueText, &end, 10);
    if (*end != '\0' || length < 1 || length > MAX_STREAM_BYTES) return sendError("I2C read length is out of range");
    ok = busRead((uint8_t)address, (uint8_t)reg, data, (size_t)length);
  } else if (directionText[0] == 'W' && directionText[1] == '\0') {
    length = parseHex(valueText, data, MAX_WRITE_BYTES);
    if (length < 0) return sendError("I2C write needs whole hex bytes");
    ok = busWrite((uint8_t)address, (uint8_t)reg, data, (size_t)length);
    length = 0;
  } else {
    return sendError("I2C direction must be R or W");
  }

  eventStart("i2c");
  lineAdd(output, ",\"seq\":%ld,\"addr\":%u,\"reg\":%u,\"ok\":%d", seq, (unsigned)address, (unsigned)reg, ok ? 1 : 0);
  if (ok && length > 0) {
    lineAdd(output, ",\"data\":\"");
    lineAddHex(output, data, (size_t)length);
    lineAdd(output, "\"");
  }
  lineAdd(output, "}");
  lineSend(output);
}

void handleScan(const char *arguments) {
  char *end = nullptr;
  long seq = strtol(arguments, &end, 10);
  if (*end != '\0' || seq < 0) return sendError("expected MM3 SCAN <seq>");
  eventStart("scan");
  lineAdd(output, ",\"seq\":%ld,\"found\":[", seq);
  int found = 0;
  for (uint8_t address = FIRST_I2C_ADDRESS; address <= LAST_I2C_ADDRESS; address++) {
    if (!busAnswers(address)) continue;
    lineAdd(output, "%s%u", found++ ? "," : "", (unsigned)address);
  }
  lineAdd(output, "]}");
  lineSend(output);
}

void handleLine(char *text) {
  size_t length = strlen(text);
  while (length > 0 && (text[length - 1] == ' ' || text[length - 1] == '\t')) text[--length] = '\0';
  while (*text == ' ' || *text == '\t') text++;
  if (strncmp(text, "MM3 CONFIG ", 11) == 0) handleConfig(text + 11);
  else if (strncmp(text, "MM3 I2C ", 8) == 0) handleI2c(text + 8);
  else if (strncmp(text, "MM3 SCAN ", 9) == 0) handleScan(text + 9);
  else if (strcmp(text, "MM3 HELLO") == 0) sendHello();
  else if (strncmp(text, "MM1 CONFIG ", 11) == 0) handleLegacyConfig(text + 11);
}

char command[384];
size_t commandLength = 0;
bool commandTooLong = false;

void readCommands() {
  for (int budget = 1024; budget > 0 && Serial.available() > 0; budget--) {
    int received = Serial.read();
    if (received < 0) break;
    if (received == '\r') continue;
    if (received == '\n') {
      command[commandLength] = '\0';
      if (!commandTooLong) handleLine(command);
      commandLength = 0;
      commandTooLong = false;
    } else if (commandLength + 1 < sizeof(command)) {
      command[commandLength++] = (char)received;
    } else {
      commandTooLong = true;
    }
  }
}

// -------------------------------------------------------------- status LED
// Blue blink: waiting for the Pi. Green blip: sending readings. Magenta
// double blink: an I2C sensor the Pi asked for is not answering; check its
// wiring. (A red 4-fast-4-slow pattern is the board's own crash signal.)

void showStatus(unsigned long now) {
  static unsigned long lastShown = 0;
  if (now - lastShown < 50) return;
  lastShown = now;
  unsigned long phase = now % 2000;
  bool red = false;
  bool green = false;
  bool blue = false;
  if (protocolMode == 0) {
    blue = phase < 100;
  } else {
    bool silent = false;
    for (int index = 0; index < streamCount; index++) {
      if (!streams[index].ok) silent = true;
    }
    if (silent) red = blue = phase < 150 || (phase >= 300 && phase < 450);
    else green = phase < 100;
  }
  // The GIGA's RGB LED lights when its pin is LOW.
  digitalWrite(LEDR, red ? LOW : HIGH);
  digitalWrite(LEDG, green ? LOW : HIGH);
  digitalWrite(LEDB, blue ? LOW : HIGH);
}

// ------------------------------------------------------------------- main

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  Wire.begin();
  Wire.setClock(BUS_CLOCK_HZ);
  pinMode(LEDR, OUTPUT);
  pinMode(LEDG, OUTPUT);
  pinMode(LEDB, OUTPUT);
}

void loop() {
  unsigned long now = millis();
  readCommands();
  if (protocolMode == 3 && now - lastReading >= interval) {
    lastReading = now;
    for (int index = 0; index < streamCount; index++) {
      I2cStream &stream = streams[index];
      stream.ok = busRead(stream.address, stream.reg, stream.data, stream.length);
    }
    sendReadings(millis());  // the clock the Pi measures its intervals with
  } else if (protocolMode == 1 && now - lastReading >= LEGACY_INTERVAL_MS) {
    lastReading = now;
    sendLegacyReadings();
  } else if (protocolMode == 0 && now - lastHello >= HELLO_INTERVAL_MS) {
    lastHello = now;
    sendHello();
  }
  showStatus(now);
}

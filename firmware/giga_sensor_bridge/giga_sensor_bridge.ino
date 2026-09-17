/* MotionModule sensor bridge for the Arduino GIGA R1 WiFi.

   The GIGA is the robot's sensor extender. It reads digital pins as 1 or 0,
   analog pins as numbers from 0 to 4095, and does the IMU maths itself, then
   streams everything to the Raspberry Pi over its USB cable. The Pi decides
   what to read: sensors.py in the robot project lists the pins and IMUs, and
   MotionModule sends that list every time it connects. One copy of this
   sketch serves every robot, and changing sensors never means reflashing.

   No Arduino IDE is needed. With the GIGA plugged into the Pi, run

       motionmodule giga flash

   or press Install firmware under Debug. The Pi flashes the prebuilt copy of
   this sketch, firmware/giga_sensor_bridge.bin. The IDE still works: install
   "Arduino Mbed OS Giga Boards", pick Arduino Giga R1, and upload.

   IMUs connect to SDA 20 and SCL 21, powered from 3.3V, and need no library:
     BNO055 9-axis (Adafruit 4646)                     0x28, or 0x29 with ADR high
     ISM330DHCX 6-axis (Adafruit 4502), LSM6DSOX (Adafruit 4438),
       LSM6DSO, LSM6DS3TR-C                              0x6A, or 0x6B
   Mount them flat, parts side up. Yaw counts up as the robot turns
   counter-clockwise seen from above, pitch as its front rises, and roll as its
   right side dips.

   Every message is one line. From the Pi:
     MM2 CONFIG <id> <pins or -> <imus or ->   MM2 CONFIG 7 A0:A,D22:U BNO055@28,LSM6@6A
     MM2 CALIBRATE      measure the 6-axis gyro bias again; keep the robot still
     MM2 HELLO          report the firmware version
     MM1 CONFIG <pins>  the original pins-only protocol, still understood
   Pin modes: A analog, D digital, U digital with pull-up, N with pull-down.
   BNO055 options: :IMU (default, ignores the magnetometer) or :NDOF (compass).
   Back to the Pi: JSON objects tagged "protocol":"motionmodule-sensor-v2".
*/

#include <Wire.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char BRIDGE_VERSION[] = "2.0.0";
const char BRIDGE_BOARD[] = "arduino_giga_r1_wifi";

constexpr int MAX_INPUTS = 20;
constexpr int MAX_IMUS = 2;
constexpr unsigned long STREAM_INTERVAL_MS = 20;          // 50 readings a second
constexpr unsigned long LEGACY_STREAM_INTERVAL_MS = 100;  // the original sketch's pace
constexpr unsigned long HELLO_INTERVAL_MS = 1000;
constexpr unsigned long RETRY_INTERVAL_MS = 2000;         // look again for a missing IMU
constexpr unsigned long BUS_CLOCK_HZ = 400000;
constexpr int BUS_FAILURE_LIMIT = 10;
constexpr float DEGREES_PER_RADIAN = 57.2957795f;

// Types come before any function: the Arduino build adds a declaration of
// every function above the first one, and those name these types.

struct OutputLine {
  char text[1400];
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

struct Vec3 {
  float x, y, z;
};

enum class ImuKind : uint8_t { Bno055, Lsm6 };
enum class ImuState : uint8_t { Starting, Calibrating, Ok, Missing, WrongChip, Failed };

struct ImuDevice {
  ImuKind kind;
  uint8_t address;
  bool compass;  // BNO055 NDOF mode

  ImuState state;
  uint8_t step;
  unsigned long stepStart;
  unsigned long stepDelay;
  unsigned long attemptStart;
  uint8_t attempts;
  uint8_t chipId;
  uint8_t failures;
  uint8_t seen[6];  // addresses that did answer while this IMU was missing
  uint8_t seenCount;

  float yaw;    // degrees, counter-clockwise positive, counts full turns
  float rate;   // degrees per second, counter-clockwise positive
  float pitch;  // degrees, front up positive
  float roll;   // degrees, right side down positive
  Vec3 up;      // unit vector pointing up, in the IMU's own axes
  bool hasUp;
  bool calibrated;
  bool moving;  // calibration keeps restarting because the robot moves
  uint8_t levels[4];  // BNO055 calibration: system, gyro, accelerometer, magnetometer

  float heading;  // BNO055 heading as reported: 0-360, clockwise
  bool hasHeading;
  bool hadHeading;
  unsigned long lastRead;
  unsigned long lastStatus;

  unsigned long lastMicros;
  bool hasMicros;
  Vec3 bias;           // gyro reading at rest, degrees per second
  float restingAccel;  // accelerometer magnitude at rest, in counts
  unsigned long windowStart;
  unsigned long windowSamples;
  Vec3 gyroSum, gyroLow, gyroHigh, accelSum;
};

ImuDevice imus[MAX_IMUS];
int imuCount = 0;

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

// Two decimals without printf's %f, which the board's C library leaves out.
void lineAddHundredths(OutputLine &line, float value) {
  if (value != value || value > 1.0e7f || value < -1.0e7f) {
    lineAdd(line, "null");
    return;
  }
  long scaled = (long)(value * 100.0f + (value < 0 ? -0.5f : 0.5f));
  unsigned long magnitude = scaled < 0 ? (unsigned long)(-scaled) : (unsigned long)scaled;
  lineAdd(line, "%s%lu.%02lu", scaled < 0 ? "-" : "", magnitude / 100UL, magnitude % 100UL);
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

bool busWrite(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

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

bool busAnswers(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

int16_t int16At(const uint8_t *data, size_t index) {
  return (int16_t)(uint16_t)(data[index] | (data[index + 1] << 8));
}

// ----------------------------------------------------------------- vectors

Vec3 vecAdd(const Vec3 &a, const Vec3 &b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 vecSub(const Vec3 &a, const Vec3 &b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 vecScale(const Vec3 &a, float k) { return {a.x * k, a.y * k, a.z * k}; }
float vecDot(const Vec3 &a, const Vec3 &b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
float vecLength(const Vec3 &a) { return sqrt(vecDot(a, a)); }

Vec3 vecCross(const Vec3 &a, const Vec3 &b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}

// ------------------------------------------------------------------- IMUs

const uint8_t KNOWN_ADDRESSES[] = {0x28, 0x29, 0x4A, 0x4B, 0x6A, 0x6B};

const char *stateName(ImuState state) {
  switch (state) {
    case ImuState::Starting: return "starting";
    case ImuState::Calibrating: return "calibrating";
    case ImuState::Ok: return "ok";
    case ImuState::Missing: return "missing";
    case ImuState::WrongChip: return "wrong-chip";
    case ImuState::Failed: return "failed";
  }
  return "failed";
}

// Reads "BNO055@28:IMU,LSM6@6A" into devices. Returns how many, or -1.
int parseImus(const char *text, ImuDevice *devices) {
  if (strcmp(text, "-") == 0) return 0;
  int count = 0;
  const char *cursor = text;
  while (*cursor != '\0') {
    if (count == MAX_IMUS) return -1;
    const char *comma = strchr(cursor, ',');
    size_t length = comma != nullptr ? (size_t)(comma - cursor) : strlen(cursor);
    char item[24];
    if (length == 0 || length >= sizeof(item)) return -1;
    memcpy(item, cursor, length);
    item[length] = '\0';
    char *at = strchr(item, '@');
    if (at == nullptr) return -1;
    *at = '\0';
    char *options = strchr(at + 1, ':');
    if (options != nullptr) *options++ = '\0';
    char *end = nullptr;
    long address = strtol(at + 1, &end, 16);
    if (end == at + 1 || *end != '\0' || address < 0x08 || address > 0x77) return -1;
    ImuDevice device;
    memset(&device, 0, sizeof(device));
    if (strcmp(item, "BNO055") == 0) device.kind = ImuKind::Bno055;
    else if (strcmp(item, "LSM6") == 0) device.kind = ImuKind::Lsm6;
    else return -1;
    device.address = (uint8_t)address;
    if (options != nullptr) {
      if (device.kind == ImuKind::Bno055 && strcmp(options, "NDOF") == 0) device.compass = true;
      else if (strcmp(options, "IMU") != 0) return -1;
    }
    devices[count++] = device;
    if (comma == nullptr) break;
    cursor = comma + 1;
  }
  return count;
}

void waitStep(ImuDevice &imu, unsigned long now, uint8_t step, unsigned long milliseconds) {
  imu.step = step;
  imu.stepStart = now;
  imu.stepDelay = milliseconds;
}

void beginAttempt(ImuDevice &imu, unsigned long now) {
  imu.state = ImuState::Starting;
  imu.attemptStart = now;
  imu.failures = 0;
  imu.calibrated = false;
  imu.hasHeading = false;
  imu.hasMicros = false;
  if (imu.attempts < 255) imu.attempts++;
  waitStep(imu, now, 0, 0);
}

void markAbsent(ImuDevice &imu, ImuState state, unsigned long now) {
  imu.state = state;
  imu.calibrated = false;
  imu.seenCount = 0;
  for (uint8_t address : KNOWN_ADDRESSES) {
    if (imu.seenCount < sizeof(imu.seen) && busAnswers(address)) imu.seen[imu.seenCount++] = address;
  }
  waitStep(imu, now, 0, RETRY_INTERVAL_MS);
}

void markFailed(ImuDevice &imu, unsigned long now) {
  imu.state = ImuState::Failed;
  imu.calibrated = false;
  waitStep(imu, now, 0, RETRY_INTERVAL_MS);
}

void noteFailure(ImuDevice &imu, unsigned long now) {
  if (++imu.failures >= BUS_FAILURE_LIMIT) markFailed(imu, now);
}

// A sensor powered up with the GIGA can take most of a second to answer.
bool stillBooting(const ImuDevice &imu, unsigned long now) {
  unsigned long patience = imu.kind == ImuKind::Bno055 ? 1500UL : 300UL;
  return imu.attempts <= 1 && now - imu.attemptStart < patience;
}

void tiltFromUp(ImuDevice &imu) {
  imu.pitch = atan2(imu.up.y, sqrt(imu.up.x * imu.up.x + imu.up.z * imu.up.z)) * DEGREES_PER_RADIAN;
  imu.roll = atan2(-imu.up.x, imu.up.z) * DEGREES_PER_RADIAN;
}

// ---------------------------------------------------- BNO055, 9-axis fusion
// Registers from Bosch's BNO055 datasheet (BST-BNO055-DS000).

constexpr uint8_t BNO_CHIP_ID = 0x00;
constexpr uint8_t BNO_EXPECTED_ID = 0xA0;
constexpr uint8_t BNO_PAGE = 0x07;
constexpr uint8_t BNO_GYRO_DATA = 0x14;     // gyro x, y, z, then heading, roll, pitch
constexpr uint8_t BNO_GRAVITY_DATA = 0x2E;  // gravity x, y, z, temperature, calibration
constexpr uint8_t BNO_SYSTEM_STATUS = 0x39;
constexpr uint8_t BNO_UNIT_SELECT = 0x3B;
constexpr uint8_t BNO_MODE = 0x3D;
constexpr uint8_t BNO_POWER = 0x3E;
constexpr uint8_t BNO_TRIGGER = 0x3F;
constexpr uint8_t BNO_MODE_CONFIG = 0x00;
constexpr uint8_t BNO_MODE_IMU = 0x08;   // gyro and accelerometer: motors cannot disturb it
constexpr uint8_t BNO_MODE_NDOF = 0x0C;  // adds the magnetometer for a compass heading

void startBno055(ImuDevice &imu, unsigned long now) {
  uint8_t value = 0;
  uint8_t mode = imu.compass ? BNO_MODE_NDOF : BNO_MODE_IMU;
  switch (imu.step) {
    case 0:  // is anything there, and is it a BNO055?
      if (!busRead(imu.address, BNO_CHIP_ID, &value, 1)) {
        if (stillBooting(imu, now)) return waitStep(imu, now, 0, 50);
        return markAbsent(imu, ImuState::Missing, now);
      }
      imu.chipId = value;
      if (value != BNO_EXPECTED_ID) {
        if (stillBooting(imu, now)) return waitStep(imu, now, 0, 50);
        return markAbsent(imu, ImuState::WrongChip, now);
      }
      if (!busWrite(imu.address, BNO_MODE, BNO_MODE_CONFIG)) break;
      return waitStep(imu, now, 1, 25);
    case 1:  // restart it, so a sensor left mid-mode starts clean
      // It can reset before acknowledging this write, so the answer is ignored.
      busWrite(imu.address, BNO_TRIGGER, 0x20);
      return waitStep(imu, now, 2, 650);
    case 2:  // wait for it to come back
      if (busRead(imu.address, BNO_CHIP_ID, &value, 1) && value == BNO_EXPECTED_ID) {
        return waitStep(imu, now, 3, 50);
      }
      if (now - imu.attemptStart > 3000) break;
      return waitStep(imu, now, 2, 20);
    case 3:  // normal power; degrees and degrees per second; the board's 32 kHz crystal
      if (!busWrite(imu.address, BNO_PAGE, 0) || !busWrite(imu.address, BNO_POWER, 0) ||
          !busWrite(imu.address, BNO_UNIT_SELECT, 0) || !busWrite(imu.address, BNO_TRIGGER, 0x80)) {
        break;
      }
      return waitStep(imu, now, 4, 20);
    case 4:
      if (!busWrite(imu.address, BNO_MODE, mode)) break;
      return waitStep(imu, now, 5, 30);
    case 5:
      if (!busRead(imu.address, BNO_MODE, &value, 1) || (value & 0x0F) != mode) break;
      imu.state = ImuState::Ok;
      imu.lastRead = now - 10;
      imu.lastStatus = now;
      return;
  }
  markFailed(imu, now);
}

void readBno055(ImuDevice &imu, unsigned long now) {
  if (now - imu.lastRead < 10) return;  // it fuses 100 times a second
  imu.lastRead = now;
  uint8_t motion[12];
  uint8_t gravity[8];
  if (!busRead(imu.address, BNO_GYRO_DATA, motion, sizeof(motion)) ||
      !busRead(imu.address, BNO_GRAVITY_DATA, gravity, sizeof(gravity))) {
    return noteFailure(imu, now);
  }
  imu.failures = 0;

  Vec3 gyro = {int16At(motion, 0) / 16.0f, int16At(motion, 2) / 16.0f, int16At(motion, 4) / 16.0f};
  float heading = (uint16_t)int16At(motion, 6) / 16.0f;
  // Gravity reads +9.8 m/s2 along whichever axis points up.
  Vec3 lift = {int16At(gravity, 0) / 100.0f, int16At(gravity, 2) / 100.0f, int16At(gravity, 4) / 100.0f};
  float strength = vecLength(lift);
  if (strength > 4.0f) {
    imu.up = vecScale(lift, 1.0f / strength);
    imu.hasUp = true;
  } else if (!imu.hasUp) {
    imu.up = {0.0f, 0.0f, 1.0f};
  }

  // Its heading grows clockwise; yaw grows counter-clockwise and keeps
  // counting past a full turn. A compass heading is absolute, so it is taken
  // as it is; a relative one carries on from where it was before a restart.
  if (!imu.hasHeading) {
    if (imu.compass || !imu.hadHeading) imu.yaw = -heading;
    imu.hasHeading = imu.hadHeading = true;
  } else {
    float change = heading - imu.heading;
    if (change > 180.0f) change -= 360.0f;
    else if (change < -180.0f) change += 360.0f;
    imu.yaw -= change;
  }
  imu.heading = heading;
  imu.rate = vecDot(gyro, imu.up);
  tiltFromUp(imu);

  uint8_t calibration = gravity[7];
  imu.levels[0] = (calibration >> 6) & 3;
  imu.levels[1] = (calibration >> 4) & 3;
  imu.levels[2] = (calibration >> 2) & 3;
  imu.levels[3] = calibration & 3;
  imu.calibrated = imu.compass ? imu.levels[0] == 3 : imu.levels[1] == 3;

  if (now - imu.lastStatus >= 500) {
    imu.lastStatus = now;
    uint8_t status[2];
    // Status 1 is the BNO055's own system error: start it again.
    if (busRead(imu.address, BNO_SYSTEM_STATUS, status, sizeof(status)) && status[0] == 1) {
      markFailed(imu, now);
    }
  }
}

// ------------------------------------------ LSM6 family, 6-axis, fused here
// Registers shared by ST's ISM330DHCX, LSM6DSOX, LSM6DSO, and LSM6DS3TR-C.

constexpr uint8_t LSM_WHO_AM_I = 0x0F;
constexpr uint8_t LSM_CTRL1_XL = 0x10;
constexpr uint8_t LSM_CTRL2_G = 0x11;
constexpr uint8_t LSM_CTRL3_C = 0x12;
constexpr uint8_t LSM_CTRL9_XL = 0x18;
constexpr uint8_t LSM_STATUS = 0x1E;
constexpr uint8_t LSM_OUTPUT = 0x22;              // gyro x, y, z, then accelerometer x, y, z
constexpr float LSM_DPS_PER_COUNT = 0.070f;       // at the +-2000 degrees per second range
constexpr unsigned long LSM_SAMPLE_MS = 2;        // the gyro updates 416 times a second
constexpr unsigned long STILL_WINDOW_MS = 1000;
constexpr float STILL_SPREAD_DPS = 1.5f;          // how much a resting gyro may wobble
constexpr float STILL_RATE_DPS = 10.0f;           // what a resting gyro may read: a steady turn wobbles too little
constexpr float BIAS_TRACK_LIMIT_DPS = 0.2f;      // never mistake a slow turn for bias
constexpr float UP_TIME_CONSTANT_S = 1.0f;

bool isLsm6Id(uint8_t id) { return id == 0x69 || id == 0x6A || id == 0x6B || id == 0x6C; }

void resetWindow(ImuDevice &imu, unsigned long now) {
  imu.windowStart = now;
  imu.windowSamples = 0;
  imu.gyroSum = {0.0f, 0.0f, 0.0f};
  imu.accelSum = {0.0f, 0.0f, 0.0f};
  imu.gyroLow = {1.0e9f, 1.0e9f, 1.0e9f};
  imu.gyroHigh = {-1.0e9f, -1.0e9f, -1.0e9f};
}

float smaller(float a, float b) { return a < b ? a : b; }
float larger(float a, float b) { return a > b ? a : b; }

void addToWindow(ImuDevice &imu, const Vec3 &gyro, const Vec3 &accel) {
  imu.windowSamples++;
  imu.gyroSum = vecAdd(imu.gyroSum, gyro);
  imu.accelSum = vecAdd(imu.accelSum, accel);
  imu.gyroLow = {smaller(imu.gyroLow.x, gyro.x), smaller(imu.gyroLow.y, gyro.y), smaller(imu.gyroLow.z, gyro.z)};
  imu.gyroHigh = {larger(imu.gyroHigh.x, gyro.x), larger(imu.gyroHigh.y, gyro.y), larger(imu.gyroHigh.z, gyro.z)};
}

bool windowIsStill(const ImuDevice &imu) {
  if (imu.windowSamples < 50) return false;
  Vec3 mean = vecScale(imu.gyroSum, 1.0f / (float)imu.windowSamples);
  return imu.gyroHigh.x - imu.gyroLow.x < STILL_SPREAD_DPS &&
         imu.gyroHigh.y - imu.gyroLow.y < STILL_SPREAD_DPS &&
         imu.gyroHigh.z - imu.gyroLow.z < STILL_SPREAD_DPS &&
         fabs(mean.x) < STILL_RATE_DPS && fabs(mean.y) < STILL_RATE_DPS && fabs(mean.z) < STILL_RATE_DPS;
}

void startCalibration(ImuDevice &imu, unsigned long now) {
  imu.state = ImuState::Calibrating;
  imu.calibrated = false;
  imu.hasMicros = false;
  resetWindow(imu, now);
}

void startLsm6(ImuDevice &imu, unsigned long now) {
  uint8_t value = 0;
  switch (imu.step) {
    case 0:
      if (!busRead(imu.address, LSM_WHO_AM_I, &value, 1)) {
        if (stillBooting(imu, now)) return waitStep(imu, now, 0, 20);
        return markAbsent(imu, ImuState::Missing, now);
      }
      imu.chipId = value;
      if (!isLsm6Id(value)) return markAbsent(imu, ImuState::WrongChip, now);
      busWrite(imu.address, LSM_CTRL3_C, 0x01);  // software reset; step 1 checks it happened
      return waitStep(imu, now, 1, 20);
    case 1:
      if (!busRead(imu.address, LSM_CTRL3_C, &value, 1)) break;
      if (value & 0x01) {
        if (now - imu.attemptStart > 500) break;
        return waitStep(imu, now, 1, 10);
      }
      // Block data update keeps each reading's two bytes from the same sample.
      if (!busWrite(imu.address, LSM_CTRL3_C, 0x44)) break;
      // Bit 1 of CTRL9_XL switches I3C off on the LSM6DSOX and LSM6DSO, and is
      // DEVICE_CONF, which ST says to set, on the ISM330DHCX.
      if ((imu.chipId == 0x6C || imu.chipId == 0x6B) &&
          (!busRead(imu.address, LSM_CTRL9_XL, &value, 1) ||
           !busWrite(imu.address, LSM_CTRL9_XL, value | 0x02))) {
        break;
      }
      if (!busWrite(imu.address, LSM_CTRL1_XL, 0x48) ||  // accelerometer 104 Hz, +-4 g
          !busWrite(imu.address, LSM_CTRL2_G, 0x6C)) {   // gyro 416 Hz, +-2000 dps
        break;
      }
      return waitStep(imu, now, 2, 100);  // let the gyro settle
    case 2:
      return startCalibration(imu, now);
  }
  markFailed(imu, now);
}

void readLsm6(ImuDevice &imu, unsigned long now) {
  if (now - imu.lastRead < LSM_SAMPLE_MS) return;
  imu.lastRead = now;
  uint8_t status = 0;
  if (!busRead(imu.address, LSM_STATUS, &status, 1)) return noteFailure(imu, now);
  imu.failures = 0;
  if ((status & 0x02) == 0) return;  // no new gyro sample yet
  uint8_t data[12];
  if (!busRead(imu.address, LSM_OUTPUT, data, sizeof(data))) return noteFailure(imu, now);

  unsigned long microsecond = micros();
  float seconds = imu.hasMicros ? (microsecond - imu.lastMicros) * 1.0e-6f : 0.0f;
  if (seconds > 0.05f) seconds = 0.05f;  // a long pause is not a long turn
  imu.lastMicros = microsecond;
  imu.hasMicros = true;

  Vec3 gyro = {int16At(data, 0) * LSM_DPS_PER_COUNT, int16At(data, 2) * LSM_DPS_PER_COUNT,
               int16At(data, 4) * LSM_DPS_PER_COUNT};
  Vec3 accel = {(float)int16At(data, 6), (float)int16At(data, 8), (float)int16At(data, 10)};
  addToWindow(imu, gyro, accel);

  if (imu.state == ImuState::Calibrating) {
    if (now - imu.windowStart < STILL_WINDOW_MS) return;
    if (windowIsStill(imu)) {
      float samples = (float)imu.windowSamples;
      Vec3 resting = vecScale(imu.accelSum, 1.0f / samples);
      imu.bias = vecScale(imu.gyroSum, 1.0f / samples);
      imu.restingAccel = vecLength(resting);
      if (imu.restingAccel > 0.0f) {
        imu.up = vecScale(resting, 1.0f / imu.restingAccel);
        imu.hasUp = true;
      }
      tiltFromUp(imu);
      imu.state = ImuState::Ok;
      imu.calibrated = true;
      imu.moving = false;
    } else {
      imu.moving = true;
    }
    return resetWindow(imu, now);
  }

  // Tilt: carry the up direction along with the gyro, and lean it gently
  // toward the accelerometer whenever that reads about one g.
  Vec3 turn = vecSub(gyro, imu.bias);
  Vec3 spin = vecScale(turn, 1.0f / DEGREES_PER_RADIAN);
  imu.up = vecSub(imu.up, vecScale(vecCross(spin, imu.up), seconds));
  float strength = vecLength(accel);
  if (imu.restingAccel > 0.0f && fabs(strength - imu.restingAccel) < 0.1f * imu.restingAccel) {
    float blend = seconds / UP_TIME_CONSTANT_S;
    if (blend > 1.0f) blend = 1.0f;
    imu.up = vecAdd(imu.up, vecScale(vecSub(vecScale(accel, 1.0f / strength), imu.up), blend));
  }
  float length = vecLength(imu.up);
  imu.up = length > 0.0f ? vecScale(imu.up, 1.0f / length) : Vec3{0.0f, 0.0f, 1.0f};

  // Heading: the turn about the up direction, so tilting never reads as turning.
  imu.rate = vecDot(turn, imu.up);
  imu.yaw += imu.rate * seconds;
  tiltFromUp(imu);

  // A resting robot keeps re-measuring the gyro's bias as it warms up.
  if (now - imu.windowStart >= STILL_WINDOW_MS) {
    if (windowIsStill(imu)) {
      Vec3 correction = vecSub(vecScale(imu.gyroSum, 1.0f / (float)imu.windowSamples), imu.bias);
      if (fabs(correction.x) < BIAS_TRACK_LIMIT_DPS && fabs(correction.y) < BIAS_TRACK_LIMIT_DPS &&
          fabs(correction.z) < BIAS_TRACK_LIMIT_DPS) {
        imu.bias = vecAdd(imu.bias, vecScale(correction, 0.2f));
      }
    }
    resetWindow(imu, now);
  }
}

void updateImu(ImuDevice &imu, unsigned long now) {
  switch (imu.state) {
    case ImuState::Missing:
    case ImuState::WrongChip:
    case ImuState::Failed:
      if (now - imu.stepStart >= imu.stepDelay) beginAttempt(imu, now);
      return;
    case ImuState::Starting:
      if (now - imu.stepStart < imu.stepDelay) return;
      if (imu.kind == ImuKind::Bno055) startBno055(imu, now);
      else startLsm6(imu, now);
      return;
    case ImuState::Calibrating:
    case ImuState::Ok:
      if (imu.kind == ImuKind::Bno055) readBno055(imu, now);
      else readLsm6(imu, now);
      return;
  }
}

// ---------------------------------------------------------------- messages

char activeConfig[200] = "";
long configId = -1;
int streamMode = 0;  // 0 until the Pi configures it, 1 original protocol, 2 current
unsigned long lastStream = 0;
unsigned long lastHello = 0;
unsigned long sequence = 0;

void eventStart(const char *event) {
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"motionmodule-sensor-v2\",\"event\":\"%s\",\"firmware\":\"%s\",\"board\":\"%s\"",
          event, BRIDGE_VERSION, BRIDGE_BOARD);
}

void sendHello() {
  eventStart("hello");
  lineAdd(output, "}");
  lineSend(output);
}

void sendConfigured() {
  eventStart("configured");
  lineAdd(output, ",\"config\":%ld,\"pins\":%d,\"imus\":%d}", configId, inputCount, imuCount);
  lineSend(output);
}

void sendError(const char *message) {
  eventStart("error");
  lineAdd(output, ",\"message\":\"%s\"}", message);
  lineSend(output);
}

void sendReadings(unsigned long now) {
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"motionmodule-sensor-v2\",\"firmware\":\"%s\",\"config\":%ld,\"seq\":%lu,\"ms\":%lu,\"values\":{",
          BRIDGE_VERSION, configId, ++sequence, now);
  for (int index = 0; index < inputCount; index++) {
    lineAdd(output, "%s\"%s\":%d", index ? "," : "", inputs[index].label, readPin(inputs[index]));
  }
  lineAdd(output, "},\"imus\":[");
  for (int index = 0; index < imuCount; index++) {
    const ImuDevice &imu = imus[index];
    lineAdd(output, "%s{\"type\":\"%s\",\"addr\":%u,\"state\":\"%s\",\"id\":%u", index ? "," : "",
            imu.kind == ImuKind::Bno055 ? "bno055" : "lsm6", (unsigned)imu.address, stateName(imu.state),
            (unsigned)imu.chipId);
    if (imu.state == ImuState::Ok) {
      lineAdd(output, ",\"cal\":%d,\"yaw\":", imu.calibrated ? 1 : 0);
      lineAddHundredths(output, imu.yaw);
      lineAdd(output, ",\"rate\":");
      lineAddHundredths(output, imu.rate);
      lineAdd(output, ",\"pitch\":");
      lineAddHundredths(output, imu.pitch);
      lineAdd(output, ",\"roll\":");
      lineAddHundredths(output, imu.roll);
      if (imu.kind == ImuKind::Bno055) {
        lineAdd(output, ",\"levels\":[%u,%u,%u,%u]", (unsigned)imu.levels[0], (unsigned)imu.levels[1],
                (unsigned)imu.levels[2], (unsigned)imu.levels[3]);
      }
    }
    if (imu.state == ImuState::Calibrating && imu.moving) lineAdd(output, ",\"moving\":1");
    if (imu.state == ImuState::Missing || imu.state == ImuState::WrongChip) {
      lineAdd(output, ",\"seen\":[");
      for (uint8_t item = 0; item < imu.seenCount; item++) {
        lineAdd(output, "%s%u", item ? "," : "", (unsigned)imu.seen[item]);
      }
      lineAdd(output, "]");
    }
    lineAdd(output, "}");
  }
  lineAdd(output, "]}");
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

void handleConfig(const char *arguments, unsigned long now) {
  // The same sensors again, as when the Pi restarts: keep the IMUs running.
  if (streamMode == 2 && strcmp(arguments, activeConfig) == 0) return sendConfigured();
  char copy[sizeof(activeConfig)];
  if (strlen(arguments) >= sizeof(copy)) return sendError("config is too long");
  strcpy(copy, arguments);
  char *idText = strtok(copy, " ");
  char *pinText = strtok(nullptr, " ");
  char *imuText = strtok(nullptr, " ");
  if (idText == nullptr || pinText == nullptr || imuText == nullptr || strtok(nullptr, " ") != nullptr) {
    return sendError("expected MM2 CONFIG <id> <pins> <imus>");
  }
  char *end = nullptr;
  long id = strtol(idText, &end, 10);
  if (*end != '\0' || id < 0) return sendError("config id must be a whole number");
  InputPin pins[MAX_INPUTS];
  int pinCount = parsePins(pinText, pins);
  if (pinCount < 0) return sendError("pin list not understood");
  ImuDevice devices[MAX_IMUS];
  int deviceCount = parseImus(imuText, devices);
  if (deviceCount < 0) return sendError("IMU list not understood");

  applyPins(pins, pinCount);
  for (int index = 0; index < deviceCount; index++) {
    imus[index] = devices[index];
    beginAttempt(imus[index], now);
  }
  imuCount = deviceCount;
  configId = id;
  strcpy(activeConfig, arguments);
  streamMode = 2;
  lastStream = now;
  sendConfigured();
}

void handleLegacyConfig(const char *declaration) {
  InputPin pins[MAX_INPUTS];
  int count = parsePins(declaration, pins);
  applyPins(pins, count < 0 ? 0 : count);
  imuCount = 0;
  activeConfig[0] = '\0';
  configId = -1;
  streamMode = 1;
  lineStart(output);
  lineAdd(output, "{\"protocol\":\"motionmodule-sensor-v1\",\"event\":\"configured\",\"firmware\":\"%s\"}",
          BRIDGE_VERSION);
  lineSend(output);
}

void recalibrate(unsigned long now) {
  for (int index = 0; index < imuCount; index++) {
    ImuDevice &imu = imus[index];
    if (imu.kind == ImuKind::Lsm6 && (imu.state == ImuState::Ok || imu.state == ImuState::Calibrating)) {
      startCalibration(imu, now);
    }
  }
}

void handleLine(char *text, unsigned long now) {
  size_t length = strlen(text);
  while (length > 0 && (text[length - 1] == ' ' || text[length - 1] == '\t')) text[--length] = '\0';
  while (*text == ' ' || *text == '\t') text++;
  if (strncmp(text, "MM2 CONFIG ", 11) == 0) handleConfig(text + 11, now);
  else if (strcmp(text, "MM2 CALIBRATE") == 0) recalibrate(now);
  else if (strcmp(text, "MM2 HELLO") == 0) sendHello();
  else if (strncmp(text, "MM1 CONFIG ", 11) == 0) handleLegacyConfig(text + 11);
}

char command[256];
size_t commandLength = 0;
bool commandTooLong = false;

void readCommands(unsigned long now) {
  for (int budget = 512; budget > 0 && Serial.available() > 0; budget--) {
    int received = Serial.read();
    if (received < 0) break;
    if (received == '\r') continue;
    if (received == '\n') {
      command[commandLength] = '\0';
      if (!commandTooLong) handleLine(command, now);
      commandLength = 0;
      commandTooLong = false;
    } else if (commandLength + 1 < sizeof(command)) {
      command[commandLength++] = (char)received;
    } else {
      commandTooLong = true;
    }
  }
}

// ------------------------------------------------------------- status LED
// Blue blink: waiting for the Pi. Green blip: streaming. Cyan: an IMU is
// starting or calibrating. Magenta double blink: an IMU is missing; check
// its wiring. (A red 4-fast-4-slow pattern is the board's own crash signal.)

void showStatus(unsigned long now) {
  static unsigned long lastShown = 0;
  if (now - lastShown < 50) return;
  lastShown = now;
  unsigned long phase = now % 2000;
  bool red = false;
  bool green = false;
  bool blue = false;
  if (streamMode == 0) {
    blue = phase < 100;
  } else {
    bool problem = false;
    bool busy = false;
    for (int index = 0; index < imuCount; index++) {
      ImuState state = imus[index].state;
      if (state == ImuState::Missing || state == ImuState::WrongChip || state == ImuState::Failed) problem = true;
      else if (state != ImuState::Ok) busy = true;
    }
    if (problem) red = blue = phase < 150 || (phase >= 300 && phase < 450);
    else if (busy) green = blue = phase % 500 < 250;
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
  readCommands(now);
  for (int index = 0; index < imuCount; index++) updateImu(imus[index], now);
  if (streamMode == 2 && now - lastStream >= STREAM_INTERVAL_MS) {
    lastStream = now;
    sendReadings(now);
  } else if (streamMode == 1 && now - lastStream >= LEGACY_STREAM_INTERVAL_MS) {
    lastStream = now;
    sendLegacyReadings();
  } else if (streamMode == 0 && now - lastHello >= HELLO_INTERVAL_MS) {
    lastHello = now;
    sendHello();
  }
  showStatus(now);
}

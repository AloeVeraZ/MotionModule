/* MotionModule Sensor Bridge v1 for Arduino GIGA R1 WiFi.

   Flash this once with Arduino IDE. MotionModule finds the GIGA by USB,
   sends the pin declarations from dashboard.py after every reconnect, and
   receives newline-delimited JSON sensor samples. No extra library is needed.
*/

struct InputPin {
  String label;
  int number;
  char mode;
};

constexpr int MAX_INPUTS = 20;
InputPin inputs[MAX_INPUTS];
int inputCount = 0;
unsigned long lastSample = 0;

int resolvePin(const String &label, char mode) {
  if (label.length() < 2) return -1;
  int number = label.substring(1).toInt();
  if (mode == 'A') {
    const int analogPins[] = {A0, A1, A2, A3, A4, A5, A6, A7};
    return number >= 0 && number < 8 ? analogPins[number] : -1;
  }
  return number >= 0 && number <= 75 ? number : -1;
}

void configureInputs(String declaration) {
  inputCount = 0;
  int start = 0;
  while (start < declaration.length() && inputCount < MAX_INPUTS) {
    int comma = declaration.indexOf(',', start);
    if (comma < 0) comma = declaration.length();
    String item = declaration.substring(start, comma);
    int colon = item.indexOf(':');
    if (colon > 0 && colon + 1 < item.length()) {
      String label = item.substring(0, colon);
      char mode = item.charAt(colon + 1);
      int number = resolvePin(label, mode);
      if (number >= 0 && (mode == 'A' || mode == 'D' || mode == 'U' || mode == 'N')) {
        inputs[inputCount++] = {label, number, mode};
        if (mode == 'U') pinMode(number, INPUT_PULLUP);
        else if (mode == 'N') pinMode(number, INPUT_PULLDOWN);
        else if (mode == 'D') pinMode(number, INPUT);
      }
    }
    start = comma + 1;
  }
  Serial.println("{\"protocol\":\"motionmodule-sensor-v1\",\"event\":\"configured\"}");
}

void readCommands() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  const String prefix = "MM1 CONFIG ";
  if (line.startsWith(prefix)) configureInputs(line.substring(prefix.length()));
}

void emitSample() {
  Serial.print("{\"protocol\":\"motionmodule-sensor-v1\",\"board\":\"arduino_giga_r1_wifi\",\"values\":{");
  for (int index = 0; index < inputCount; index++) {
    if (index) Serial.print(',');
    Serial.print('\"');
    Serial.print(inputs[index].label);
    Serial.print("\":");
    Serial.print(inputs[index].mode == 'A' ? analogRead(inputs[index].number) : digitalRead(inputs[index].number));
  }
  Serial.println("}}");
}

void setup() {
  analogReadResolution(12);
  Serial.begin(115200);
}

void loop() {
  readCommands();
  unsigned long now = millis();
  if (now - lastSample >= 100) {
    lastSample = now;
    emitSample();
  }
}

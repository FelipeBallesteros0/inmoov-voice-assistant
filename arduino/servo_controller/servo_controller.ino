#include <Servo.h>

const int SERVO_PIN = 11;
const long BAUD_RATE = 115200;

Servo servo;
String inputLine = "";

void setup() {
  Serial.begin(BAUD_RATE);
  servo.attach(SERVO_PIN);
  servo.write(90);
  inputLine.reserve(32);
  Serial.println("READY");
}

void loop() {
  while (Serial.available() > 0) {
    char ch = static_cast<char>(Serial.read());
    if (ch == '\r') {
      continue;
    }
    if (ch == '\n') {
      processLine(inputLine);
      inputLine = "";
      continue;
    }
    if (inputLine.length() < 31) {
      inputLine += ch;
    } else {
      inputLine = "";
      Serial.println("ERR line_too_long");
    }
  }
}

void processLine(String line) {
  line.trim();
  if (!line.startsWith("SERVO ")) {
    Serial.println("ERR unknown_command");
    return;
  }

  String angleText = line.substring(6);
  angleText.trim();
  if (angleText.length() == 0) {
    Serial.println("ERR missing_angle");
    return;
  }

  for (unsigned int i = 0; i < angleText.length(); i++) {
    if (!isDigit(angleText.charAt(i))) {
      Serial.println("ERR invalid_angle");
      return;
    }
  }

  int angle = angleText.toInt();
  if (angle < 0 || angle > 180) {
    Serial.println("ERR angle_out_of_range");
    return;
  }

  servo.write(angle);
  Serial.print("OK ");
  Serial.println(angle);
}

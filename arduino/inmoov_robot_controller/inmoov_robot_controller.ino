#include <Servo.h>

const long BAUD_RATE = 115200;
const int JOINT_COUNT = 21;
const int MAX_COMMAND_LENGTH = 220;
const int JOINT_MOVE_STEPS = 45;
const int JOINT_MOVE_DELAY_MS = 25;

const char* JOINT_NAMES[JOINT_COUNT] = {
  "lat_izq", "lat_der", "rotor_izq", "rotor_der", "bicep_izq", "bicep_der",
  "cabeza", "mandibula", "cuello", "cuello_izq", "cuello_der",
  "pulgar_izq", "indice_izq", "medio_izq", "anular_izq", "meni_izq",
  "pulgar_der", "indice_der", "medio_der", "anular_der", "meni_der"
};

const int PINS[JOINT_COUNT] = {
  40, 41, 36, 37, 34, 35, 48, 47, 44, 42, 43, 22, 23, 24, 25, 26, 28, 29, 30, 31, 32
};

const int MIN_ANGLE[JOINT_COUNT] = {
  80, 70, 10, 10, 75, 90, 10, 10, 50, 70, 50, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

const int MAX_ANGLE[JOINT_COUNT] = {
  135, 123, 80, 90, 140, 140, 170, 70, 180, 150, 130, 140, 140, 160, 130, 130, 120, 120, 130, 170, 120
};

const int HOME_ANGLE[JOINT_COUNT] = {
  135, 123, 80, 90, 90, 90, 90, 10, 60, 110, 90, 140, 140, 160, 130, 130, 120, 120, 130, 170, 120
};

enum JointIndex {
  LAT_IZQ = 0,
  LAT_DER,
  ROTOR_IZQ,
  ROTOR_DER,
  BICEP_IZQ,
  BICEP_DER,
  CABEZA,
  MANDIBULA,
  CUELLO,
  CUELLO_IZQ,
  CUELLO_DER,
  PULGAR_IZQ,
  INDICE_IZQ,
  MEDIO_IZQ,
  ANULAR_IZQ,
  MENI_IZQ,
  PULGAR_DER,
  INDICE_DER,
  MEDIO_DER,
  ANULAR_DER,
  MENI_DER
};

Servo servos[JOINT_COUNT];
int currentAngle[JOINT_COUNT];
bool attached[JOINT_COUNT];
String inputLine = "";
bool runningRoutine = false;

void setup() {
  Serial.begin(BAUD_RATE);
  inputLine.reserve(MAX_COMMAND_LENGTH);
  initializePositionMemory();
  Serial.println("READY");
}

void loop() {
  readSerialCommands();
}

void initializePositionMemory() {
  for (int i = 0; i < JOINT_COUNT; i++) {
    currentAngle[i] = HOME_ANGLE[i];
    attached[i] = false;
    servos[i].write(currentAngle[i]);
  }
}

void ensureAttached(int joint) {
  if (attached[joint]) {
    return;
  }
  servos[joint].write(currentAngle[joint]);
  servos[joint].attach(PINS[joint]);
  servos[joint].write(currentAngle[joint]);
  attached[joint] = true;
  delay(80);
}

void attachGroup(const int joints[], int count) {
  for (int i = 0; i < count; i++) {
    ensureAttached(joints[i]);
  }
}

int clampAngle(int joint, int angle) {
  return constrain(angle, MIN_ANGLE[joint], MAX_ANGLE[joint]);
}

void writeJoint(int joint, int angle) {
  int safeAngle = clampAngle(joint, angle);
  ensureAttached(joint);
  servos[joint].write(safeAngle);
  currentAngle[joint] = safeAngle;
}

void moveGroup(const int joints[], const int targets[], int count, int steps, int delayMs) {
  attachGroup(joints, count);
  int starts[JOINT_COUNT];
  for (int i = 0; i < count; i++) {
    starts[i] = currentAngle[joints[i]];
  }
  for (int step = 1; step <= steps; step++) {
    for (int i = 0; i < count; i++) {
      int joint = joints[i];
      int target = clampAngle(joint, targets[i]);
      int angle = starts[i] + (target - starts[i]) * step / steps;
      writeJoint(joint, angle);
    }
    delay(delayMs);
  }
}

void moveSingle(int joint, int target, int steps, int delayMs) {
  const int joints[] = { joint };
  const int targets[] = { target };
  moveGroup(joints, targets, 1, steps, delayMs);
}

bool parseInteger(String text, int &value) {
  text.trim();
  if (text.length() == 0) {
    return false;
  }
  int start = 0;
  if (text.charAt(0) == '-') {
    if (text.length() == 1) {
      return false;
    }
    start = 1;
  }
  for (int i = start; i < text.length(); i++) {
    if (!isDigit(text.charAt(i))) {
      return false;
    }
  }
  value = text.toInt();
  return true;
}

bool parseJointPair(String token, int &joint, int &angle, String &error) {
  token.trim();
  int separator = token.indexOf(':');
  if (separator <= 0 || separator == token.length() - 1) {
    error = "bad_joint_command";
    return false;
  }

  String jointText = token.substring(0, separator);
  String angleText = token.substring(separator + 1);
  if (!parseInteger(jointText, joint) || !parseInteger(angleText, angle)) {
    error = "bad_joint_command";
    return false;
  }
  if (joint < 0 || joint >= JOINT_COUNT) {
    error = "unknown_joint";
    return false;
  }
  if (angle < MIN_ANGLE[joint] || angle > MAX_ANGLE[joint]) {
    error = "joint_out_of_range";
    return false;
  }
  return true;
}

bool parseJointCommand(String payload, int joints[], int targets[], int &count, String &error) {
  payload.trim();
  if (payload.length() == 0) {
    error = "bad_joint_command";
    return false;
  }

  bool used[JOINT_COUNT] = { false };
  count = 0;
  while (payload.length() > 0) {
    int space = payload.indexOf(' ');
    String token;
    if (space < 0) {
      token = payload;
      payload = "";
    } else {
      token = payload.substring(0, space);
      payload = payload.substring(space + 1);
    }
    token.trim();
    if (token.length() == 0) {
      continue;
    }
    if (count >= JOINT_COUNT) {
      error = "too_many_joints";
      return false;
    }

    int joint = -1;
    int angle = -1;
    if (!parseJointPair(token, joint, angle, error)) {
      return false;
    }
    if (used[joint]) {
      error = "duplicate_joint";
      return false;
    }

    used[joint] = true;
    joints[count] = joint;
    targets[count] = angle;
    count++;
  }

  if (count == 0) {
    error = "bad_joint_command";
    return false;
  }
  return true;
}

bool runJointCommand(String payload, int &count, String &error) {
  int joints[JOINT_COUNT];
  int targets[JOINT_COUNT];
  if (!parseJointCommand(payload, joints, targets, count, error)) {
    return false;
  }

  runningRoutine = true;
  moveGroup(joints, targets, count, JOINT_MOVE_STEPS, JOINT_MOVE_DELAY_MS);
  runningRoutine = false;
  return true;
}

int resolveFingerJoint(String hand, String finger) {
  if (hand == "left") {
    if (finger == "thumb") return PULGAR_IZQ;
    if (finger == "index") return INDICE_IZQ;
    if (finger == "middle") return MEDIO_IZQ;
    if (finger == "ring") return ANULAR_IZQ;
    if (finger == "pinky") return MENI_IZQ;
  }
  if (hand == "right") {
    if (finger == "thumb") return PULGAR_DER;
    if (finger == "index") return INDICE_DER;
    if (finger == "middle") return MEDIO_DER;
    if (finger == "ring") return ANULAR_DER;
    if (finger == "pinky") return MENI_DER;
  }
  return -1;
}

int resolveFingerTarget(int joint, String position) {
  if (position == "open") {
    return HOME_ANGLE[joint];
  }
  if (position == "closed") {
    return 0;
  }
  return -1;
}

bool runFingerCommand(String hand, String finger, String position) {
  int joint = resolveFingerJoint(hand, finger);
  if (joint < 0) {
    return false;
  }
  int target = resolveFingerTarget(joint, position);
  if (target < 0) {
    return false;
  }
  runningRoutine = true;
  moveSingle(joint, target, 45, 25);
  runningRoutine = false;
  return true;
}

bool parseFingerCommand(String payload, String &hand, String &finger, String &position) {
  payload.trim();
  int firstSpace = payload.indexOf(' ');
  if (firstSpace < 0) {
    return false;
  }
  int secondSpace = payload.indexOf(' ', firstSpace + 1);
  if (secondSpace < 0) {
    return false;
  }
  hand = payload.substring(0, firstSpace);
  finger = payload.substring(firstSpace + 1, secondSpace);
  position = payload.substring(secondSpace + 1);
  hand.trim();
  finger.trim();
  position.trim();
  return hand.length() > 0 && finger.length() > 0 && position.length() > 0;
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char ch = static_cast<char>(Serial.read());
    if (ch == '\r') {
      continue;
    }
    if (ch == '\n') {
      processCommand(inputLine);
      inputLine = "";
      continue;
    }
    if (inputLine.length() < MAX_COMMAND_LENGTH - 1) {
      inputLine += ch;
    } else {
      inputLine = "";
      Serial.println("ERR line_too_long");
    }
  }
}

void processCommand(String line) {
  line.trim();
  line.toLowerCase();
  if (line == "robot status") {
    Serial.println(runningRoutine ? "OK STATUS running" : "OK STATUS idle");
    return;
  }
  if (line == "robot stop") {
    runningRoutine = false;
    Serial.println("OK STOP");
    return;
  }
  if (line.startsWith("robot joints ")) {
    int count = 0;
    String error;
    if (runJointCommand(line.substring(13), count, error)) {
      Serial.print("OK JOINTS ");
      Serial.println(count);
    } else {
      Serial.print("ERR ");
      Serial.println(error);
    }
    return;
  }
  if (line.startsWith("robot finger ")) {
    String hand;
    String finger;
    String position;
    if (!parseFingerCommand(line.substring(13), hand, finger, position)) {
      Serial.println("ERR bad_finger_command");
      return;
    }
    if (runFingerCommand(hand, finger, position)) {
      Serial.print("OK FINGER ");
      Serial.print(hand);
      Serial.print(" ");
      Serial.print(finger);
      Serial.print(" ");
      Serial.println(position);
    } else {
      Serial.println("ERR unknown_finger");
    }
    return;
  }
  if (!line.startsWith("robot routine ")) {
    Serial.println("ERR unknown_command");
    return;
  }

  String routine = line.substring(14);
  routine.trim();
  if (runRoutine(routine)) {
    Serial.print("OK ROUTINE ");
    Serial.println(routine);
  } else {
    Serial.println("ERR unknown_routine");
  }
}

bool runRoutine(String routine) {
  runningRoutine = true;
  bool ok = true;

  if (routine == "rest") {
    routineRest();
  } else if (routine == "open_left_hand") {
    routineOpenLeftHand();
  } else if (routine == "close_left_hand") {
    routineCloseLeftHand();
  } else if (routine == "open_right_hand") {
    routineOpenRightHand();
  } else if (routine == "close_right_hand") {
    routineCloseRightHand();
  } else if (routine == "open_hands") {
    routineOpenHands();
  } else if (routine == "close_hands") {
    routineCloseHands();
  } else if (routine == "head_center") {
    routineHeadCenter();
  } else if (routine == "head_left") {
    routineHeadLeft();
  } else if (routine == "head_right") {
    routineHeadRight();
  } else if (routine == "head_nod") {
    routineHeadNod();
  } else if (routine == "arms_open") {
    routineArmsOpen();
  } else if (routine == "arms_rest") {
    routineArmsRest();
  } else if (routine == "demo") {
    routineDemo();
  } else {
    ok = false;
  }

  runningRoutine = false;
  return ok;
}

void routineRest() {
  const int joints[] = {
    LAT_IZQ, LAT_DER, ROTOR_IZQ, ROTOR_DER, BICEP_IZQ, BICEP_DER,
    CABEZA, MANDIBULA, CUELLO, CUELLO_IZQ, CUELLO_DER,
    PULGAR_IZQ, INDICE_IZQ, MEDIO_IZQ, ANULAR_IZQ, MENI_IZQ,
    PULGAR_DER, INDICE_DER, MEDIO_DER, ANULAR_DER, MENI_DER
  };
  const int targets[] = {
    135, 123, 80, 90, 90, 90, 90, 10, 60, 110, 90,
    140, 140, 160, 130, 130, 120, 120, 130, 170, 120
  };
  moveGroup(joints, targets, 21, 80, 35);
}

void routineOpenLeftHand() {
  const int joints[] = { PULGAR_IZQ, INDICE_IZQ, MEDIO_IZQ, ANULAR_IZQ, MENI_IZQ };
  const int targets[] = { 140, 140, 160, 130, 130 };
  moveGroup(joints, targets, 5, 50, 25);
}

void routineCloseLeftHand() {
  const int joints[] = { PULGAR_IZQ, INDICE_IZQ, MEDIO_IZQ, ANULAR_IZQ, MENI_IZQ };
  const int targets[] = { 0, 0, 0, 0, 0 };
  moveGroup(joints, targets, 5, 50, 25);
}

void routineOpenRightHand() {
  const int joints[] = { PULGAR_DER, INDICE_DER, MEDIO_DER, ANULAR_DER, MENI_DER };
  const int targets[] = { 120, 120, 130, 170, 120 };
  moveGroup(joints, targets, 5, 50, 25);
}

void routineCloseRightHand() {
  const int joints[] = { PULGAR_DER, INDICE_DER, MEDIO_DER, ANULAR_DER, MENI_DER };
  const int targets[] = { 0, 0, 0, 0, 0 };
  moveGroup(joints, targets, 5, 50, 25);
}

void routineOpenHands() {
  const int joints[] = {
    PULGAR_IZQ, INDICE_IZQ, MEDIO_IZQ, ANULAR_IZQ, MENI_IZQ,
    PULGAR_DER, INDICE_DER, MEDIO_DER, ANULAR_DER, MENI_DER
  };
  const int targets[] = { 140, 140, 160, 130, 130, 120, 120, 130, 170, 120 };
  moveGroup(joints, targets, 10, 60, 25);
}

void routineCloseHands() {
  const int joints[] = {
    PULGAR_IZQ, INDICE_IZQ, MEDIO_IZQ, ANULAR_IZQ, MENI_IZQ,
    PULGAR_DER, INDICE_DER, MEDIO_DER, ANULAR_DER, MENI_DER
  };
  const int targets[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
  moveGroup(joints, targets, 10, 60, 25);
}

void routineHeadCenter() {
  const int joints[] = { CABEZA, MANDIBULA, CUELLO, CUELLO_IZQ, CUELLO_DER };
  const int targets[] = { 90, 10, 60, 110, 90 };
  moveGroup(joints, targets, 5, 45, 30);
}

void routineHeadLeft() {
  moveSingle(CABEZA, 10, 45, 30);
}

void routineHeadRight() {
  moveSingle(CABEZA, 170, 45, 30);
}

void routineHeadNod() {
  const int jointsA[] = { CUELLO, CUELLO_IZQ, CUELLO_DER };
  const int targetsA[] = { 50, 95, 105 };
  moveGroup(jointsA, targetsA, 3, 25, 35);
  delay(200);
  const int targetsB[] = { 180, 125, 75 };
  moveGroup(jointsA, targetsB, 3, 35, 35);
  delay(200);
  const int targetsC[] = { 60, 110, 90 };
  moveGroup(jointsA, targetsC, 3, 35, 35);
}

void routineArmsOpen() {
  const int joints[] = { LAT_IZQ, LAT_DER, ROTOR_IZQ, ROTOR_DER, BICEP_IZQ, BICEP_DER };
  const int targets[] = { 80, 70, 10, 10, 140, 140 };
  moveGroup(joints, targets, 6, 90, 35);
}

void routineArmsRest() {
  const int joints[] = { LAT_IZQ, LAT_DER, ROTOR_IZQ, ROTOR_DER, BICEP_IZQ, BICEP_DER };
  const int targets[] = { 135, 123, 80, 90, 90, 90 };
  moveGroup(joints, targets, 6, 90, 35);
}

void jawPulse(int count) {
  for (int i = 0; i < count; i++) {
    moveSingle(MANDIBULA, 70, 12, 30);
    moveSingle(MANDIBULA, 10, 12, 30);
  }
}

void routineDemo() {
  routineArmsOpen();
  routineCloseHands();
  routineHeadLeft();
  jawPulse(1);
  routineHeadRight();
  jawPulse(2);
  routineHeadCenter();
  jawPulse(1);
  routineHeadNod();
  routineArmsRest();
  routineOpenHands();
}

// SMBusPeek: D1 mini als I2C-Master zum Fey-Pack PA-LNB117.R002.
//
// Ausgabe ueber USB-Serial: eine JSON-Zeile pro Messung, dazu ein paar
// Kommandos. Bewusst ASCII in allen Serial-Strings, damit jedes Terminal
// mitspielt; Umlaute nur in Kommentaren und Doku.

#include <Arduino.h>
#include <Wire.h>

#include "sbs.h"

namespace {

constexpr uint32_t kBaud = 115200;
constexpr uint32_t kDefaultIntervalMs = 1000;
constexpr uint32_t kMinIntervalMs = 100;
constexpr uint32_t kMaxIntervalMs = 60000;
constexpr size_t kLineMax = 64;

bool gStreaming = false;
uint32_t gIntervalMs = kDefaultIntervalMs;
uint32_t gNextSampleMs = 0;
char gLine[kLineMax];
size_t gLineLen = 0;

struct Sample {
  uint16_t voltageMv;
  int16_t currentMa;
  uint16_t tempDk;
  uint16_t soc;
  uint16_t remaining;
  uint16_t full;
  uint16_t cycles;
  bool capacityIn10mWh;
};

void ledPulse() {
#if defined(LED_BUILTIN)
  digitalWrite(LED_BUILTIN, LOW);  // D1 mini: LED ist low-aktiv
  delay(2);
  digitalWrite(LED_BUILTIN, HIGH);
#endif
}

void printError(const char *message) {
  Serial.printf("{\"ms\":%lu,\"ok\":0,\"err\":\"%s\"}\n",
                static_cast<unsigned long>(millis()), message);
}

// Ein kompletter Messsatz. Bricht beim ersten Fehler ab, damit keine halben
// Werte als gueltig durchgehen.
bool readSample(Sample &s) {
  uint16_t mode = 0;
  if (!sbs::readWord(sbs::kBatteryMode, mode)) {
    return false;
  }
  s.capacityIn10mWh = (mode & sbs::kCapacityModeBit) != 0;

  if (!sbs::readWord(sbs::kVoltage, s.voltageMv)) return false;
  if (!sbs::readWordSigned(sbs::kCurrent, s.currentMa)) return false;
  if (!sbs::readWord(sbs::kTemperature, s.tempDk)) return false;
  if (!sbs::readWord(sbs::kRelativeStateOfCharge, s.soc)) return false;
  if (!sbs::readWord(sbs::kRemainingCapacity, s.remaining)) return false;
  if (!sbs::readWord(sbs::kFullChargeCapacity, s.full)) return false;
  if (!sbs::readWord(sbs::kCycleCount, s.cycles)) return false;
  return true;
}

void printSampleJson(const Sample &s) {
  // 0,1 K -> 0,1 Â°C ohne Float-Formatierung (printf mit %f ist je nach
  // Core-Build nicht verfuegbar); auf 0,1 Â°C runden.
  int32_t t10 = static_cast<int32_t>(s.tempDk) * 10 - 27315;
  t10 = (t10 >= 0) ? (t10 + 5) / 10 : (t10 - 5) / 10;
  // Vorzeichen getrennt halten: -1/10 waere 0 und wuerde "+0,1" ergeben.
  const char *sign = (t10 < 0) ? "-" : "";
  const int32_t magnitude = (t10 < 0) ? -t10 : t10;

  Serial.printf(
      "{\"ms\":%lu,\"ok\":1,\"v_mv\":%u,\"i_ma\":%d,\"t_c\":%s%d.%d,\"soc\":%u,"
      "\"rc\":%u,\"fcc\":%u,\"cycles\":%u,\"cap_unit\":\"%s\"}\n",
      static_cast<unsigned long>(millis()), static_cast<unsigned>(s.voltageMv),
      static_cast<int>(s.currentMa), sign,
      static_cast<int>(magnitude / 10), static_cast<int>(magnitude % 10),
      static_cast<unsigned>(s.soc), static_cast<unsigned>(s.remaining),
      static_cast<unsigned>(s.full), static_cast<unsigned>(s.cycles),
      s.capacityIn10mWh ? "10mWh" : "mAh");
}

void measureOnce() {
  Sample s = {};
  if (readSample(s)) {
    printSampleJson(s);
    ledPulse();
  } else {
    printError("Lesefehler 0x0B (kein ACK oder Timeout)");
  }
}

void printHelp() {
  Serial.println(F("# Kommandos:"));
  Serial.println(F("#   read            einmal messen, eine JSON-Zeile"));
  Serial.println(F("#   start [ms]      dauerhaft senden (Standard 1000 ms, min 100)"));
  Serial.println(F("#   stop            dauerhaftes Senden beenden"));
  Serial.println(F("#   id              Hersteller, Name, Chemie, Seriennummer, Baudatum"));
  Serial.println(F("#   scan            I2C-Adressen 0x08..0x77 suchen"));
  Serial.println(F("#   raw <reg>       Register als Rohwert lesen, z. B. raw 0x0d"));
  Serial.println(F("#   block <reg>     Block lesen (Text oder Hex), z. B. block 0x21"));
  Serial.println(F("#   write <reg> <wert>  Wort schreiben (SMBus Write Word), z. B. write 0x03 0x0001"));
  Serial.println(F("#   status          BatteryStatus, BatteryMode, MaxError, AbsoluteSoC (JSON)"));
  Serial.println(F("#   dump            alle Register aus SBS 1.1 5.1 als eine JSON-Zeile"));
  Serial.println(F("#   reset           Pack in den Off State zwingen und neu adressieren"));
  Serial.println(F("#   help            diese Liste"));
}

void printId() {
  if (!sbs::probe()) {
    printError("kein ACK von 0x0B");
    return;
  }

  char text[33];

  if (sbs::readBlock(sbs::kManufacturerName, text, sizeof(text))) {
    Serial.printf("# %-18s: %s\n", "Hersteller", text);
  }
  if (sbs::readBlock(sbs::kDeviceName, text, sizeof(text))) {
    Serial.printf("# %-18s: %s\n", "Name", text);
  }
  if (sbs::readBlock(sbs::kDeviceChemistry, text, sizeof(text))) {
    Serial.printf("# %-18s: %s\n", "Chemie", text);
  }

  uint16_t value = 0;
  if (sbs::readWord(sbs::kSerialNumber, value)) {
    Serial.printf("# %-18s: %u\n", "Serien-Nr", static_cast<unsigned>(value));
  }
  if (sbs::readWord(sbs::kManufactureDate, value)) {
    // SBS 1.1 Â§5.1.26: (Jahr - 1980) * 512 + Monat * 32 + Tag
    const unsigned year = 1980 + ((value >> 9) & 0x7F);
    const unsigned month = (value >> 5) & 0x0F;
    const unsigned day = value & 0x1F;
    Serial.printf("# %-18s: %04u-%02u-%02u\n", "Baudatum", year, month, day);
  }

  // Einheit der Kapazitaet haengt am CAPACITY_MODE-Bit (BatteryMode, Bit 15).
  uint16_t mode = 0;
  const char *capacityUnit = "mAh";
  if (sbs::readWord(sbs::kBatteryMode, mode) && (mode & sbs::kCapacityModeBit)) {
    capacityUnit = "10mWh";
  }
  if (sbs::readWord(sbs::kDesignCapacity, value)) {
    Serial.printf("# %-18s: %u %s\n", "Design-Kapazitaet",
                  static_cast<unsigned>(value), capacityUnit);
  }
  if (sbs::readWord(sbs::kDesignVoltage, value)) {
    Serial.printf("# %-18s: %u mV\n", "Design-Spannung", static_cast<unsigned>(value));
  }
}

void scanBus() {
  Serial.println(F("# I2C-Scan 0x08..0x77"));
  uint8_t found = 0;
  for (uint8_t address = 0x08; address <= 0x77; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("#   0x%02X%s\n", address,
                    address == sbs::kAddress ? "  <- SBS-Pack" : "");
      found++;
    }
  }
  if (found == 0) {
    Serial.println(F("#   nichts gefunden (Pull-ups? GND? Pack wach?)"));
  }
}

void printRaw(const char *argument) {
  if (argument == nullptr) {
    Serial.println(F("# Aufruf: raw <reg>, z. B. raw 0x0d"));
    return;
  }
  char *end = nullptr;
  const unsigned long reg = strtoul(argument, &end, 0);
  if (end == argument || reg > 0xFF) {
    Serial.println(F("# Register unlesbar (hex 0x.. oder dezimal)"));
    return;
  }

  uint16_t value = 0;
  if (!sbs::readWord(static_cast<uint8_t>(reg), value)) {
    printError("Register nicht lesbar (kein ACK oder Timeout)");
    return;
  }
  Serial.printf("# 0x%02lX = 0x%04X (%u)\n", reg, value, static_cast<unsigned>(value));
}

// Blockread als Text; ist der Block binaer, wird er als Hex-Folge ausgegeben.
// Achtung: das Pack setzt nach einem Blockread ERROR_CODE 7, bis wieder ein
// Wort gelesen wird (siehe printDump).
void printBlock(const char *argument) {
  if (argument == nullptr) {
    Serial.println(F("# Aufruf: block <reg>, z. B. block 0x21"));
    return;
  }
  char *end = nullptr;
  const unsigned long reg = strtoul(argument, &end, 0);
  if (end == argument || reg > 0xFF) {
    Serial.println(F("# Register unlesbar (hex 0x.. oder dezimal)"));
    return;
  }

  char text[33];
  if (sbs::readBlock(static_cast<uint8_t>(reg), text, sizeof(text))) {
    Serial.printf("# 0x%02lX = \"%s\"\n", reg, text);
    return;
  }

  uint8_t bytes[33];
  const uint8_t count = sbs::readBlockBytes(static_cast<uint8_t>(reg), bytes,
                                            sizeof(bytes));
  if (count == 0) {
    printError("Block nicht lesbar (kein ACK oder Timeout)");
    return;
  }
  Serial.printf("# 0x%02lX =", reg);
  for (uint8_t i = 0; i < count; i++) {
    Serial.printf(" %02X", static_cast<unsigned>(bytes[i]));
  }
  Serial.println();
}

// BatteryStatus (0x16) plus die Register, die bei einer Schutzabschaltung
// helfen. Kurze JSON-Zeile, damit sie auch im Live-Betrieb nicht stoert.
// Bitbelegung aus SBS 1.1 §5.1.21 (BatteryStatus) und §5.1.4 (BatteryMode).
void printStatus() {
  uint16_t status = 0;
  uint16_t mode = 0;
  uint16_t maxError = 0;
  uint16_t absSoc = 0;
  if (!sbs::readWord(sbs::kBatteryStatus, status) ||
      !sbs::readWord(sbs::kBatteryMode, mode) ||
      !sbs::readWord(sbs::kMaxError, maxError) ||
      !sbs::readWord(sbs::kAbsoluteStateOfCharge, absSoc)) {
    printError("Status nicht lesbar (kein ACK oder Timeout)");
    return;
  }

  // Arduino.h kennt ein Makro "bit", deshalb heisst der Helfer "flag".
  const auto flag = [](uint16_t value, uint8_t pos) {
    return static_cast<unsigned>((value >> pos) & 1u);
  };

  // Alarme 15..8, Statusbits 7..4, danach Error-Code (Bits 3..0).
  // BatteryMode: 15 CAPACITY_MODE, 14 CHARGER_MODE, 13 ALARM_MODE,
  // 9 PRIMARY_BATTERY, 8 CHARGE_CONTROLLER_ENABLED, 7 CONDITION_FLAG,
  // 1 PRIMARY_BATTERY_SUPPORT, 0 INTERNAL_CHARGE_CONTROLLER.
  Serial.printf(
      "{\"ms\":%lu,\"ok\":1,\"st\":%u,\"err\":%u,\"ovc\":%u,\"tc\":%u,\"ot\":%u,"
      "\"td\":%u,\"rca\":%u,\"rta\":%u,\"init\":%u,\"dis\":%u,\"full\":%u,"
      "\"empty\":%u,\"maxerr\":%u,\"asoc\":%u,\"mode\":%u,\"cap10mwh\":%u,"
      "\"chgm\":%u,\"alarm\":%u,\"prim\":%u,\"chgc\":%u,\"cond\":%u,\"pbsup\":%u,"
      "\"icc\":%u}\n",
      static_cast<unsigned long>(millis()), static_cast<unsigned>(status),
      static_cast<unsigned>(status & 0x0F),
      flag(status, 15), flag(status, 14), flag(status, 12), flag(status, 11),
      flag(status, 9), flag(status, 8),
      flag(status, 7), flag(status, 6), flag(status, 5), flag(status, 4),
      static_cast<unsigned>(maxError), static_cast<unsigned>(absSoc),
      static_cast<unsigned>(mode),
      flag(mode, 15), flag(mode, 14), flag(mode, 13), flag(mode, 9),
      flag(mode, 8), flag(mode, 7), flag(mode, 1), flag(mode, 0));
}

// JSON-String ausgeben. Escaped werden nur die beiden Zeichen, die JSON nicht
// ungeschuetzt erlaubt; die SBS-Bloecke sind reines ASCII ohne Steuerzeichen.
void writeJsonString(const char *text) {
  Serial.print('"');
  for (const char *p = text; *p != '\0'; p++) {
    if (*p == '"' || *p == '\\') {
      Serial.print('\\');
    }
    Serial.print(*p);
  }
  Serial.print('"');
}

// Alle Register aus SBS 1.1 §5.1 in einer Zeile: Wortregister 0x00..0x1C,
// danach die vier Blockreads 0x20..0x23. Nicht lesbare Woerter stehen als -1,
// nicht lesbare Bloecke als leerer String, damit die Zeile auswertbar bleibt.
// Die Bedeutung der Felder kennt die GUI.
void printDump() {
  if (!sbs::probe()) {
    printError("kein ACK von 0x0B");
    return;
  }

  Serial.printf("{\"ms\":%lu,\"ok\":1,\"dump\":1",
                static_cast<unsigned long>(millis()));
  for (unsigned reg = 0x00; reg <= 0x1C; reg++) {
    uint16_t value = 0;
    if (sbs::readWord(static_cast<uint8_t>(reg), value)) {
      Serial.printf(",\"r%02X\":%u", reg, static_cast<unsigned>(value));
    } else {
      Serial.printf(",\"r%02X\":-1", reg);
    }
  }

  char text[33];
  const uint8_t blocks[] = {sbs::kManufacturerName, sbs::kDeviceName,
                            sbs::kDeviceChemistry};
  for (const uint8_t reg : blocks) {
    Serial.printf(",\"b%02X\":", static_cast<unsigned>(reg));
    if (sbs::readBlock(reg, text, sizeof(text))) {
      writeJsonString(text);
    } else {
      Serial.print(F("\"\""));
    }
  }

  // ManufacturerData ist herstellerspezifisch und meist binaer, deshalb als
  // Hex-Folge statt als Text.
  uint8_t bytes[33];
  const uint8_t count = sbs::readBlockBytes(sbs::kManufacturerData, bytes,
                                            sizeof(bytes));
  Serial.print(F(",\"b23\":\""));
  for (uint8_t i = 0; i < count; i++) {
    Serial.printf("%s%02X", i > 0 ? " " : "", static_cast<unsigned>(bytes[i]));
  }
  Serial.print('"');

  // Das Pack quittiert Blockreads mit ERROR_CODE 7 ("unbekannter Fehler"), obwohl
  // die Daten sauber ankommen. Ein erfolgreicher Wortzugriff setzt den Code
  // zurueck – ohne ihn zeigte der naechste status einen Phantomfehler.
  uint16_t discarded = 0;
  sbs::readWord(sbs::kVoltage, discarded);

  Serial.println("}");
}

void printWrite(const char *regArg, const char *valueArg) {
  if (regArg == nullptr || valueArg == nullptr) {
    Serial.println(F("# Aufruf: write <reg> <wert>, z. B. write 0x03 0x0001"));
    return;
  }
  char *endReg = nullptr;
  char *endValue = nullptr;
  const unsigned long reg = strtoul(regArg, &endReg, 0);
  const unsigned long value = strtoul(valueArg, &endValue, 0);
  if (endReg == regArg || reg > 0xFF) {
    Serial.println(F("# Register unlesbar (hex 0x.. oder dezimal)"));
    return;
  }
  if (endValue == valueArg || value > 0xFFFF) {
    Serial.println(F("# Wert unlesbar (hex 0x.. oder dezimal, max. 0xFFFF)"));
    return;
  }

  Serial.printf("# schreibe 0x%02lX <- 0x%04lX\n", reg, value);
  if (sbs::writeWord(static_cast<uint8_t>(reg), static_cast<uint16_t>(value))) {
    Serial.println(F("# ACK"));
  } else {
    // Sealed-Pack oder Nur-Lese-Register: kein ACK ist die normale Antwort.
    Serial.println(F("# kein ACK (Pack gesperrt oder Register nur lesbar)"));
  }
}

void handleCommand(char *line) {
  char *save = nullptr;
  const char *command = strtok_r(line, " \t", &save);
  if (command == nullptr) {
    return;
  }
  const char *argument = strtok_r(nullptr, " \t", &save);

  if (strcmp(command, "read") == 0) {
    measureOnce();
  } else if (strcmp(command, "start") == 0) {
    uint32_t interval = kDefaultIntervalMs;
    if (argument != nullptr) {
      const unsigned long parsed = strtoul(argument, nullptr, 10);
      if (parsed >= kMinIntervalMs && parsed <= kMaxIntervalMs) {
        interval = parsed;
      } else {
        Serial.printf("# Intervall ausserhalb %lu..%lu ms, nehme %lu\n",
                      static_cast<unsigned long>(kMinIntervalMs),
                      static_cast<unsigned long>(kMaxIntervalMs),
                      static_cast<unsigned long>(kDefaultIntervalMs));
      }
    }
    gIntervalMs = interval;
    gStreaming = true;
    gNextSampleMs = millis();
    Serial.printf("# sende alle %lu ms\n", static_cast<unsigned long>(gIntervalMs));
  } else if (strcmp(command, "stop") == 0) {
    gStreaming = false;
    Serial.println(F("# gestoppt"));
  } else if (strcmp(command, "id") == 0) {
    printId();
  } else if (strcmp(command, "scan") == 0) {
    scanBus();
  } else if (strcmp(command, "raw") == 0) {
    printRaw(argument);
  } else if (strcmp(command, "block") == 0) {
    printBlock(argument);
  } else if (strcmp(command, "write") == 0) {
    const char *valueArg = strtok_r(nullptr, " \t", &save);
    printWrite(argument, valueArg);
  } else if (strcmp(command, "status") == 0) {
    printStatus();
  } else if (strcmp(command, "dump") == 0) {
    printDump();
  } else if (strcmp(command, "reset") == 0) {
    Serial.println(F("# beide Leitungen 2,6 s low -> Pack in Off State"));
    if (sbs::resetPack()) {
      Serial.println(F("# Pack antwortet wieder"));
    } else {
      Serial.println(F("# kein ACK nach dem Reset"));
    }
  } else if (strcmp(command, "help") == 0) {
    printHelp();
  } else {
    Serial.printf("# unbekannt: %s (help)\n", command);
  }
}

void pollSerial() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      gLine[gLineLen] = '\0';
      if (gLineLen > 0) {
        handleCommand(gLine);
      }
      gLineLen = 0;
      continue;
    }
    if (gLineLen + 1 < kLineMax) {
      gLine[gLineLen++] = c;
    } else {
      // Zeile zu lang: verwerfen, sonst laeuft der Puffer ueber.
      gLineLen = 0;
      Serial.println(F("# Zeile zu lang, verworfen"));
    }
  }
}

}  // namespace

void setup() {
#if defined(LED_BUILTIN)
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
#endif

  Serial.begin(kBaud);
  delay(50);
  Serial.println();
  Serial.println(F("# SMBusPeek - D1 mini als SBS-Master"));
  Serial.println(F("# SDA = GPIO4 (D2), SCL = GPIO5 (D1), 100 kHz"));

  sbs::begin();
  if (sbs::probe()) {
    Serial.printf("# Pack 0x%02X antwortet\n", sbs::kAddress);
  } else {
    Serial.println(F("# kein ACK von 0x0B: GND verbunden? Pull-ups? 'scan' oder 'reset'."));
  }
  Serial.println(F("# 'help' fuer Kommandos"));
}

void loop() {
  pollSerial();

  if (gStreaming) {
    const uint32_t now = millis();
    if (static_cast<int32_t>(now - gNextSampleMs) >= 0) {
      gNextSampleMs = now + gIntervalMs;
      measureOnce();
    }
  }
}

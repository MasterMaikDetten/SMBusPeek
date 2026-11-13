#include "sbs.h"

#include <Wire.h>

namespace sbs {
namespace {

constexpr uint32_t kI2cHz = 100000;
// SMBus 2.0: tTIMEOUT betraegt 25-35 ms. Laenger warten hat keinen Zweck,
// danach ist der Bus ohnehin zu resetten.
constexpr uint32_t kStretchLimitUs = 30000;

constexpr uint8_t kMaxBlock = 32;
constexpr uint8_t kProbeAttempts = 3;

void startWire() {
  Wire.begin(SBS_SDA_PIN, SBS_SCL_PIN);
  Wire.setClock(kI2cHz);
  Wire.setClockStretchLimit(kStretchLimitUs);
}

void drainRx() {
  while (Wire.available()) {
    Wire.read();
  }
}

// Text aus einem Blockread aufraeumen: Steuerzeichen raus, rechts trimmen.
void sanitize(char *text) {
  size_t len = strlen(text);
  size_t end = 0;
  for (size_t i = 0; i < len; i++) {
    const uint8_t c = static_cast<uint8_t>(text[i]);
    if (c >= 0x20 && c <= 0x7E) {
      text[end++] = static_cast<char>(c);
    }
  }
  while (end > 0 && text[end - 1] == ' ') {
    end--;
  }
  text[end] = '\0';
}

}  // namespace

void begin() {
  startWire();
}

bool probe() {
  for (uint8_t attempt = 1; attempt <= kProbeAttempts; attempt++) {
    Wire.beginTransmission(kAddress);
    if (Wire.endTransmission() == 0) {
      return true;
    }
    // Kein ACK ist laut SBS 1.1 §4.4.2 normal: das Pack kommt erst mit
    // steigenden Leitungen in den On State. Beim zweiten Versuch zusaetzlich
    // den Bus freischaukeln, falls eine Leitung low haengt.
    if (attempt == 2) {
      recoverBus();
    }
    delay(10);
  }
  return false;
}

bool readWord(uint8_t reg, uint16_t &out) {
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(kAddress, static_cast<uint8_t>(2)) != 2) {
    drainRx();
    return false;
  }
  const uint8_t lo = Wire.read();
  const uint8_t hi = Wire.read();
  out = static_cast<uint16_t>(lo | (static_cast<uint16_t>(hi) << 8));
  return true;
}

bool readWordSigned(uint8_t reg, int16_t &out) {
  uint16_t raw = 0;
  if (!readWord(reg, raw)) {
    return false;
  }
  out = static_cast<int16_t>(raw);
  return true;
}

bool writeWord(uint8_t reg, uint16_t value) {
  // SMBus Write Word: Register, dann Little-Endian niederwertiges Byte zuerst.
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  Wire.write(static_cast<uint8_t>(value & 0xFF));
  Wire.write(static_cast<uint8_t>(value >> 8));
  return Wire.endTransmission() == 0;
}

bool readBlock(uint8_t reg, char *out, size_t outSize) {
  if (outSize < 2) {
    return false;
  }
  const uint8_t n = readBlockBytes(
      reg, reinterpret_cast<uint8_t *>(out), static_cast<uint8_t>(outSize - 1));
  out[n] = '\0';
  sanitize(out);
  return out[0] != '\0';
}

uint8_t readBlockBytes(uint8_t reg, uint8_t *out, uint8_t outSize) {
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return 0;
  }

  // SMBus-Block read: erst Laengenbyte, dann Daten. Wir fordern die maximale
  // Menge an und vertrauen nur den ersten len Bytes; was das Pack nicht liefert,
  // bleibt 0xFF.
  const uint8_t got = Wire.requestFrom(kAddress, static_cast<uint8_t>(kMaxBlock + 1));
  if (got < 2) {
    drainRx();
    return 0;
  }
  const uint8_t len = Wire.read();
  if (len == 0 || len > kMaxBlock) {
    drainRx();
    return 0;
  }

  uint8_t n = len;
  if (n > outSize) {
    n = outSize;
  }
  for (uint8_t i = 0; i < n; i++) {
    out[i] = static_cast<uint8_t>(Wire.read());
  }
  drainRx();
  return n;
}

void recoverBus() {
  // Der ESP8266-Wire-Treiber kennt kein end(). pinMode() haengt die Pins vom
  // I2C-Peripherieblock ab (GPIO-Funktion), danach haengt begin() sie wieder an.
  pinMode(SBS_SDA_PIN, INPUT_PULLUP);
  pinMode(SBS_SCL_PIN, INPUT_PULLUP);
  delayMicroseconds(10);

  // Haengt SDA low (Slave mitten im Byte abgebrochen), schiebt der Host bis zu
  // neun Takte nach, bis der Slave loslaesst.
  if (digitalRead(SBS_SDA_PIN) == LOW) {
    for (uint8_t i = 0; i < 9 && digitalRead(SBS_SDA_PIN) == LOW; i++) {
      pinMode(SBS_SCL_PIN, OUTPUT);
      digitalWrite(SBS_SCL_PIN, LOW);
      delayMicroseconds(5);
      pinMode(SBS_SCL_PIN, INPUT_PULLUP);
      delayMicroseconds(5);
    }
    // STOP erzeugen: SDA geht hoch, waehrend SCL hoch ist.
    pinMode(SBS_SDA_PIN, OUTPUT);
    digitalWrite(SBS_SDA_PIN, LOW);
    delayMicroseconds(5);
    pinMode(SBS_SCL_PIN, INPUT_PULLUP);
    delayMicroseconds(5);
    pinMode(SBS_SDA_PIN, INPUT_PULLUP);
    delayMicroseconds(5);
  }

  startWire();
}

bool resetPack(uint16_t holdMs) {
  // Leitungen als GPIO uebernehmen und beide auf low ziehen.
  pinMode(SBS_SDA_PIN, OUTPUT);
  pinMode(SBS_SCL_PIN, OUTPUT);
  digitalWrite(SBS_SDA_PIN, LOW);
  digitalWrite(SBS_SCL_PIN, LOW);
  delay(holdMs);

  // Leitungen freigeben: das ist laut §4.4.2 das Signal fuer den On State.
  pinMode(SBS_SDA_PIN, INPUT_PULLUP);
  pinMode(SBS_SCL_PIN, INPUT_PULLUP);
  delay(10);

  startWire();
  return probe();
}

}  // namespace sbs

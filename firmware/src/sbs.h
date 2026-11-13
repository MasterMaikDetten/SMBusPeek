// SBS-Zugriff auf das Fey-Pack PA-LNB117.R002 (Adresse 0x0B).
//
// Register und Einheiten aus SBS 1.1 §5.1 (datasheets/SBS_Smart-Battery-Data-Spec-1.1.pdf).
// Elektrik aus SMBus 2.0: 100 kHz, tTIMEOUT 25-35 ms, VIH >= 2,1 V.
#pragma once

#include <Arduino.h>

#ifndef SBS_SDA_PIN
#define SBS_SDA_PIN 4  // D2 = GPIO4
#endif
#ifndef SBS_SCL_PIN
#define SBS_SCL_PIN 5  // D1 = GPIO5
#endif

namespace sbs {

// SBS-Adresse des Packs (SBS 1.1 §5).
constexpr uint8_t kAddress = 0x0B;

// Register (SBS 1.1 §5.1). Nur was hier steht, ist gegen die Spec belegt.
enum Reg : uint8_t {
  kManufacturerAccess = 0x00,
  kRemainingCapacityAlarm = 0x01,
  kRemainingTimeAlarm = 0x02,
  kBatteryMode = 0x03,
  kAtRate = 0x04,                // mA oder 10 mW (CAPACITY_MODE), signed
  kAtRateTimeToFull = 0x05,      // min, 65535 = nicht verfuegbar
  kAtRateTimeToEmpty = 0x06,     // min, 65535 = nicht verfuegbar
  kAtRateOK = 0x07,              // Boolean
  kTemperature = 0x08,           // 0,1 K
  kVoltage = 0x09,               // mV
  kCurrent = 0x0A,               // mA, signed: + = Laden, - = Entladen
  kAverageCurrent = 0x0B,        // mA, signed
  kMaxError = 0x0C,              // %
  kRelativeStateOfCharge = 0x0D, // %
  kAbsoluteStateOfCharge = 0x0E, // %
  kRemainingCapacity = 0x0F,     // mAh oder 10 mWh (CAPACITY_MODE)
  kFullChargeCapacity = 0x10,    // mAh oder 10 mWh (CAPACITY_MODE)
  kRunTimeToEmpty = 0x11,        // min, 65535 = nicht verfuegbar
  kAverageTimeToEmpty = 0x12,    // min, 65535 = nicht verfuegbar
  kAverageTimeToFull = 0x13,     // min, 65535 = nicht verfuegbar
  kChargingCurrent = 0x14,       // mA, SBS 1.1 §5.2
  kChargingVoltage = 0x15,       // mV, SBS 1.1 §5.3
  kBatteryStatus = 0x16,
  kCycleCount = 0x17,
  kDesignCapacity = 0x18,
  kDesignVoltage = 0x19,         // mV
  kSpecificationInfo = 0x1A,
  kManufactureDate = 0x1B,
  kSerialNumber = 0x1C,
  kManufacturerName = 0x20,      // Block
  kDeviceName = 0x21,            // Block
  kDeviceChemistry = 0x22,       // Block
  kManufacturerData = 0x23,      // Block
};

// CAPACITY_MODE in BatteryMode(): 1 = Kapazitaeten in 10 mWh statt mAh.
constexpr uint16_t kCapacityModeBit = 0x8000;

// Bus auf 100 kHz initialisieren.
void begin();

// Adresse 0x0B ansprechen, mit einem Bus-Recovery dazwischen.
bool probe();

// Wort lesen (Little-Endian: niederwertiges Byte zuerst).
bool readWord(uint8_t reg, uint16_t &out);
bool readWordSigned(uint8_t reg, int16_t &out);

// Wort schreiben (SMBus Write Word). Veraendert das Pack – nur mit Bedacht.
bool writeWord(uint8_t reg, uint16_t value);

// SMBus-Block lesen (Laengenbyte + Text). PEC wird nicht benutzt.
bool readBlock(uint8_t reg, char *out, size_t outSize);

// Block roh lesen (ohne Text-Aufbereitung), fuer binaere Herstellerdaten wie
// ManufacturerData. Liefert die Anzahl Bytes, 0 bei Fehler.
uint8_t readBlockBytes(uint8_t reg, uint8_t *out, uint8_t outSize);

// Haengende Leitungen loesen: bis zu 9 Takte, dann STOP, dann Wire neu starten.
void recoverBus();

// Beide Leitungen holdMs low ziehen. Das ist laut SBS 1.1 §4.4.3 der Weg in den
// Off State (Pack schlaeft), keine "Aufweck"-Funktion.
bool resetPack(uint16_t holdMs = 2600);

}  // namespace sbs

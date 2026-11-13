# SMBusPeek – D1 mini als SMBus-Brücke für ein Smart Battery

Ein Wemos **D1 mini (ESP8266)** als USB↔I²C-Adapter zu einem **Smart Battery**
nach SBS 1.1, hier konkret zum Fey-Pack **PA-LNB117.R002** (`4INR19/66`, 4S1P
aus 4 × 18650). Der Pack liefert Spannung, Strom, Temperatur und Ladezustand
selbst über SDA/SCL – der D1 mini misst nichts, er fragt nur.

Dazu gibt es:

- **`firmware/`** – PlatformIO-Firmware mit einer kleinen Kommandoschnittstelle
  über USB-Serial (JSON-Zeilen).
- **`gui/`** – Tkinter-Oberfläche für Windows, die dieselben Kommandos
  schickt: Messwerte live, alle 33 SBS-Register als Tabelle, Statusdekodierung
  und – wo erlaubt – Register schreiben.
- **`hardware/`** – KiCad-10-Schaltplan (Direktverbindung, keine
  Pegelwandler), als PDF und SVG exportiert, mit ERC-Bericht.

## Status

Am echten Pack gelaufen (2026-11-13): Adresse 0x0B antwortet, Hersteller
`FEY`, DeviceName `HRDL-0007-XXXXXXXXXX`, 16,4 V, 21 °C, 2979 mAh, 19 Zyklen.
Alle Kommandos (`read`, `start`/`stop`, `id`, `scan`, `raw`, `block`, `write`,
`status`, `dump`, `reset`) sind am Pack getestet. Schreibzugriffe auf 0x01,
0x02, 0x03 und 0x04 werden mit ACK bestätigt; bei `AtRate` ist die Wirkung
nachweisbar (die Prognosen 0x05–0x07 ändern sich passend).

## Sicherheit zuerst

Der Pack hat **16,8 V** und rund 96 A Kurzschlussstrom. Deshalb:

- **Gemeinsame Masse** zwischen D1 mini und Pack (Pin 4) ist Pflicht.
- **Niemals** 16,8 V auf `5V`, `Vin` oder `3V3` des D1 mini – der AMS1117
  verheizt über 1 W. Der D1 mini wird über USB versorgt, Pin 1 (Bat+) bleibt
  offen.
- Reihenfolge: erst GND, dann SDA/SCL; SDA/SCL nie an einen unversorgten
  D1 mini stecken (sonst speist der Pack über die ESD-Dioden ein).
- Vor dem Anstecken die Ruhespannung von SDA/SCL gegen GND am Pack messen.
  Zieht der Pack nach 5 V, ist ein Pegelwandler nötig (ESP8266 max. 3,6 V).
- **Laden ist nicht Teil dieses Aufbaus.** Dafür braucht es ein CC/CV-Lader
  (4S, 16,8 V). Nicht gleichzeitig laden und USB anschließen, solange die
  Massepfade nicht geklärt sind.
- Die **Safety Unit im Pack nie überbrücken** – sie ist die einzige
  Schutzebene.

## Aufbau

```
Rechner ──USB── D1 mini ──I²C (3,3 V, 100 kHz)── Pack
                              SDA = GPIO4 (D2)
                              SCL = GPIO5 (D1)
                              GND = gemeinsame Masse
```

Stecker am Pack (Molex Microfit 43645-0400, 4-polig):

| Pin | Signal |
| --- | --- |
| 1 | Bat+ (bleibt hier offen) |
| 2 | SCL |
| 3 | SDA |
| 4 | GND |

Pull-ups R1/R2 gegen 3,3 V sind im Plan 4,7 kΩ, im Test 3 kΩ bestückt (über
Lötjumper JP1/JP2 abschaltbar). SBS-Adresse des Packs: **0x0B**.

## Firmware

PlatformIO, Umgebung `d1_mini`:

```
cd firmware
pio run                # bauen
pio run -t upload      # flashen (Port ggf. mit --upload-port COMx)
pio device monitor     # 115200 Baud
```

Kommandos (Auszug): `read`, `start [ms]`, `stop`, `id`, `scan`, `raw <reg>`,
`block <reg>`, `write <reg> <wert>`, `status`, `dump`, `reset`, `help`.

Eine Messung ist eine JSON-Zeile:

```json
{"ms":12345,"ok":1,"v_mv":15823,"i_ma":-120,"t_c":24.9,"soc":87,
 "rc":2910,"fcc":3350,"cycles":12,"cap_unit":"mAh"}
```

## GUI

```
gui\start.cmd          # legt beim ersten Mal das venv an und startet die GUI
```

Python 3 mit Tkinter, `pyserial` aus `gui/requirements.txt`. Port wählen,
verbinden, fertig. Das Öffnen des Ports setzt den D1 mini zurück.

Die Tabelle **Alle SBS-Werte …** zeigt alle Funktionen aus §5.1 mit Zugriff
(`R/W`/`R`), Rohwert und aufbereitetem Wert; schreibbar sind laut Spec nur
0x00–0x04, doppelklicken öffnet den Schreibdialog. Details in
[`gui/README.md`](gui/README.md).

## Dokumentation

[`AGENTS.md`](AGENTS.md) ist die ausführliche Referenz: Pinbelegung, elektrische
Grenzen, Pegel-Diskussion (SBS regelt nur Daten, SMBus die Elektrik), alle
Register mit Messwerten, Verhalten am Bus (Off State, Bus-Recovery, fehlender
ACK beim ersten Zugriff), Grenzen der Firmware und das Messprotokoll.

## Datenblätter und Normen

**Nicht im Repo** – die PDFs sind „all rights reserved“ und werden nicht
weitergegeben. Woher sie kommen und welche Werte daraus stammen, steht in
[`datasheets/README.md`](datasheets/README.md):

- Fey-Datenblatt: <https://www.feyelektronik.de/downloads/db-pa-lnb117.pdf>
- SBS 1.1: <http://sbs-forum.org/specs/sbdat110.pdf>
- SMBus 2.0 / 3.3: <https://smbus.org/specs/smbus20.pdf>,
  <https://smbus.org/specs/SMBus_3_3_20240512.pdf>

## Lizenz

[MIT](LICENSE). Die Norm- und Herstellerdokumente sind davon **nicht**
erfasst – sie liegen nicht bei und dürfen nicht weitergegeben werden.

## Haftung

Alles auf eigene Gefahr. Li-Ion-Packs mit 16,8 V können bei Kurzschluss,
Verpolung oder falscher Behandlung Feuer fangen. Nachbau nur mit
Strombegrenzung, Messgerät und Verstand – und ohne die Schutzebene des Packs
zu umgehen.

# SMBusPeek

Ziel des Repos: ein Wemos **D1 mini (ESP8266)** als I²C-Schnittstelle zum
Fey-Pack **PA-LNB117.R002** (`4INR19/66` = 4S1P aus 4 × INR19/66 / 18650).

Der Pack ist ein **Smart Battery (SBS)** und liefert Spannung, Strom,
Temperatur und Ladezustand selbst über SDA/SCL. Der D1 mini ist deshalb
I²C-**Master** und muss nichts selbst messen – kein Shunt, kein Spannungsteiler.

## Stand

- Dokumentation, **Schaltplan** (`hardware/`), **Firmware** (`firmware/`) und
  **GUI** (`gui/`, Tkinter + pyserial, mit Tabelle aller SBS-Register).
- Datenblatt: `datasheets/README.md` (Herkunft, Eigenheiten, Bezugsquellen –
  die PDFs selbst sind aus Urheberrechtsgründen nicht im Repo).
- Schaltplan: `hardware/SMBusPeek.kicad_sch` (KiCad 10),
  Ausgabe als `hardware/SMBusPeek.pdf` und `hardware/svg/`.
  ERC-Bericht: `hardware/erc.rpt` (Stand Rev A: 0 Verstöße).
- Firmware: PlatformIO, Umgebung `d1_mini`. Baut warnungsfrei mit
  `-Wall -Wextra` und ist **am 2026-11-13 am echten Pack gelaufen** –
  Messwerte im Abschnitt „Messprotokoll“.

## Aufbau (bestätigtes Konzept)

USB vom Rechner an den D1 mini, von dort per I²C an den Pack. Der D1 mini ist
USB↔SMBus-Brücke; er wird **aus USB** versorgt, nicht aus dem Pack.

- Pflicht: **gemeinsame Masse** (D1 mini GND ↔ Pin 4 des Packs). Ohne sie gibt
  es keine definierten Pegel.
- Kein Pegelwandler, solange der Pack SDA/SCL auf 3,3 V zieht. Offen und vor
  dem Anstecken zu messen: Ruhespannung von SDA und SCL gegen GND am Pack
  (ohne D1 mini). ~3,3 V → direkt verbinden. ~5 V → Pegelwandler (BSS138-Modul
  reicht bei 100 kHz) oder die Leitung nicht anschließen.
- Niemals 16,8 V auf `5V`/`Vin`/`3V3` des D1 mini: der AMS1117 verheizt
  (16,8 V → 3,3 V bei ~80 mA ≈ 1 W). Laden des Packs ist nicht Teil dieses
  Aufbaus, dafür braucht es ein CC/CV-Ladegerät mit 16,8 V.
- Reihenfolge: erst GND, dann SDA/SCL; SDA/SCL nie an einen unversorgten
  D1 mini stecken (der Pack speist sonst über die ESD-Dioden ein).
- Nicht gleichzeitig laden und USB anschließen, solange die Massepfade nicht
  geklärt sind (Masseschleife über Netzteil/Rechner).

## Stecker (Molex Microfit 43645-0400, 4-polig)

| Pin | Signal |
| --- | --- |
| 1 | Bat+ |
| 2 | SCL |
| 3 | SDA |
| 4 | GND |

Pinbelegung aus dem Datenblatt, nicht aus Forenposts. **Kein NTC am Stecker**
(Datenblatt: `NTC n/a`) – Temperatur ausschließlich über das SBS-Register 0x08.

## Pack-Daten (Datenblatt, Datenstand 09.11.2017)

- 14,4 V nominal, 3,35 Ah typ. (3,1 Ah min.), 48 Wh, 4 × Panasonic NCR-18650B.
- Betriebsspannung 12–16,8 V (medizinische Anwendung 12–16,4 V).
- Laden: max. 16,8 V, 1625 mA (10–45 °C), Standard 500 mA.
- Entladen: 4,875 A Dauer, 5 A Peak, ~96 A Kurzschluss.
- Schutz durch Safety Unit: 5 A/16 s, 14 A/31 ms, Kurzschluss ≥22,5 A;
  Zelle über 4,225 V / unter 3,0 V Abschaltung.
- Innenwiderstand 150 mΩ, 135 mm Kabel, ca. 220 g, ESD-Schutz vorhanden.
- Eigenverbrauch 350 µA aktiv, **<50 µA sleep** → der Pack schläft. Der Weg
  hinein und hinaus ist in der SBS-Spec definiert (siehe unten), nicht im
  Fey-Datenblatt.

## Pegel – was die Norm sagt (und was nicht)

Normen: SBS 1.1 (Daten), SMBus 2.0 (Elektrik, Fassung zur Bauzeit des Packs)
und SMBus 3.3 (aktuelle Fassung) – Quellen in `datasheets/README.md`, die PDFs
liegen nicht im Repo.

- Die **SBS-Spec regelt nur die Daten**, nicht die Elektrik (§1.1: "The
  electrical and mechanical specifications are covered by other
  specifications"). Aus dem Fey-Datenblatt ist der Pegel damit prinzipiell
  nicht ableitbar – auch nicht aus dem Wort "SBS Compliant".
- **SMBus 2.0, Tab. 2** (§3.1.2.1): VDD nominal **2,7–5,5 V** ("3 to 5 Volts
  ±10 %"), VIL ≤0,8 V, **VIH ≥2,1 V**. SMBus 3.3 erweitert auf 1,62–5,5 V und
  senkt VIH auf 1,35 V; Anhang B.1: Geräte mit unterschiedlichem VDD dürfen am
  selben Bus hängen.
- **Folge: eine feste Spannungsebene legt die Norm nicht fest.** Sie erlaubt
  ausdrücklich 5 V. Die Norm beantwortet die Frage nach dem Pegelwandler also
  nicht, sie grenzt sie nur ein.
- Konstruktiv: der Bus lässt sich auf 3,3 V **festnageln**, indem man selbst
  Pull-ups nach 3,3 V setzt – mit VIH ≥2,1 V ist 3,3 V für den Pack sicher
  gelesen. Gefährlich ist nur der umgekehrte Fall: zieht der Pack seine eigenen
  Pull-ups nach 5 V, sieht der ESP8266 5 V (absolut max. 3,6 V) → dann
  Pegelwandler. Deshalb bleibt es beim Messen.
- Timing, die die Firmware einhalten muss: fSMB **10–100 kHz** (Class),
  tTIMEOUT 25–35 ms Clock-low. Nach einem Timeout den Bus zurücksetzen, nicht
  ewig auf ACK warten.
- **Off State** (SBS §4.4.3): SCL und SDA länger als 2,5 s low → Pack darf
  abschalten. Der Host darf beide Leitungen low ziehen, um den Pack zu
  resetten; danach Bus freigeben und neu adressieren. Kein ACK beim ersten
  Zugriff ist daher normal, kein Defekt.
- **Safety Signal / T-Pin** (§4.4.4): 425–3150 Ω zwischen T-Pin und GND heißt
  "nicht laden". Der Fey-Pack hat **keinen T-Pin** (NTC n/a, nur 4 Pins) –
  das passt nicht zu "SBS Compliant 4S CC/CV Charger" im Datenblatt. Offener
  Widerspruch, beim Laden klären.

## I²C / SBS

- D1 mini: SDA = GPIO4 (D2), SCL = GPIO5 (D1). 100 kHz fahren (SMBus-Class
  schafft max. 100 kHz), nicht unter 10 kHz; der ESP8266 kann nur Master
  (Slave fehlt Clock-Stretching).
- SBS-Adresse **0x0B**, Register als Little-Endian-Words:
  0x08 Temperatur (0,1 K), 0x09 Spannung (mV), 0x0A Strom (mA, signed),
  0x0F RemainingCapacity, 0x10 FullChargeCapacity, 0x17 CycleCount.
- Pull-ups: Pack zuerst messen. Hat er eigene, keine zusätzlichen ergänzen
  (parallel zu viel). Bestückt sind **3 kΩ gegen 3,3 V** (siehe Schaltplan);
  das liegt über dem SMBus-Low-Power-Limit von 350 µA, lief im Test aber
  stabil.
- Der Pack ist 16,8 V: **nie** auf GPIO/A0. Versorgung des D1 mini nur über
  Schaltregler (16,8 V → 3,3 V), ein LDO verheizt >1 W.
- A0 des D1 mini liegt hinter 100k/220k und verträgt max. ~3,3 V (Chip-ADC
  0–1,0 V) – nur relevant, falls doch analog gemessen wird.

## Schaltplan (`hardware/`)

- Direktverbindung, **kein Pegelwandler** eingeplant: U1 D1 mini (USB) mit
  D1/SCL = GPIO5 und D2/SDA = GPIO4 an J1 Pin 2/3. GND durchverbunden, Pin 1
  (Bat+) bleibt offen – der D1 mini wird über USB versorgt, nicht aus dem Pack.
- Pull-ups **R1/R2** gegen 3,3 V, jeweils über Lötjumper **JP1/JP2**
  abschaltbar. Im Plan stehen 4,7 k, **bestückt sind 3 kΩ** (Stand
  2026-11-13). SMBus 2.0 erlaubt bei 3,3 V nur 8,3–29 kΩ (350 µA); 3 kΩ
  zieht ~1 mA und ist damit I²C-, nicht SMBus-konform. Läuft am Pack stabil,
  bei Auffälligkeiten zwei 3 kΩ in Reihe (≈6 kΩ) je Leitung.
- J1 = `Conn_01x04` mit Footprint
  `Connector_Molex:Molex_Micro-Fit_3.0_43650-0415_1x04_P3.00mm_Vertical`
  (PCB-Gegenstück zur Kabelbuchse 43645-0400). Pin 1/2/3/4 = Bat+/SCL/SDA/GND.
- U1 ist ein eigenes Symbol in `hardware/libs/SMBusPeek.kicad_sym`
  (links Versorgung/RST, rechts die D-Pins). Die Nummern 1–16 sind funktional
  vergeben, **nicht** in Stiftleisten-Reihenfolge; ein Footprint ist bewusst
  nicht gesetzt, weil der D1 mini als fertiges Modul gesteckt wird.
- Prüfen/Exportieren (kicad-cli aus der KiCad-10-Installation):
  `kicad-cli sch erc -o hardware/erc.rpt hardware/SMBusPeek.kicad_sch`
  und `kicad-cli sch export pdf|svg`. Alle Pins liegen auf dem 1,27-mm-Raster,
  sonst meckert der ERC „off grid“.
- Offen: Die Ruhespannung von SDA/SCL am Pack ist weiterhin nicht gemessen.
  Im Test am 2026-11-13 lief der Bus mit der aktuellen Bestückung stabil bei
  100 kHz – welche Pull-ups dabei wirken (Pack eigene, JP1/JP2 oder die
  schwachen internen des ESP8266), ist damit noch nicht geklärt. Erst wenn
  der Pack nach 5 V zieht, ist ein Pegelwandler nötig.

## Firmware (`firmware/`)

PlatformIO mit Arduino-Framework, Umgebung `d1_mini`. PlatformIO Core 6.2.0
liegt unter `%USERPROFILE%\.platformio\penv\Scripts\pio.exe` (über die
Codium-Erweiterung installiert), die ESP8266-Plattform 4.2.1 ist installiert.

```
pio run                # bauen
pio run -t upload      # flashen (Port ggf. mit --upload-port COMx)
pio device monitor     # 115200 Baud
```

- `src/sbs.h` / `src/sbs.cpp`: SBS-Schicht. Adresse 0x0B, Wort- und
  Blockread, **Write Word** (`writeWord`), Bus-Recovery, Off-State-Reset.
  Pins über `SBS_SDA_PIN` (4) und `SBS_SCL_PIN` (5) einstellbar, in
  `platformio.ini` auch als `-D` gesetzt.
- `src/main.cpp`: Kommandozeile über USB-Serial und JSON-Ausgabe.

### Kommandos

| Kommando | Wirkung |
| --- | --- |
| `read` | eine Messung, eine JSON-Zeile |
| `start [ms]` | dauerhaft senden, Standard 1000 ms, erlaubt 100–60000 |
| `stop` | dauerhaftes Senden beenden |
| `id` | Hersteller, Name, Chemie, Seriennummer, Baudatum, Designwerte |
| `scan` | I²C-Adressen 0x08–0x77 suchen |
| `raw <reg>` | Register als Rohwert lesen, z. B. `raw 0x0d` |
| `block <reg>` | Block lesen (Text, sonst Hex), z. B. `block 0x21` |
| `write <reg> <wert>` | Wort schreiben (SMBus Write Word), z. B. `write 0x01 0x012C` |
| `status` | BatteryStatus, BatteryMode, MaxError, AbsoluteSoC als JSON |
| `dump` | alle Register 0x00–0x1C und Blockreads 0x20–0x23 als eine JSON-Zeile |
| `reset` | beide Leitungen 2,6 s low, danach neu adressieren |
| `help` | Kommandoliste |

`write` meldet `# ACK` oder `# kein ACK (Pack gesperrt oder Register nur
lesbar)`. Ein fehlender ACK ist die normale Antwort auf ein Nur-Lese-Register
oder einen gesperrten Pack, kein Defekt. Am 2026-11-13 geprüft: `write 0x01
<gleicher Wert>` → ACK, Wert unverändert; `write 0x09 0x1234` (Spannung, nur
lesbar) → kein ACK, Messwerte danach unverändert.

Achtung: `ManufacturerAccess` (0x00) ist der Weg zu seal/unseal. Falsche
Werte können den Pack sperren oder abschalten – nur schreiben, wenn Register
und Wert belegt sind.

### Schreibbare Register

SBS 1.1 nennt in §5.1 nur fünf Funktionen als „Read or Write Word“ – alles
andere in §5.1 ist nur lesbar. Die Firmware kennt jedes Register, das Pack
entscheidet per ACK, ob ein Schreibzugriff erlaubt ist.

| Register | Name | Was das Schreiben bewirkt |
| --- | --- | --- |
| 0x00 | ManufacturerAccess | herstellerspezifisch, bei vielen Packs seal/unseal – **nicht getestet** |
| 0x01 | RemainingCapacityAlarm | Schwelle für den Restkapazitäts-Alarm (0 = aus) |
| 0x02 | RemainingTimeAlarm | Schwelle für den Restzeit-Alarm in min (0 = aus) |
| 0x03 | BatteryMode | nur das obere Byte (Bits 8, 9, 13, 14, 15); Bits 0–7 und reservierte Bits sind lesbar bzw. unzulässig |
| 0x04 | AtRate | Bezugslast für die Prognosen 0x05–0x07: positiv = Laden, negativ = Entladen, 0 = keine Prognose |

`0x14 ChargingCurrent` und `0x15 ChargingVoltage` sind laut §5.2 **Ausgaben des
Packs** an ein Ladegerät (Broadcast) – der Host liest sie nur, schreiben kann
er sie nicht.

Am Pack geprüft (2026-11-13, jeweils aktueller Wert, danach zurückgelesen):

| Register | Vorgabe | Antwort | Wert danach |
| --- | --- | --- | --- |
| 0x01 | 0x012C (300 mAh) | `# ACK` | 0x012C |
| 0x02 | 0x000A (10 min) | `# ACK` | 0x000A |
| 0x03 | 0x0001 | `# ACK` | 0x0001 |
| 0x04 | 0x0000 | `# ACK` | 0x0000 |

Dass ein Schreibzugriff wirklich wirkt, zeigt AtRate: `write 0x04 0xFE0C`
(−500 mA) → `# ACK`, Read-back 0xFE0C, **AtRateTimeToEmpty (0x06) springt von
65535 auf 357 min** – 2979 mAh / 500 mA = 5,96 h. Nach `write 0x04 0x0000`
steht 0x06 wieder auf 65535 (nicht verfügbar). Die Werte 0x01/0x02 werden vom
Pack also angenommen, ein geänderter Wert wurde dort aber nicht auf einen
Alarm hin geprüft.

### Ausgabe

Eine JSON-Zeile pro Messung, `ok:0` bei Fehler:

```json
{"ms":12345,"ok":1,"v_mv":15823,"i_ma":-120,"t_c":24.9,"soc":87,
 "rc":2910,"fcc":3350,"cycles":12,"cap_unit":"mAh"}
```

`i_ma` ist signed (positiv = Laden, negativ = Entladen). `t_c` ist aus
0,1 K umgerechnet und auf 0,1 °C gerundet. `rc`/`fcc` stehen in `cap_unit`,
das aus dem CAPACITY_MODE-Bit in BatteryMode() folgt (mAh oder 10 mWh).

`status` liefert eine eigene Zeile mit denselben Kurznamen wie die Register:

```json
{"ms":2256,"ok":1,"st":2256,"err":0,"ovc":0,"tc":0,"ot":0,"td":1,
 "rca":0,"rta":0,"init":1,"dis":1,"full":0,"empty":1,"maxerr":1,
 "asoc":94,"mode":1,"cap10mwh":0,"chgm":0,"alarm":0,"prim":0,"chgc":0,
 "cond":0,"pbsup":0,"icc":1}
```

| Feld | Register | Bedeutung |
| --- | --- | --- |
| `st` | 0x16 | BatteryStatus roh |
| `err` | 0x16 Bits 3..0 | ERROR_CODE: 0 = OK, 1 = Busy, 3 = Kommando nicht unterstützt, 4 = Zugriff verweigert, 7 = unbekannter Fehler |
| `ovc` | 0x16 Bit 15 | OVER_CHARGED_ALARM |
| `tc` | 0x16 Bit 14 | TERMINATE_CHARGE_ALARM (Laden beenden) |
| `ot` | 0x16 Bit 12 | OVER_TEMP_ALARM |
| `td` | 0x16 Bit 11 | **TERMINATE_DISCHARGE_ALARM (Entladen gesperrt)** |
| `rca` / `rta` | 0x16 Bit 9 / 8 | REMAINING_CAPACITY_ALARM / REMAINING_TIME_ALARM |
| `init` | 0x16 Bit 7 | INITIALIZED |
| `dis` | 0x16 Bit 6 | DISCHARGING |
| `full` / `empty` | 0x16 Bit 5 / 4 | FULLY_CHARGED / FULLY_DISCHARGED |
| `maxerr` | 0x0C | MaxError in % |
| `asoc` | 0x0E | AbsoluteStateOfCharge in % |
| `mode` | 0x03 | BatteryMode roh |
| `cap10mwh` | 0x03 Bit 15 | CAPACITY_MODE (1 = 10 mWh) |
| `chgm` | 0x03 Bit 14 | CHARGER_MODE (Laden angefordert) |
| `alarm` | 0x03 Bit 13 | ALARM_MODE (AlarmWarning-Broadcast aus) |
| `prim` | 0x03 Bit 9 | PRIMARY_BATTERY |
| `chgc` | 0x03 Bit 8 | CHARGE_CONTROLLER_ENABLED |
| `cond` | 0x03 Bit 7 | CONDITION_FLAG |
| `pbsup` | 0x03 Bit 1 | PRIMARY_BATTERY_SUPPORT |
| `icc` | 0x03 Bit 0 | INTERNAL_CHARGE_CONTROLLER (nur lesbar) |

Bits 13 und 10 in BatteryStatus sowie 2–6, 10–12 in BatteryMode sind laut
§5.1.21/§5.1.4 reserviert und werden nicht ausgewertet.

Alle vier Register müssen lesbar sein, sonst kommt `ok:0` – eine halbe
Statuszeile wäre irreführend.

`dump` schreibt alle Funktionen aus §5.1 in **eine** Zeile: `r00`…`r1C` sind
die Wortregister, `b20`…`b23` die Blockreads (Text; `b23` als Hex, weil
ManufacturerData herstellerspezifisch und meist binaer ist). Nicht lesbare
Wörter stehen als `-1`, nicht lesbare Blöcke als `""`, damit die Zeile
maschinell auswertbar bleibt.

```json
{"ms":3960,"ok":1,"dump":1,"r00":0,"r01":300,…,"r1C":1234,
 "b20":"FEY","b21":"HRDL-0007-XXXXXXXXXX","b22":"LION","b23":"00 … 09 00 00"}
```

Die Einheiten deutet die Firmware hier absichtlich nicht: `dump` ist die
Rohsicht, die Auswertung macht die GUI (eine Tabelle mit Einheiten).

### Verhalten am Bus

- `probe()` versucht dreimal, dazwischen einmal `recoverBus()`: bis zu neun
  Takte auf SCL, dann STOP, dann `Wire.begin()` neu.
- Kein ACK beim ersten Zugriff ist normal (SBS 1.1 §4.4.2: der Pack kommt
  erst mit steigenden Leitungen in den On State) – erst nach den
  Wiederholungen gilt es als Fehler.
- Clock-Stretch-Limit steht auf 30 ms, passend zu tTIMEOUT 25–35 ms aus
  SMBus 2.0. Nach einem Timeout wird zurückgesetzt, nicht endlos gewartet.
- `reset` zieht beide Leitungen 2,6 s low. Das ist laut §4.4.3 der Weg in den
  Off State (Pack schläft), kein Aufweckbefehl.

### Grenzen

- **Kein PEC.** SMBus-Paketprüfung ist nicht implementiert. Das Pack meldet in
  SpecificationInfo (0x1A) = 0x0031 Version 3, also „SBS 1.1 mit PEC“ – es
  akzeptiert Befehle ohne PEC trotzdem, Fehler fallen nur als fehlender ACK auf.
- Blockread (0x20–0x23) fordert 33 Byte an und wertet nur die ersten
  Längenbytes aus; mehr als 32 Zeichen werden abgeschnitten. Ist ein Block
  nicht druckbar, liefert `block` die Bytes als Hex.
- **ERROR_CODE 7 nach Blockreads.** Das Pack setzt nach einem Blockread
  ERROR_CODE = 7 („unbekannter Fehler“), obwohl die Daten sauber ankommen; ein
  erfolgreicher Wortzugriff setzt den Code zurück. `dump` liest deshalb am Ende
  einmal die Spannung (Wert verworfen), damit der nächste `status` sauber ist.
  Ein `block` von Hand hinterlässt den Code sichtbar – kein Defekt.
- Kein WLAN, kein MQTT, keine Uhr – bewusst nur die USB↔SMBus-Brücke.
- `printf` mit `%f` wird vermieden (Temperatur als Ganzzahl formatiert).

## GUI (`gui/`)

Tkinter-Fenster für Windows, das dieselben Kommandos über USB-Serial schickt:
Messwerte live, `id`/`scan`/`read`, Live-Modus, Register lesen (`raw`) und
schreiben (`write`), `reset`, alle SBS-Register als Tabelle (`dump`) und ein
Freitextfeld. Kein WLAN, keine Cloud – nur eine Bedienoberfläche für die
Firmware.

```
gui\start.cmd          # legt beim ersten Mal das venv an und startet die GUI
```

- `.venv` legt `start.cmd` beim ersten Start an (Python 3, Tkinter aus der
  Stdlib, `pyserial` aus `gui/requirements.txt`). `start.cmd` startet mit
  `pythonw.exe`, damit kein Konsolenfenster daneben aufgeht; `.venv/` ist in
  `gui/.gitignore` und gehört nicht ins Repo.
- Portauswahl kommt aus `serial.tools.list_ports`. **Port-Öffnen zieht
  DTR/RTS → der D1 mini wird zurückgesetzt**; die GUI wartet deshalb 1,2 s
  und schickt dann selbst `id`.
- Lesen läuft in einem Thread, Zeilen gehen über eine Queue an `after(100)`
  im Tk-Hauptthread. Zeilen mit `#` landen im Protokoll, `{…}` mit `ok:1`
  aktualisieren die Messwerte, `ok:0` wird rot geloggt. Die Boot-Ausgabe des
  ROM (kein ASCII) wird verworfen.
- `Schreiben (write) …` und `reset …` fragen vorher nach. Schreibzugriffe
  können den Pack sperren, deshalb ist die Rückfrage kein Klicken aus
  Gewohnheit. Bei den bekannten R/W-Registern (0x01–0x04) steht in der
  Rückfrage zusätzlich, was der Wert bedeutet (`WRITE_HINTS`).
- Das **Statusfeld** zeigt BatteryStatus, BatteryMode, Sperren, Error-Code,
  Alarme, den Zustand (initialisiert/entlädt/voll) und Abs. SoC sowie MaxError.
  Es wird beim Verbinden, nach jeder Messung und im Live-Betrieb höchstens
  alle 5 s über `status` nachgezogen; im Protokoll steht dazu eine
  Kurzfassung statt der Rohzeile.
- **Alle SBS-Werte …** öffnet ein eigenes Fenster mit allen 33 Funktionen aus
  §5.1: Funktion, Zugriff (`R/W` oder `R`), Register, Rohwert (hex und
  dezimal) und der aufbereitete Wert. Die Firmware liefert nur Rohwerte
  (`dump`), die GUI rechnet sie um – 65535 wird zu „nicht verfügbar“,
  Temperaturen zu °C, SpecificationInfo zu Version/Revision/Skalen,
  ManufactureDate zu JJJJ-MM-TT, Kapazitäten in der Einheit aus
  CAPACITY_MODE. Nicht lesbare Register erscheinen rot als „nicht lesbar“.
- Schreiben geht direkt aus der Tabelle: Zeile wählen und **Schreiben …**
  drücken oder doppelklicken. Der Dialog ist mit dem aktuellen Rohwert
  vorbelegt, versteht `0x012C` und `300`, und schickt erst nach der
  Bestätigung. Nur die fünf R/W-Register (0x00–0x04) sind zugelassen; bei
  allen anderen und bei den Blockregistern 0x20–0x23 kommt ein Hinweis statt
  eines Schreibbefehls. Nach dem Senden holt die GUI den `dump` nach 1,2 s
  neu, damit der Read-back in der Tabelle steht.
- Beim Verbinden schickt die GUI zuerst `stop`, dann `id`, dann `status` –
  sonst gehen die Antworten in einem noch laufenden `start`-Strom unter.
- Register- und Werteingabe verstehen `0x0d`, `13` und `0d` (`int(x, 0)` mit
  Hex-Fallback).
- Ohne Verbindung sind alle Kommandoknöpfe gesperrt; der Verbinden-Knopf
  trennt bei bestehender Verbindung (vorher wird `stop` geschickt).

## Messprotokoll

Erster Lauf mit echtem Pack am **2026-11-13**: D1 mini über USB an COM4
(CH340), Pack am Stecker, `firmware/` geflasht, Abfrage über die
serielle Kommandoschnittstelle. Seriennummer und DeviceName sind in dieser
Fassung maskiert (echte Werte nur lokal).

| Wert | Register | Ergebnis |
| --- | --- | --- |
| Adresse | — | 0x0B antwortet, sonst kein Gerät am Bus |
| Hersteller | 0x20 | `FEY` |
| DeviceName | 0x21 | `HRDL-0007-XXXXXXXXXX` |
| Chemie | 0x22 | `LION` |
| Seriennummer | 0x1C | XXXX |
| Baudatum | 0x1B | 2024-04-17 |
| DesignCapacity | 0x18 | 3200 mAh |
| DesignVoltage | 0x19 | 14400 mV |
| BatteryMode | 0x03 | 0x0001 → CAPACITY_MODE = 0 (mAh) |
| Spannung | 0x09 | 16433 mV (Ruhe) |
| Strom | 0x0A | 0 mA (Ruhe) |
| Temperatur | 0x08 | 20,9 °C |
| RelativeStateOfCharge | 0x0D | 100 % |
| RemainingCapacity | 0x0F | 2979 mAh |
| FullChargeCapacity | 0x10 | 2979 mAh |
| CycleCount | 0x17 | 19 |

Auffälligkeiten:

- **DesignCapacity ist 3200 mAh, nicht 3350 mAh** wie im Fey-Datenblatt
  (typisch). Für Prozentrechnung den Registerwert nehmen, nicht das
  Datenblatt.
- FCC 2979 mAh bei 3200 mAh Design → rund 93 % Restkapazität nach 19 Zyklen.
- `BatteryMode` = 0x0001: Bit 0 = INTERNAL_CHARGE_CONTROLLER (nur lesbar) ist
  gesetzt, der Pack hat also einen internen Ladecontroller; Bit 8
  (CHARGE_CONTROLLER_ENABLED) ist 0, er ist also nicht aktiv. Bit 15
  (CAPACITY_MODE) = 0 → mAh.
- Blockread (0x20–0x22) funktioniert, die Strings kommen ohne PEC sauber an.
- Ein fehlender ACK beim ersten Zugriff trat nicht auf – die Leitungen gehen
  beim Anstecken hoch, der Pack war also im On State.

### Alle Register (`dump`)

Vollständige Antwort auf `dump`, gegengeprüft in der GUI-Tabelle (Ruhezustand,
2026-11-13):

| Register | Name | Wert | Deutung |
| --- | --- | --- | --- |
| 0x00 | ManufacturerAccess | 0 | herstellerspezifisch, hier 0 |
| 0x01 | RemainingCapacityAlarm | 300 mAh | ≈ 10 % von 3200 mAh |
| 0x02 | RemainingTimeAlarm | 10 min | |
| 0x03 | BatteryMode | 0x0001 | interner Ladecontroller vorhanden, CAPACITY_MODE = 0 |
| 0x04 | AtRate | 0 | kein AtRate-Betrieb |
| 0x05 | AtRateTimeToFull | 65535 | nicht verfügbar |
| 0x06 | AtRateTimeToEmpty | 65535 | nicht verfügbar |
| 0x07 | AtRateOK | 1 | ja |
| 0x08 | Temperature | 2943 | 21,0 °C |
| 0x09 | Voltage | 16432 mV | |
| 0x0A | Current | 0 mA | Ruhe |
| 0x0B | AverageCurrent | 0 mA | |
| 0x0C | MaxError | 1 % | |
| 0x0D | RelativeStateOfCharge | 100 % | |
| 0x0E | AbsoluteStateOfCharge | 94 % | |
| 0x0F | RemainingCapacity | 2979 mAh | |
| 0x10 | FullChargeCapacity | 2979 mAh | |
| 0x11 | RunTimeToEmpty | 65535 | nicht verfügbar (kein Entladen) |
| 0x12 | AverageTimeToEmpty | 65535 | nicht verfügbar |
| 0x13 | AverageTimeToFull | 65535 | nicht verfügbar |
| 0x14 | ChargingCurrent | 1625 mA | passt zum Datenblatt (max. 1625 mA) |
| 0x15 | ChargingVoltage | 16800 mV | passt zum Datenblatt (16,8 V) |
| 0x16 | BatteryStatus | 0x08D0 | siehe „Ausgang gesperrt“ |
| 0x17 | CycleCount | 19 | |
| 0x18 | DesignCapacity | 3200 mAh | |
| 0x19 | DesignVoltage | 14400 mV | |
| 0x1A | SpecificationInfo | 0x0031 | Version 3 = SBS 1.1 mit PEC, Revision 1, VScale/IScale 1 |
| 0x1B | ManufactureDate | 0x5891 | 2024-04-17 |
| 0x1C | SerialNumber | XXXX | |
| 0x20 | ManufacturerName | `FEY` | |
| 0x21 | DeviceName | `HRDL-0007-XXXXXXXXXX` | |
| 0x22 | DeviceChemistry | `LION` | |
| 0x23 | ManufacturerData | 14 Byte, `00 … 09 00 00` | herstellerspezifisch, überwiegend 0 |

Bemerkenswert: **0x14/0x15 liefern genau die Datenblatt-Grenzen** (1625 mA,
16800 mV) – der Pack beschreibt damit sein eigenes Ladeverfahren. Für einen
Ladeversuch ist das die Referenz, nicht ein geratener Wert.

### Ausgang gesperrt (2026-11-13)

Der Pack war vorher tiefentladen (rund 3,0 V pro Zelle), die Zellen wurden
einzeln nachgeladen. Danach lieferte **Pin 1 (Bat+) keine Spannung**, die
SBS-Antworten liefen aber weiter.

`status` am Pack:

| Wert | Ergebnis |
| --- | --- |
| BatteryStatus (0x16) | **0x08D0** → TERMINATE_DISCHARGE_ALARM (Bit 11) = 1, INITIALIZED (7) = 1, DISCHARGING (6) = 1, FULLY_DISCHARGED (4) = 1, ERROR_CODE = 0 |
| BatteryMode (0x03) | 0x0001 (interner Ladecontroller vorhanden, nicht aktiv) |
| MaxError (0x0C) | 1 % |
| AbsoluteStateOfCharge (0x0E) | 94 % |
| Spannung (0x09) | 16431 mV |

Deutung: Der Gauge meldet **keinen Fehler** (ERROR_CODE 0), aber er fordert
selbst **Entladen beenden** an (TERMINATE_DISCHARGE_ALARM) und führt den Pack
als **voll entladen** (FULLY_DISCHARGED) – bei 94 % AbsoluteStateOfCharge und
16,4 V. Diese Kombination ist das Ergebnis der Tiefentladung: die
Abschaltbedingung wurde ausgelöst und wird erst über den Ladepfad
zurückgesetzt.

Wer den FET öffnet, ist von außen nicht zu trennen: der Gauge fordert die
Abschaltung an, die **Safety Unit** ist die Ebene, die den Ausgang tatsächlich
trennt. Die SBS-Elektronik hängt weiter direkt an den Zellen (deshalb weiterhin
16,4 V und saubere Register), die Strecke zum Ausgang ist offen.

Datenblatt-Werte der SU (per Textextraktion aus dem PDF geprüft, Zeilen
„over voltage (per cell)“ / „under voltage (per cell)“):

| Schutz | cut off | release |
| --- | --- | --- |
| over voltage | 4225 mV ±25 | 4050 mV ±25 |
| under voltage | 3000 mV ±50 | 3300 mV ±50 |

Die Zellen standen bei 3,0 V, also genau auf der Abschaltschwelle. Weil die
Freigabe bei 3,3 V/Zelle liegt, müsste die SU bei den jetzigen ~4,11 V offen
sein – ist sie aber nicht. Nächster Schritt ist deshalb ein Ladeversuch am
Pack (4S-CC/CV, 16,8 V, auf 500 mA begrenzt), damit die SU den Ladepfad
sieht. Bleibt der Ausgang danach tot, ist sie verriegelt oder die
FET-/Sicherungsstrecke ist defekt.

**Nicht** überbrücken: die SU ist die einzige Schutzebene des 4S-Packs.

## Arbeitsweise

- Werte und Register erst gegen Datenblatt oder Messung belegen, dann in Code
  und Doku übernehmen.
- Erst am Labornetzteil mit Strombegrenzung testen, nicht am echten Pack.
- Doku-Sprache: Deutsch (wie dieses File).

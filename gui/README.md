# GUI

Tkinter-Fenster für SMBusPeek. Schickt dieselben Kommandos wie
das Terminal an die Firmware (`firmware/`), nur mit Knöpfen und Live-Anzeige.

## Start

```
start.cmd
```

Beim ersten Mal legt `start.cmd` das venv im Verzeichnis an und installiert
`pyserial` daraus. Voraussetzung ist Python 3 mit Tkinter im `PATH` (bei der
Windows-Installation ist beides dabei).

Von Hand:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe smbuspeek.py
```

## Bedienung

1. D1 mini per USB anschließen, Port wählen, **Verbinden**.
   Das Öffnen des Ports setzt den ESP8266 zurück – die GUI wartet kurz und
   holt dann selbst `id`.
2. **read** für eine Einzelmessung, **Live starten** für eine Zeile pro
   Sekunde, **Live stoppen** beendet das.
3. **Status** zeigt `BatteryStatus` (0x16) und `BatteryMode` (0x03) dekodiert:
   welche Sperre aktiv ist (Laden/Entladen), welche Alarme anstehen, den
   Zustand (initialisiert, entlädt, voll geladen, voll entladen), den
   ERROR_CODE, `AbsoluteStateOfCharge` und `MaxError`. Der Knopf `status`
   holt die Werte sofort; sonst werden sie beim Verbinden, nach jeder Messung
   und im Live-Betrieb alle 5 s nachgezogen.
4. **Alle SBS-Werte …** öffnet eine Tabelle mit allen Funktionen aus SBS 1.1
   §5.1 (Register 0x00–0x1C und die Blockreads 0x20–0x23): Funktion, Zugriff
   (`R/W` oder `R`), Register, Rohwert und der aufbereitete Wert mit Einheit.
   `Aktualisieren` holt die Werte neu (Kommando `dump`); 65535 erscheint als
   „nicht verfügbar“, nicht lesbare Register stehen rot als „nicht lesbar“.
   Schreiben geht direkt aus der Tabelle: Zeile wählen und **Schreiben …**
   drücken oder doppelklicken. Der Dialog ist mit dem aktuellen Rohwert
   vorbelegt und versteht `0x012C` wie `300`; geschickt wird erst nach der
   Bestätigung. Zugelassen sind nur die fünf R/W-Register 0x00–0x04
   (SBS 1.1 §5.1.1–§5.1.5) – bei allen anderen und bei den Blockregistern
   kommt ein Hinweis. Danach holt die GUI den `dump` neu, sodass der
   Read-back in der Tabelle steht.
5. **Register**: Nummer eintragen (`0x0d`, `13` oder `0d`) und **Lesen (raw)**
   bzw. **Schreiben (write) …** wählen. Schreiben fragt vorher nach, weil
   falsche Werte den Pack sperren können.
6. **Freies Kommando** schickt beliebigen Text an die Firmware, z. B.
   `start 500`, `raw 0x03` oder `dump`.

Das Protokoll rechts zeigt alle Zeilen mit Zeitstempel: `>` gesendet,
`#` Antworttext, `{…}` Messwerte; Fehler (`kein ACK`, `ok:0`) erscheinen rot.

## Schreibbare Register

Laut SBS 1.1 §5.1.1–§5.1.5 nehmen nur fünf Register einen Schreibzugriff an:

| Register | Name | Hinweis |
| --- | --- | --- |
| 0x00 | ManufacturerAccess | herstellerspezifisch, oft seal/unseal – im Test bewusst nicht beschrieben |
| 0x01 | RemainingCapacityAlarm | Restkapazitäts-Alarm, 0 = aus |
| 0x02 | RemainingTimeAlarm | Restzeit-Alarm in min, 0 = aus |
| 0x03 | BatteryMode | nur Bits 8, 9, 13, 14, 15 |
| 0x04 | AtRate | Bezugslast für die Prognosen 0x05–0x07 |

Alles andere (z. B. 0x09 Spannung, 0x14/0x15 Ladevorgaben) ist nur lesbar; ein
Schreibversuch dort ergibt `# kein ACK`. Am Pack geprüft (2026-11-13): 0x01,
0x02, 0x03 und 0x04 antworten mit `# ACK`, und `AtRate` = −500 mA lässt
`AtRateTimeToEmpty` (0x06) auf 357 min springen – der Schreibzugriff wirkt
also wirklich.

## Grenzen

- Pro Fenster eine Verbindung; die Firmware ist eine reine USB↔SMBus-Brücke
  ohne Puffer, deshalb immer erst trennen, bevor ein anderes Programm den
  Port öffnet.
- Kein Mitschnitt in eine Datei – dafür `pio device monitor` oder ein
  eigenes Skript neben dem Fenster benutzen.

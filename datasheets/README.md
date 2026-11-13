# Datenblätter und Normen

Die PDFs von Fey Elektronik und den Standardisierungsgremien (SBS-IF, SMIF)
liegen **nicht** im Repo: sie sind frei abrufbar, aber nicht frei weitergebbar
(SBS 1.1 © Benchmarq, Duracell, Energizer, Intel, Linear Technology, Maxim,
Mitsubishi, National Semiconductor, Toshiba Battery, Varta; SMBus © SMIF –
jeweils all rights reserved). Für den Nachbau bitte selbst herunterladen.

| Dokument | Quelle | Inhalt |
| --- | --- | --- |
| `db-pa-lnb117.pdf` | Fey, 09.11.2017 | 4S1P 18650 (Panasonic NCR18650B), 14,4 V / 3,35 Ah / 48 Wh, SBS-konform, Molex Microfit 43645-0400 (Bat+ / SCL / SDA / GND) |
| SBS Smart Battery Data Spec 1.1 | sbs-forum.org, 11.12.1998 | Register, Protokolle, Off State, Safety Signal. **Nur Daten, keine Elektrik** |
| SMBus Specification 2.0 | smbus.org, 03.08.2000 | Elektrik der Bauzeit: VDD 2,7–5,5 V, VIH ≥2,1 V |
| SMBus Specification 3.3 | smbus.org, 12.05.2024 | aktuelle Elektrik: VDD 1,62–5,5 V, VIH ≥1,35 V |

Quellen:

- <https://www.feyelektronik.de/downloads/db-pa-lnb117.pdf>
- <https://www.feyelektronik.de/en/products/lithium-ion-packs/>
- <http://sbs-forum.org/specs/sbdat110.pdf>
- <https://smbus.org/specs/smbus20.pdf>
- <https://smbus.org/specs/SMBus_3_3_20240512.pdf>

## Worauf man beim Nachladen hereinfällt

- Der Fey-Katalog verlinkt `db-pa-lnb117-r002.pdf` – dieser Pfad liefert
  **404**. Erreichbar ist nur `db-pa-lnb117.pdf`; der Dateiname trägt die
  Revision nicht, der Inhalt ist aber `PA-LNB117.R002`.
- Das Fey-PDF ist ein Ein-Seiter mit Grafiken: reine Textextraktion liefert die
  Werte unsortiert. Pinbelegung und Grenzwerte nur mit Koordinaten bzw. aus dem
  gerenderten PDF lesen.
- Die SBS-Spec 1.1 verweist für Elektrik auf SMBus 1.1, das nicht mehr auf
  smbus.org liegt. Deshalb lohnt 2.0: gleiche Schwellen (0,8 / 2,1 V), besser
  dokumentiert.

Welche Werte aus diesen Dokumenten in dieses Projekt übernommen wurden, steht
mit Zitatstelle in [`AGENTS.md`](../AGENTS.md).

"""SMBusPeek – kleine GUI fuer den D1 mini als SBS-Bruecke.

Startet ueber ``gui/start.cmd`` oder direkt::

    gui\\.venv\\Scripts\\pythonw.exe gui\\smbuspeek.py

Die Firmware antwortet mit ``#`` (Text) oder ``{`` (JSON) am Zeilenanfang,
siehe AGENTS.md. Alle Kommandos gehen zeilenweise ueber USB-Serial.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import serial
from serial.tools import list_ports

BAUD = 115200
DEFAULT_CAP_UNIT = "mAh"

# ERROR_CODE aus BatteryStatus(), Bits 3..0 (SBS 1.1 §5.1.16).
ERROR_CODES = {
    0: "OK",
    1: "Busy",
    2: "reserviert",
    3: "Kommando nicht unterstützt",
    4: "Zugriff verweigert",
    5: "Overflow/Underflow",
    6: "falsche Größe",
    7: "unbekannter Fehler",
}

# BatteryStatus (0x16): Alarmbits 15..8 und Statusbits 7..4 (SBS 1.1 §5.1.21).
STATUS_ALARM_BITS = (
    (15, "überladen"),
    (14, "Laden beenden"),
    (12, "Übertemperatur"),
    (11, "Entladen beenden"),
    (9, "Restkapazität"),
    (8, "Restzeit"),
)
STATUS_FLAG_BITS = (
    (7, "initialisiert"),
    (6, "entlädt"),
    (5, "voll geladen"),
    (4, "voll entladen"),
)

# BatteryMode (0x03), Bit 15 wird getrennt ausgewertet (CAPACITY_MODE).
MODE_BITS = (
    (0, "interner Ladecontroller vorhanden"),
    (1, "Primär/Sekundär unterstützt"),
    (7, "Conditioning angefragt"),
    (8, "Ladecontroller aktiv"),
    (9, "Primärbatterie"),
    (13, "AlarmWarning-Broadcast aus"),
    (14, "Charger-Mode angefragt"),
)

# Alle Funktionen aus SBS 1.1 §5.1: (Register, Name, Anzeigeart, schreibbar).
# Schreibbar sind laut §5.1.1–§5.1.5 nur 0x00 (herstellerabhängig), die beiden
# Alarmschwellen 0x01/0x02, BatteryMode 0x03 (nur obere Bytehälfte) und
# AtRate 0x04. Alles andere ist nur lesbar.
SBS_REGISTERS = (
    (0x00, "ManufacturerAccess", "access", True),
    (0x01, "RemainingCapacityAlarm", "capacity", True),
    (0x02, "RemainingTimeAlarm", "minutes", True),
    (0x03, "BatteryMode", "mode", True),
    (0x04, "AtRate", "rate", True),
    (0x05, "AtRateTimeToFull", "minutes", False),
    (0x06, "AtRateTimeToEmpty", "minutes", False),
    (0x07, "AtRateOK", "boolean", False),
    (0x08, "Temperature", "temperature", False),
    (0x09, "Voltage", "millivolt", False),
    (0x0A, "Current", "milliamp_signed", False),
    (0x0B, "AverageCurrent", "milliamp_signed", False),
    (0x0C, "MaxError", "percent", False),
    (0x0D, "RelativeStateOfCharge", "percent", False),
    (0x0E, "AbsoluteStateOfCharge", "percent", False),
    (0x0F, "RemainingCapacity", "capacity", False),
    (0x10, "FullChargeCapacity", "capacity", False),
    (0x11, "RunTimeToEmpty", "minutes", False),
    (0x12, "AverageTimeToEmpty", "minutes", False),
    (0x13, "AverageTimeToFull", "minutes", False),
    (0x14, "ChargingCurrent", "milliamp", False),
    (0x15, "ChargingVoltage", "millivolt", False),
    (0x16, "BatteryStatus", "status", False),
    (0x17, "CycleCount", "count", False),
    (0x18, "DesignCapacity", "capacity", False),
    (0x19, "DesignVoltage", "millivolt", False),
    (0x1A, "SpecificationInfo", "spec", False),
    (0x1B, "ManufactureDate", "date", False),
    (0x1C, "SerialNumber", "count", False),
)
SBS_BLOCKS = (
    (0x20, "ManufacturerName", "text"),
    (0x21, "DeviceName", "text"),
    (0x22, "DeviceChemistry", "text"),
    # Herstellerspezifisch und meist binaer -> Firmware liefert Hex.
    (0x23, "ManufacturerData", "hex"),
)

# Was beim Schreiben zu beachten ist (SBS 1.1 §5.1.1–§5.1.5).
WRITE_HINTS = {
    0x00: "ManufacturerAccess ist herstellerspezifisch – hier liegt bei vielen "
          "Packs seal/unseal. Nur schreiben, wenn der Wert belegt ist; ein "
          "falscher Wert kann den Pack sperren.",
    0x01: "Alarmschwelle für die Restkapazität, 0 schaltet den Alarm ab. "
          "Einheit folgt CAPACITY_MODE (mAh oder 10 mWh).",
    0x02: "Alarmschwelle für die Restzeit in Minuten, 0 schaltet den Alarm ab.",
    0x03: "Nur das obere Byte (Bits 8–15) ist schreibbar: 8 Ladecontroller "
          "aktiv, 9 Primärbatterie, 13 ALARM_MODE, 14 CHARGER_MODE, "
          "15 CAPACITY_MODE. Bits 0–7 sind nur lesbar, reservierte Bits "
          "dürfen nicht gesetzt werden.",
    0x04: "AtRate ist die Bezugslast für die Prognosen 0x05–0x07: positiv = "
          "Laden, negativ = Entladen, 0 = keine Prognose. Einheit folgt "
          "CAPACITY_MODE (mA oder 10 mW).",
}

# 65535 heißt bei den Zeit- und AtRate-Registern "nicht verfügbar" (§5.1).
NOT_AVAILABLE = 0xFFFF


def decode_status(value: int) -> tuple[list[str], list[str], list[str]]:
    """BatteryStatus zerlegen: (Sperren, Alarme, Statusflags)."""
    locks = []
    if value >> 14 & 1:
        locks.append("Laden")
    if value >> 11 & 1:
        locks.append("Entladen")
    alarms = [text for pos, text in STATUS_ALARM_BITS if value >> pos & 1]
    flags = [text for pos, text in STATUS_FLAG_BITS if value >> pos & 1]
    return locks, alarms, flags


def decode_mode(value: int) -> str:
    """BatteryMode lesbar machen; das CAPACITY_MODE-Bit steht immer dabei."""
    notes = ["Kapazität in 10 mWh" if value >> 15 & 1 else "Kapazität in mAh"]
    notes += [text for pos, text in MODE_BITS if value >> pos & 1]
    return ", ".join(notes)


def to_signed(value: int) -> int:
    """16-Bit-Wort als vorzeichenbehaftete Zahl."""
    return value - 0x10000 if value >= 0x8000 else value


def format_register(kind: str, value: int, unit: str) -> str:
    """Registerwert nach Einheit aus SBS 1.1 §5.1 formatieren."""
    if kind == "access":
        return "herstellerspezifisch"
    if kind == "capacity":
        return f"{value} {unit}"
    if kind == "minutes":
        return "nicht verfügbar" if value == NOT_AVAILABLE else f"{value} min"
    if kind == "mode":
        return decode_mode(value)
    if kind == "rate":
        return f"{to_signed(value)} {unit.replace('mAh', 'mA')}"
    if kind == "boolean":
        return "ja" if value else "nein"
    if kind == "temperature":
        return f"{value / 10 - 273.15:.1f} °C"
    if kind == "millivolt":
        return f"{value} mV ({value / 1000:.3f} V)"
    if kind == "milliamp":
        return f"{value} mA"
    if kind == "milliamp_signed":
        current = to_signed(value)
        note = "Laden" if current > 0 else "Entladen" if current < 0 else "Ruhe"
        return f"{current} mA ({note})"
    if kind == "percent":
        return f"{value} %"
    if kind == "status":
        locks, alarms, flags = decode_status(value)
        parts = []
        if locks:
            parts.append("Sperren: " + ", ".join(locks))
        if alarms:
            parts.append("Alarme: " + ", ".join(alarms))
        if flags:
            parts.append("Zustand: " + ", ".join(flags))
        return "; ".join(parts) if parts else "keine Alarme, keine Statusflags"
    if kind == "count":
        return f"{value}"
    if kind == "spec":
        return format_specification(value)
    if kind == "date":
        return format_manufacture_date(value)
    return f"{value}"


def format_specification(value: int) -> str:
    """SpecificationInfo: Version/Revision und die Skalen-Faktoren."""
    version = value >> 4 & 0x0F
    revision = value & 0x0F
    vscale = 10 ** (value >> 8 & 0x0F)
    iscale = 10 ** (value >> 12 & 0x0F)
    names = {2: "SBS 1.1", 3: "SBS 1.1 mit PEC"}
    return (f"Version {version} ({names.get(version, 'unbekannt')}), "
            f"Revision {revision}, VScale {vscale:g}, IScale {iscale:g}")


def format_manufacture_date(value: int) -> str:
    """ManufactureDate: (Jahr-1980)*512 + Monat*32 + Tag (§5.1.26)."""
    year = 1980 + (value >> 9 & 0x7F)
    month = value >> 5 & 0x0F
    day = value & 0x1F
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return f"ungültig (Rohwert {value})"
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_int(text: str) -> int | None:
    """Zahl aus dem Eingabefeld: 0x0d, 13 und 0d sind alle erlaubt."""
    text = text.strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        pass
    try:
        return int(text, 16)
    except ValueError:
        return None


class SerialLink:
    """Serielle Verbindung mit Lesethread; Zeilen landen in einer Queue."""

    def __init__(self) -> None:
        self._port: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.lines: queue.Queue[str] = queue.Queue()

    @property
    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    @property
    def port_name(self) -> str:
        return self._port.port if self._port is not None else ""

    def open(self, device: str) -> None:
        self.close()
        # Port-Oeffnen zieht DTR/RTS -> der D1 mini wird zurueckgesetzt.
        self._port = serial.Serial(device, BAUD, timeout=0.2)
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._port is not None:
            try:
                self._port.close()
            except Exception:  # Port kann schon weg sein (Kabel gezogen)
                pass
            self._port = None

    def send(self, command: str) -> None:
        if not self.is_open:
            raise RuntimeError("nicht verbunden")
        assert self._port is not None
        self._port.write((command.strip() + "\n").encode("ascii", "replace"))
        self._port.flush()

    def _read_loop(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            try:
                assert self._port is not None
                chunk = self._port.read(256)
            except Exception as exc:
                self.lines.put(f"# Lesefehler: {exc}")
                return
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                self.lines.put(self._clean(raw))

    @staticmethod
    def _clean(raw: bytes) -> str:
        """Zeile saeubern und ROM-Boot-Muell (nicht-ASCII) verwerfen."""
        text = raw.decode("utf-8", "replace").strip()
        text = "".join(ch for ch in text if ch >= " " or ch == "\t")
        if any(ord(ch) > 0x7E for ch in text):
            return ""
        return text


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SMBusPeek – SBS-Pack am D1 mini")
        self.geometry("1040x700")
        self.minsize(900, 620)

        self.link = SerialLink()
        self._port_map: dict[str, str] = {}
        self._live = False
        self._last_status_request = 0.0
        self.sbs_window: SbsWindow | None = None

        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        self.cmd_buttons: list[ttk.Button] = []
        self._build_connection(root)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self._build_values(left)
        self._build_status(left)
        self._build_commands(left)
        self._build_registers(left)
        self._build_free_text(left)
        self._build_log(right)

        self._refresh_ports()
        self._refresh_connection_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_lines)

    # ---- Aufbau -----------------------------------------------------

    def _build_connection(self, root: ttk.Frame) -> None:
        conn = ttk.LabelFrame(root, text="Verbindung", padding=8)
        conn.pack(fill="x")

        ttk.Label(conn, text="Port:").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(conn, textvariable=self.port_var, width=36,
                                     state="readonly")
        self.port_box.grid(row=0, column=1, padx=(4, 8), sticky="w")

        self.refresh_btn = ttk.Button(conn, text="Aktualisieren",
                                      command=self._refresh_ports)
        self.refresh_btn.grid(row=0, column=2, padx=2)

        self.connect_btn = ttk.Button(conn, text="Verbinden",
                                      command=self._toggle_connection)
        self.connect_btn.grid(row=0, column=3, padx=2)

        self.status_var = tk.StringVar(value="getrennt")
        ttk.Label(conn, textvariable=self.status_var).grid(row=0, column=4,
                                                           padx=(12, 0), sticky="w")
        conn.columnconfigure(4, weight=1)

    def _build_values(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Messwerte", padding=8)
        frame.pack(fill="x")

        self.value_vars: dict[str, tk.StringVar] = {}
        # Zwei Spalten, damit die linke Leiste flach bleibt.
        pairs = (
            (("v_mv", "Spannung"), ("soc", "Ladezustand")),
            (("i_ma", "Strom"), ("rc", "Restkapazität")),
            (("t_c", "Temperatur"), ("fcc", "Vollkapazität")),
            (("cycles", "Zyklen"), ("ms", "Laufzeit")),
        )
        for row, pair in enumerate(pairs):
            for column, (key, label) in ((0, pair[0]), (2, pair[1])):
                ttk.Label(frame, text=label + ":").grid(
                    row=row, column=column, sticky="w", pady=1,
                    padx=(0 if column == 0 else 20, 4))
                var = tk.StringVar(value="–")
                self.value_vars[key] = var
                ttk.Label(frame, textvariable=var, width=20, anchor="e").grid(
                    row=row, column=column + 1, sticky="e")

    def _build_status(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Status", padding=8)
        frame.pack(fill="x", pady=(8, 0))

        self.status_vars: dict[str, tk.StringVar] = {}
        # Alarme und Zustand können mehrere Flags enthalten und bekommen
        # deshalb eine eigene, volle Zeile.
        rows = (
            (0, ("st", "BatteryStatus"), ("mode", "BatteryMode")),
            (1, ("locks", "Gesperrt"), ("err", "Error-Code")),
            (2, ("alarms", "Alarme"), None),
            (3, ("state", "Zustand"), None),
            (4, ("asoc", "Abs. SoC"), ("maxerr", "MaxError")),
        )
        for row, left, right in rows:
            for column, entry in ((0, left), (2, right)):
                if entry is None:
                    continue
                key, label = entry
                # Steht rechts nichts, darf der Wert die ganze Zeile nutzen.
                wide = right is None
                ttk.Label(frame, text=label + ":").grid(
                    row=row, column=column, sticky="w", pady=1,
                    padx=(0 if column == 0 else 20, 4))
                var = tk.StringVar(value="–")
                self.status_vars[key] = var
                ttk.Label(frame, textvariable=var, anchor="w",
                          width=0 if wide else 20).grid(
                    row=row, column=column + 1, sticky="w",
                    columnspan=3 if wide else 1)

    def _build_commands(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Kommandos", padding=8)
        frame.pack(fill="x", pady=(8, 0))

        buttons = []
        for column, command in enumerate(("read", "id", "scan", "status")):
            button = ttk.Button(frame, text=command,
                                command=lambda cmd=command: self._send(cmd))
            button.grid(row=0, column=column, sticky="ew", padx=2, pady=2)
            buttons.append(button)

        self.live_btn = ttk.Button(frame, text="Live starten",
                                   command=self._toggle_live)
        self.live_btn.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2,
                           pady=2)

        reset_btn = ttk.Button(frame, text="reset …", command=self._reset)
        reset_btn.grid(row=1, column=2, columnspan=2, sticky="ew", padx=2,
                       pady=2)

        all_btn = ttk.Button(frame, text="Alle SBS-Werte …",
                             command=self._open_sbs_window)
        all_btn.grid(row=2, column=0, columnspan=4, sticky="ew", padx=2, pady=2)

        for column in range(4):
            frame.columnconfigure(column, weight=1)

        self.cmd_buttons.extend(buttons)
        self.cmd_buttons.extend([reset_btn, self.live_btn, all_btn])

    def _build_registers(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Register", padding=8)
        frame.pack(fill="x", pady=(8, 0))

        ttk.Label(frame, text="Register:").grid(row=0, column=0, sticky="w")
        self.reg_var = tk.StringVar(value="0x0d")
        ttk.Entry(frame, textvariable=self.reg_var, width=9).grid(
            row=0, column=1, padx=(2, 8))

        ttk.Label(frame, text="Wert:").grid(row=0, column=2, sticky="w")
        self.write_var = tk.StringVar(value="0x0000")
        ttk.Entry(frame, textvariable=self.write_var, width=9).grid(
            row=0, column=3, padx=2)

        read_btn = ttk.Button(frame, text="Lesen (raw)", command=self._read_register)
        read_btn.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2,
                      pady=(6, 2))
        write_btn = ttk.Button(frame, text="Schreiben (write) …",
                               command=self._write_register)
        write_btn.grid(row=1, column=2, columnspan=2, sticky="ew", padx=2,
                       pady=(6, 2))

        for column in range(4):
            frame.columnconfigure(column, weight=1)
        self.cmd_buttons.extend([read_btn, write_btn])

    def _build_free_text(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Freies Kommando", padding=8)
        frame.pack(fill="x", pady=(8, 0))

        self.free_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.free_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self._send_free())

        send_btn = ttk.Button(frame, text="Senden", command=self._send_free)
        send_btn.pack(side="left", padx=(4, 0))
        self.cmd_buttons.append(send_btn)

    def _build_log(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Protokoll", padding=4)
        frame.pack(fill="both", expand=True)

        self.log = tk.Text(frame, wrap="none", height=20, state="disabled",
                           font=("Consolas", 9), background="#101418",
                           foreground="#d8dee9", insertbackground="#d8dee9")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal",
                                command=self.log.xview)
        self.log.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        self.log.pack(side="left", fill="both", expand=True)

        self.log.tag_configure("cmd", foreground="#7fb7ff")
        self.log.tag_configure("err", foreground="#ff8080")
        self.log.tag_configure("ok", foreground="#8fd38f")
        self.log.tag_configure("info", foreground="#b0b0b0")

    # ---- Ports und Verbindung ---------------------------------------

    def _refresh_ports(self) -> None:
        ports = sorted(list(list_ports.comports()), key=lambda p: p.device)
        self._port_map = {self._port_label(p): p.device for p in ports}
        values = list(self._port_map)
        self.port_box["values"] = values
        if self.port_var.get() not in values:
            self.port_var.set(values[0] if values else "")

    @staticmethod
    def _port_label(port) -> str:
        """Beschreibung ohne doppeltes COM, z. B. 'COM4  (USB-SERIAL CH340)'."""
        description = port.description.strip()
        for suffix in (f" ({port.device})", port.device):
            if description.endswith(suffix):
                description = description[: -len(suffix)].strip()
        return f"{port.device}  ({description})" if description else port.device

    def _toggle_connection(self) -> None:
        if self.link.is_open:
            self._disconnect()
        else:
            self._connect()

    def _selected_device(self) -> str:
        selection = self.port_var.get()
        if selection in self._port_map:
            return self._port_map[selection]
        return selection.split()[0] if selection else ""

    def _connect(self) -> None:
        device = self._selected_device()
        if not device:
            messagebox.showwarning("Kein Port",
                                   "Keinen Port ausgewählt. D1 mini per USB "
                                   "anschließen und „Aktualisieren“ drücken.")
            return
        try:
            self.link.open(device)
        except Exception as exc:
            messagebox.showerror("Verbindung fehlgeschlagen",
                                 f"{device}: {exc}")
            return

        self._log(f"verbunden mit {device} (115200 Baud) – der D1 mini wurde "
                  f"durch das Öffnen zurückgesetzt", "ok")
        if self._live:
            self._live = False
            self.live_btn.configure(text="Live starten")
        # Nach dem Reset erst kurz warten, sonst geht das Kommando verloren.
        self._last_status_request = time.monotonic()
        self.after(1200, self._auto_id)
        self._refresh_connection_state()

    def _auto_id(self) -> None:
        if not self.link.is_open:
            return
        # Erst einen eventuell noch laufenden Dauerstrom stoppen, sonst gehen
        # id und status in den Messzeilen unter.
        self._send("stop")
        self._send("id")
        self.after(1500, self._request_status)

    def _disconnect(self) -> None:
        if self.link.is_open and self._live:
            try:
                self.link.send("stop")
            except Exception:
                pass
        self._live = False
        self.live_btn.configure(text="Live starten")
        self.link.close()
        self._log("getrennt", "info")
        self._refresh_connection_state()

    def _refresh_connection_state(self) -> None:
        open_ = self.link.is_open
        self.connect_btn.configure(text="Trennen" if open_ else "Verbinden")
        self.status_var.set(f"verbunden: {self.link.port_name}" if open_
                            else "getrennt")
        state = "normal" if open_ else "disabled"
        for button in self.cmd_buttons:
            button.configure(state=state)
        self.port_box.configure(state="disabled" if open_ else "readonly")
        self.refresh_btn.configure(state="disabled" if open_ else "normal")

    # ---- Kommandos ---------------------------------------------------

    def _send(self, command: str) -> None:
        if not self.link.is_open:
            self._log("nicht verbunden", "err")
            return
        try:
            self.link.send(command)
        except Exception as exc:
            self._log(f"Senden fehlgeschlagen: {exc}", "err")
            return
        self._log(f"> {command}", "cmd")

    def _send_free(self) -> None:
        command = self.free_var.get().strip()
        if command:
            self._send(command)
            self.free_var.set("")

    def _toggle_live(self) -> None:
        if self._live:
            self._send("stop")
            self._live = False
            self.live_btn.configure(text="Live starten")
        else:
            self._send("start 1000")
            self._live = True
            self.live_btn.configure(text="Live stoppen")

    def _reset(self) -> None:
        if not messagebox.askyesno(
                "Pack in den Off State zwingen",
                "Beide Leitungen 2,6 s auf low ziehen?\n\n"
                "Laut SBS 1.1 §4.4.3 ist das der Weg in den Off State – das "
                "Pack schläft danach. Es ist kein Aufweckbefehl."):
            return
        self._send("reset")

    def _read_register(self) -> None:
        reg = parse_int(self.reg_var.get())
        if reg is None or not 0x00 <= reg <= 0xFF:
            messagebox.showwarning("Register",
                                   "Register als 0x0d oder 13 eingeben "
                                   "(0x00–0xFF).")
            return
        self._send(f"raw 0x{reg:02X}")

    def _write_register(self) -> None:
        reg = parse_int(self.reg_var.get())
        value = parse_int(self.write_var.get())
        if reg is None or not 0x00 <= reg <= 0xFF:
            messagebox.showwarning("Register",
                                   "Register als 0x0d oder 13 eingeben "
                                   "(0x00–0xFF).")
            return
        if value is None or not 0x0000 <= value <= 0xFFFF:
            messagebox.showwarning("Wert",
                                   "Wert als 0x0001 oder 1 eingeben "
                                   "(0x0000–0xFFFF).")
            return
        self._write_value(reg, value)

    def _write_value(self, reg: int, value: int) -> bool:
        """Nach Rückfrage ``write`` schicken. True, wenn es rausging."""
        text = (f"Register 0x{reg:02X} mit 0x{value:04X} beschreiben?\n\n"
                "Schreibzugriffe verändern den Pack. Falsche Werte können ihn "
                "sperren oder abschalten. Nur schreiben, wenn Register und "
                "Wert belegt sind.")
        hinweis = WRITE_HINTS.get(reg)
        if hinweis:
            text += f"\n\n0x{reg:02X}: {hinweis}"
        if not messagebox.askyesno("Register schreiben", text):
            return False
        self._send(f"write 0x{reg:02X} 0x{value:04X}")
        return True

    # ---- Ausgabe -----------------------------------------------------

    def _poll_lines(self) -> None:
        try:
            while True:
                line = self.link.lines.get_nowait()
                if line:
                    self._handle_line(line)
        except queue.Empty:
            pass
        self._refresh_connection_state()
        self.after(100, self._poll_lines)

    def _handle_line(self, line: str) -> None:
        if line.startswith("#"):
            tag = "err" if ("kein ACK" in line or "fehlt" in line) else "info"
            self._log(line, tag)
        elif line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                self._log(line)
                return
            if data.get("ok") == 1:
                if data.get("dump"):
                    self._handle_dump(data)
                elif "st" in data:
                    self._handle_status(data)
                else:
                    self._update_values(data)
                    self._log(line)
                    self._maybe_request_status()
            else:
                self._log(line, "err")
        else:
            self._log(line)

    def _update_values(self, data: dict) -> None:
        unit = data.get("cap_unit", DEFAULT_CAP_UNIT)
        mv = data.get("v_mv")
        self.value_vars["v_mv"].set(
            f"{mv / 1000:.3f} V  ({mv} mV)" if mv is not None else "–")
        self.value_vars["i_ma"].set(f"{data.get('i_ma', 0)} mA")
        self.value_vars["t_c"].set(f"{data.get('t_c', 0.0):.1f} °C")
        self.value_vars["soc"].set(f"{data.get('soc', 0)} %")
        self.value_vars["rc"].set(f"{data.get('rc', 0)} {unit}")
        self.value_vars["fcc"].set(f"{data.get('fcc', 0)} {unit}")
        self.value_vars["cycles"].set(f"{data.get('cycles', 0)}")
        self.value_vars["ms"].set(f"{data.get('ms', 0) / 1000:.1f} s")

    def _handle_status(self, data: dict) -> None:
        status = data.get("st", 0)
        locks, alarms, flags = decode_status(status)
        code = data.get("err", 0)

        lock_text = " + ".join(locks) if locks else "keine"
        alarm_text = ", ".join(alarms) if alarms else "keine"
        state_text = ", ".join(flags) if flags else "keine"

        self.status_vars["st"].set(f"0x{status:04X} ({status})")
        self.status_vars["mode"].set(f"0x{data.get('mode', 0):04X}")
        self.status_vars["locks"].set(lock_text)
        self.status_vars["state"].set(state_text)
        self.status_vars["alarms"].set(alarm_text)
        self.status_vars["err"].set(f"{code} ({ERROR_CODES.get(code, '?')})")
        self.status_vars["asoc"].set(f"{data.get('asoc', 0)} %")
        self.status_vars["maxerr"].set(f"{data.get('maxerr', 0)} %")

        # Kurzfassung im Protokoll, damit die Rohzeile nicht alles zustellt.
        self._log(f"Status 0x{status:04X}: gesperrt {lock_text}, "
                  f"Alarme {alarm_text}, Zustand {state_text}, "
                  f"Error {ERROR_CODES.get(code, code)}, "
                  f"AbsSoC {data.get('asoc', 0)} %, "
                  f"MaxError {data.get('maxerr', 0)} %",
                  "err" if (locks or alarms) else "info")

    def _request_status(self) -> None:
        if self.link.is_open:
            self._last_status_request = time.monotonic()
            self._send("status")

    def _maybe_request_status(self) -> None:
        """Nach jeder Messung den Status nachziehen, aber höchstens alle 5 s."""
        if time.monotonic() - self._last_status_request < 5.0:
            return
        self._request_status()

    # ---- Alle SBS-Werte ----------------------------------------------

    def _open_sbs_window(self) -> None:
        if self.sbs_window is None or not self.sbs_window.winfo_exists():
            self.sbs_window = SbsWindow(self)
        else:
            self.sbs_window.lift()
        self.sbs_window.focus_set()
        self._request_dump()

    def _request_dump(self) -> None:
        if self.link.is_open:
            self._send("dump")

    def _handle_dump(self, data: dict) -> None:
        if self.sbs_window is not None and self.sbs_window.winfo_exists():
            self.sbs_window.update_dump(data)
        # Die Rohzeile ist zu lang fuer das Protokoll, deshalb nur die Quittung.
        self._log("SBS-Werte aktualisiert "
                  f"({len(SBS_REGISTERS)} Wortregister, {len(SBS_BLOCKS)} Blöcke)",
                  "ok")

    def _log(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        stamp = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{stamp}] {text}\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self.link.close()
        self.destroy()


class SbsWindow(tk.Toplevel):
    """Alle Funktionen aus SBS 1.1 §5.1 als Tabelle (Kommando ``dump``).

    Die Firmware liefert nur Rohwerte (-1 = nicht lesbar, "" = Block leer);
    die Einheiten und Sonderwerte werden hier ausgewertet.
    """

    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.app = app
        self.title("Alle SBS-Werte – SBS 1.1 §5.1")
        self.geometry("1180x660")
        self.minsize(760, 400)
        self.transient(app)
        # Letzter Dump – Vorbelegung für den Schreibdialog.
        self.last_dump: dict = {}

        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        table = ttk.Frame(outer)
        table.pack(fill="both", expand=True)

        columns = ("funktion", "zugriff", "reg", "roh", "wert")
        self.tree = ttk.Treeview(table, columns=columns, show="headings")
        for column, text, width, anchor in (
                ("funktion", "Funktion", 200, "w"),
                ("zugriff", "Zugriff", 70, "center"),
                ("reg", "Register", 80, "center"),
                ("roh", "Rohwert", 130, "e"),
                ("wert", "Wert", 620, "w")):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width, anchor=anchor,
                             stretch=column == "wert")
        yscroll = ttk.Scrollbar(table, orient="vertical",
                               command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal",
                                command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set,
                            xscrollcommand=xscroll.set)
        yscroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("missing", foreground="#a00000")
        self.tree.bind("<Double-1>", lambda _event: self._write_selected())

        # Zeilennummern einmal anlegen, damit beim Aktualisieren nur die
        # Werte getauscht werden (kein Flackern, keine Sprünge).
        self.rows: dict[str, str] = {}
        self.by_item: dict[str, str] = {}
        for reg, name, _kind, writable in SBS_REGISTERS:
            key = f"r{reg:02X}"
            self.rows[key] = self.tree.insert(
                "", "end",
                values=(name, "R/W" if writable else "R", f"0x{reg:02X}",
                        "–", "–"))
            self.by_item[self.rows[key]] = key
        for reg, name, _kind in SBS_BLOCKS:
            key = f"b{reg:02X}"
            self.rows[key] = self.tree.insert(
                "", "end",
                values=(name, "R", f"0x{reg:02X}", "Block", "–"))
            self.by_item[self.rows[key]] = key

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Aktualisieren",
                   command=self.app._request_dump).pack(side="left")
        self.write_btn = ttk.Button(bar, text="Schreiben …",
                                    command=self._write_selected)
        self.write_btn.pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Schließen",
                   command=self._close).pack(side="right")
        self.hint = tk.StringVar(
            value="Rohwerte aus dump · R/W = schreibbar, Doppelklick öffnet "
                  "den Schreibdialog · Einheiten nach SBS 1.1 §5.1")
        ttk.Label(bar, textvariable=self.hint).pack(side="left", padx=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        self.app.sbs_window = None
        self.destroy()

    def _write_selected(self) -> None:
        """Gewählte Zeile beschreiben – nur die fünf R/W-Register."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Schreiben",
                                "Erst eine Zeile in der Tabelle auswählen.")
            return
        key = self.by_item.get(selection[0], "")
        if not key.startswith("r"):
            messagebox.showinfo(
                "Schreiben",
                "Blockregister (0x20–0x23) sind laut SBS 1.1 nur lesbar.")
            return
        reg = int(key[1:], 16)
        entry = next((e for e in SBS_REGISTERS if e[0] == reg), None)
        if entry is None or not entry[3]:
            name = entry[1] if entry else ""
            messagebox.showinfo(
                "Schreiben",
                f"0x{reg:02X} {name} ist laut SBS 1.1 nur lesbar.")
            return

        alt = self.last_dump.get(key, -1)
        start = f"0x{alt:04X}" if alt >= 0 else "0x0000"
        text = simpledialog.askstring(
            "Wert schreiben",
            f"Neuer Wert für 0x{reg:02X} {entry[1]}\n"
            "0x0000–0xFFFF, als 0x012C oder 300:",
            initialvalue=start, parent=self)
        if text is None:
            return
        value = parse_int(text)
        if value is None or not 0x0000 <= value <= 0xFFFF:
            messagebox.showwarning("Wert",
                                   "Wert als 0x0001 oder 1 eingeben "
                                   "(0x0000–0xFFFF).",
                                   parent=self)
            return
        if self.app._write_value(reg, value):
            # Der Pack braucht einen Moment, bis der neue Wert im Dump steht.
            self.after(1200, self.app._request_dump)

    def update_dump(self, data: dict) -> None:
        self.last_dump = data
        mode = data.get("r03", 0)
        # CAPACITY_MODE (Bit 15) bestimmt, ob Kapazitäten in mAh oder 10 mWh
        # stehen (SBS 1.1 §5.1.4).
        unit = "10mWh" if mode >= 0 and mode >> 15 & 1 else DEFAULT_CAP_UNIT

        for reg, name, kind, writable in SBS_REGISTERS:
            key = f"r{reg:02X}"
            access = "R/W" if writable else "R"
            value = data.get(key, -1)
            if value is None or value < 0:
                self.tree.item(self.rows[key],
                               values=(name, access, f"0x{reg:02X}", "–",
                                       "nicht lesbar"),
                               tags=("missing",))
                continue
            self.tree.item(
                self.rows[key],
                values=(name, access, f"0x{reg:02X}", f"0x{value:04X} ({value})",
                        format_register(kind, value, unit)),
                tags=())

        for reg, name, kind in SBS_BLOCKS:
            key = f"b{reg:02X}"
            text = data.get(key, "")
            if not text:
                self.tree.item(self.rows[key],
                               values=(name, "R", f"0x{reg:02X}", "Block",
                                       "nicht lesbar oder leer"),
                               tags=("missing",))
                continue
            if kind == "hex":
                count = len(text.split())
                self.tree.item(self.rows[key],
                               values=(name, "R", f"0x{reg:02X}",
                                       f"Block, {count} Byte", text),
                               tags=())
            else:
                self.tree.item(self.rows[key],
                               values=(name, "R", f"0x{reg:02X}", "Block", text),
                               tags=())

        self.hint.set(f"Stand: {data.get('ms', 0) / 1000:.1f} s nach dem "
                      "Einschalten · R/W = schreibbar, Doppelklick schreibt")


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

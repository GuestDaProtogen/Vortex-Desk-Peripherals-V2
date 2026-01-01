# -*- coding: utf-8 -*-
"""
Vortex Desk Peripherals - Qt GUI + Qt System Tray (single file)
Python: 3.9+

Requires:
  pip install pyserial pillow unidecode requests psutil screeninfo numpy soundcard PySide6

Optional:
  pip install pycaw comtypes
  pip install pywin32
"""

import os
import sys
import time
import re
import threading
import asyncio
import multiprocessing as mp
import atexit
from datetime import datetime
from queue import Queue, Empty

# Force STA for comtypes everywhere
sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED

# ---- 3rd party
import requests
import serial
import serial.tools.list_ports
import psutil
from unidecode import unidecode
from PIL import ImageGrab, Image
from screeninfo import get_monitors

# Optional: numpy for VU worker
try:
    import numpy as np
    HAVE_NUMPY = True
except Exception:
    HAVE_NUMPY = False

# Optional: Windows APIs (foreground exe)
try:
    import win32gui
    PDH_OK = True
except Exception:
    PDH_OK = False

# Optional: WinRT media
try:
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
    MUSIC_OK = True
except Exception:
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as MediaManager
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
        MUSIC_OK = True
    except Exception:
        MUSIC_OK = False

LOG_PATH = "vortex_log.txt"
LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
LOG_BACKUP_COUNT = 3
_LOG_LOCK = threading.Lock()

# Qt scaling knobs
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR"] = "0.7"

UI_SCALE = 1
def S(x): return int(round(x * UI_SCALE))


def _now_ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def init_log_file(truncate=True):
    try:
        if truncate:
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.write(f"[{_now_ts()}] log start\n")
        else:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{_now_ts()}] log start (append)\n")
    except Exception:
        pass


def rotate_log_if_needed():
    try:
        if not os.path.exists(LOG_PATH):
            return
        if os.path.getsize(LOG_PATH) < LOG_MAX_BYTES:
            return

        for i in range(LOG_BACKUP_COUNT, 0, -1):
            src = f"{LOG_PATH}.{i}"
            dst = f"{LOG_PATH}.{i+1}"
            if os.path.exists(src):
                if i == LOG_BACKUP_COUNT:
                    try: os.remove(src)
                    except Exception: pass
                else:
                    try: os.replace(src, dst)
                    except Exception: pass

        try:
            os.replace(LOG_PATH, f"{LOG_PATH}.1")
        except Exception:
            pass

        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"[{_now_ts()}] log rotated\n")
    except Exception:
        pass


# ---------------- Logging ----------------
_LOG_QUEUE = Queue()

def _log(msg: str):
    s = f"[{_now_ts()}] {msg}"
    try:
        print(s, flush=True)
    except Exception:
        pass

    try:
        with _LOG_LOCK:
            rotate_log_if_needed()
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(s + "\n")
    except Exception:
        pass

    try:
        _LOG_QUEUE.put_nowait(s)
    except Exception:
        pass


def report_exception(tag: str):
    import traceback
    _log(f"{tag}: exception")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass


def _thread_exhook(args):
    report_exception(f"thread_ex: {getattr(args, 'thread', None)}")


import threading as _th
_th.excepthook = _thread_exhook

def _sys_exhook(exctype, value, tb):
    report_exception("sys_excepthook")
sys.excepthook = _sys_exhook

@atexit.register
def _on_atexit():
    _log("process exiting (atexit). see vortex_log.txt")


# ---------------- Serial ----------------
def find_serial_port():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        return None
    for p in ports:
        if any(k in (p.description or "").lower() for k in ['ch340', 'cp210', 'nodemcu', 'esp']):
            return p.device
    return ports[0].device


def clean_string(text):
    if not isinstance(text, str):
        text = str(text)
    text = text.replace('\x00', '').replace('\r', '').replace('\n', ' ')
    return ''.join(c for c in unidecode(text) if 32 <= ord(c) <= 126).strip()


class SerialLink:
    def __init__(self):
        self.ser = None
        self.lock = threading.Lock()
        self.last_tx = 0.0

    def connect(self):
        try:
            com_port = find_serial_port()
            if not com_port:
                _log("No serial port found")
                self.ser = None
                return False
            _log(f"Connecting to {com_port}")
            self.ser = serial.Serial(com_port, 115200, timeout=1)
            time.sleep(2)
            _log("Serial connection established")
            return True
        except Exception as e:
            _log(f"Serial connection failed: {e}")
            self.ser = None
            return False

    def is_open(self):
        return bool(self.ser and self.ser.is_open)

    def send_line(self, line: str) -> bool:
        if not self.is_open():
            return False

        s = clean_string(line)
        if not s.endswith("\n"):
            s += "\n"

        # High frequency data
        is_vu = s.startswith("V:") or s.startswith("CH:")

        with self.lock:
            try:
                self.ser.write(s.encode("ascii", errors="ignore"))
                if not is_vu:
                    self.ser.flush()
                    _log(f"TX: {s.strip()}")
                self.last_tx = time.time()
                return True
            except Exception as e:
                _log(f"Serial send error: {e}")
                return False

    def reset(self):
        if not self.is_open():
            _log("Serial not open, trying to reconnect...")
            return self.connect()
        try:
            _log("Resetting NodeMCU...")
            self.ser.dtr = False
            time.sleep(0.1)
            self.ser.dtr = True
            time.sleep(0.5)
            try:
                self.ser.close()
            except Exception:
                pass
            time.sleep(1)
            ok = self.connect()
            if ok:
                self.send_line("RESET")
            else:
                _log("Failed to reconnect after reset")
            return ok
        except Exception as e:
            _log(f"Failed to reset NodeMCU: {e}")
            return False

    def close(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None


# ---------------- LCD emulator (16x2 HD44780-ish) ----------------
_FONT5X7 = [
    0x00,0x00,0x00,0x00,0x00,  0x00,0x00,0x5F,0x00,0x00,  0x00,0x07,0x00,0x07,0x00,
    0x14,0x7F,0x14,0x7F,0x14,  0x24,0x2A,0x7F,0x2A,0x12,  0x23,0x13,0x08,0x64,0x62,
    0x36,0x49,0x55,0x22,0x50,  0x00,0x05,0x03,0x00,0x00,  0x00,0x1C,0x22,0x41,0x00,
    0x00,0x41,0x22,0x1C,0x00,  0x14,0x08,0x3E,0x08,0x14,  0x08,0x08,0x3E,0x08,0x08,
    0x00,0x50,0x30,0x00,0x00,  0x08,0x08,0x08,0x08,0x08,  0x00,0x60,0x60,0x00,0x00,
    0x20,0x10,0x08,0x04,0x02,  0x3E,0x51,0x49,0x45,0x3E,  0x00,0x42,0x7F,0x40,0x00,
    0x42,0x61,0x51,0x49,0x46,  0x21,0x41,0x45,0x4B,0x31,  0x18,0x14,0x12,0x7F,0x10,
    0x27,0x45,0x45,0x45,0x39,  0x3C,0x4A,0x49,0x49,0x30,  0x01,0x71,0x09,0x05,0x03,
    0x36,0x49,0x49,0x49,0x36,  0x06,0x49,0x49,0x29,0x1E,  0x00,0x36,0x36,0x00,0x00,
    0x00,0x56,0x36,0x00,0x00,  0x08,0x14,0x22,0x41,0x00,  0x14,0x14,0x14,0x14,0x14,
    0x00,0x41,0x22,0x14,0x08,  0x02,0x01,0x51,0x09,0x06,  0x32,0x49,0x79,0x41,0x3E,
    0x7E,0x11,0x11,0x11,0x7E,  0x7F,0x49,0x49,0x49,0x36,  0x3E,0x41,0x41,0x41,0x22,
    0x7F,0x41,0x41,0x22,0x1C,  0x7F,0x49,0x49,0x49,0x41,  0x7F,0x09,0x09,0x09,0x01,
    0x3E,0x41,0x49,0x49,0x7A,  0x7F,0x08,0x08,0x08,0x7F,  0x00,0x41,0x7F,0x41,0x00,
    0x20,0x40,0x41,0x3F,0x01,  0x7F,0x08,0x14,0x22,0x41,  0x7F,0x40,0x40,0x40,0x40,
    0x7F,0x02,0x0C,0x02,0x7F,  0x7F,0x04,0x08,0x10,0x7F,  0x3E,0x41,0x41,0x41,0x3E,
    0x7F,0x09,0x09,0x09,0x06,  0x3E,0x41,0x51,0x21,0x5E,  0x7F,0x09,0x19,0x29,0x46,
    0x46,0x49,0x49,0x49,0x31,  0x01,0x01,0x7F,0x01,0x01,  0x3F,0x40,0x40,0x40,0x3F,
    0x1F,0x20,0x40,0x20,0x1F,  0x7F,0x20,0x18,0x20,0x7F,  0x63,0x14,0x08,0x14,0x63,
    0x03,0x04,0x78,0x04,0x03,  0x61,0x51,0x49,0x45,0x43,  0x00,0x7F,0x41,0x41,0x00,
    0x02,0x04,0x08,0x10,0x20,  0x00,0x41,0x41,0x7F,0x00,  0x04,0x02,0x01,0x02,0x04,
    0x40,0x40,0x40,0x40,0x40,  0x00,0x01,0x02,0x04,0x00,  0x20,0x54,0x54,0x54,0x78,
    0x7F,0x48,0x44,0x44,0x38,  0x38,0x44,0x44,0x44,0x20,  0x38,0x44,0x44,0x48,0x7F,
    0x38,0x54,0x54,0x54,0x18,  0x08,0x7E,0x09,0x01,0x02,  0x0C,0x52,0x52,0x52,0x3E,
    0x7F,0x08,0x04,0x04,0x78,  0x00,0x44,0x7D,0x40,0x00,  0x20,0x40,0x44,0x3D,0x00,
    0x7F,0x10,0x28,0x44,0x00,  0x00,0x41,0x7F,0x40,0x00,  0x7C,0x04,0x18,0x04,0x78,
    0x7C,0x08,0x04,0x04,0x78,  0x38,0x44,0x44,0x44,0x38,  0x7C,0x14,0x14,0x14,0x08,
    0x08,0x14,0x14,0x18,0x7C,  0x7C,0x08,0x04,0x04,0x08,  0x48,0x54,0x54,0x54,0x20,
    0x04,0x3F,0x44,0x40,0x20,  0x3C,0x40,0x40,0x20,0x7C,  0x1C,0x20,0x40,0x20,0x1C,
    0x3C,0x40,0x30,0x40,0x3C,  0x44,0x28,0x10,0x28,0x44,  0x0C,0x50,0x50,0x50,0x3C,
    0x44,0x64,0x54,0x4C,0x44,  0x00,0x08,0x36,0x41,0x00,  0x00,0x00,0x7F,0x00,0x00,
    0x00,0x41,0x36,0x08,0x00,  0x08,0x04,0x08,0x10,0x08,  0x00,0x00,0x00,0x00,0x00,
]

def _glyph_cols_for_ascii(ch: int):
    if ch < 0x20 or ch > 0x7F:
        ch = 0x20
    i = (ch - 0x20) * 5
    return _FONT5X7[i:i+5]

def _cgram_to_cols(byte_rows_8):
    cols = [0]*5
    for y in range(8):
        row = int(byte_rows_8[y]) & 0x1F
        for x in range(5):
            if row & (1 << (4-x)):
                cols[x] |= (1 << y)
    return cols

_VISIT_BAR_CHARS = [
    [0,0,0,0,0,0,0,0],
    [0,0,0,0,0,0,0,31],
    [0,0,0,0,0,0,31,31],
    [0,0,0,0,0,31,31,31],
    [0,0,0,0,31,31,31,31],
    [0,0,0,31,31,31,31,31],
    [0,0,31,31,31,31,31,31],
    [0,31,31,31,31,31,31,31],
]
_MUSIC_ICONS = {
    0: [0b00000,0b00111,0b01101,0b01001,0b01011,0b11011,0b11000,0b00000],
    1: [0b00000,0b01000,0b01100,0b01110,0b01110,0b01100,0b01000,0b00000],
    2: [0b00000,0b00001,0b00101,0b10101,0b10101,0b10101,0b00000,0b00000],
    3: [0b00000,0b00010,0b00110,0b11110,0b11110,0b00110,0b00010,0b00000],
}
_SYSTEM_ICONS = {
    0: [0b00000,0b01010,0b11111,0b01110,0b11111,0b01010,0b00000,0b00000],
    1: [0b00000,0b11111,0b11111,0b11111,0b00100,0b01110,0b00000,0b00000],
    2: [0b00000,0b00000,0b11111,0b11111,0b11111,0b10101,0b00000,0b00000],
}

def pad16(s: str) -> str:
    s = s or ""
    if len(s) > 16:
        s = s[:16]
    return s + (" " * (16 - len(s)))

class LcdState:
    def __init__(self):
        self.mode = "VISIT"
        self.ddram = [[0x20]*16, [0x20]*16]
        self.cgram = {i: _VISIT_BAR_CHARS[i][:] for i in range(8)}
        self.visit_anim_active = False
        self.box_step = 0
        self.last_anim = 0.0
        self.anim_interval = 0.9
        self.scroll_top = ""
        self.scroll_bottom = ""
        self.scroll_i_top = 0
        self.scroll_i_bottom = 0
        self.last_scroll = 0.0
        self.scroll_interval = 0.75
        self.volume_overlay = False
        self._vol_until = 0.0
        self.last_visit_astro = 0
        self.last_visit_core = 0

    def set_mode_by_num(self, m: int):
        if m == 1: self.enter_visit()
        elif m == 3: self.enter_music()
        elif m == 4: self.enter_clock()
        elif m == 5: self.enter_text()
        elif m == 7: self.enter_system()
        elif m == 8: self.enter_screen()

    def clear(self):
        self.ddram = [[0x20]*16, [0x20]*16]

    def enter_visit(self):
        self.mode = "VISIT"
        self.clear()
        self.cgram = {i: _VISIT_BAR_CHARS[i][:] for i in range(8)}
        self.visit_anim_active = False
        self.box_step = 0
        self.draw_visit_header_counts(0, 0)

    def draw_visit_header_counts(self, astro: int, core: int):
        self.last_visit_astro = int(astro)
        self.last_visit_core = int(core)
        top = pad16("Live Visit Count")
        bottom15 = f"ARI:{astro} CC:{core}"
        if len(bottom15) > 15:
            bottom15 = bottom15[:15]
        bottom15 = bottom15 + (" " * (15 - len(bottom15)))
        self.write_line(0, top)
        for i, ch in enumerate(bottom15):
            self.ddram[1][i] = ord(ch)
        self.ddram[1][15] = self.box_step

    def enter_music(self):
        self.mode = "MUSIC"
        self.clear()
        for i in range(8):
            self.cgram[i] = [0]*8
        for k, v in _MUSIC_ICONS.items():
            self.cgram[k] = v[:]
        self.write_icon_prefix_line(0, 0, "Music Mode")
        self.write_icon_prefix_line(1, 1, "Loading...")

    def enter_clock(self):
        self.mode = "CLOCK"
        self.clear()
        self.write_line(0, pad16("Clock Mode"))
        self.write_line(1, pad16("Loading..."))

    def enter_text(self):
        self.mode = "TEXT"
        self.clear()
        self.write_line(0, pad16("Text Mode"))
        self.write_line(1, pad16("Loading..."))

    def enter_system(self):
        self.mode = "SYSTEM"
        self.clear()
        for i in range(8):
            self.cgram[i] = [0]*8
        for k, v in _SYSTEM_ICONS.items():
            self.cgram[k] = v[:]
        self.write_icon_prefix_line(0, 0, "System Mode")
        self.write_icon_prefix_line(1, 2, "Loading...")

    def enter_screen(self):
        self.mode = "SCREEN"
        self.clear()
        self.write_line(0, pad16("Screen Mirror"))
        self.write_line(1, pad16("Running"))

    def write_line(self, row: int, text16: str):
        text16 = pad16(text16)
        for i, ch in enumerate(text16[:16]):
            self.ddram[row][i] = ord(ch)

    def write_icon_prefix_line(self, row: int, icon_index: int, text: str):
        t = (text or "")
        if len(t) > 14:
            t = t[:14]
        t = t + (" " * (14 - len(t)))
        self.ddram[row][0] = int(icon_index) & 0xFF
        self.ddram[row][1] = ord(" ")
        for i in range(14):
            self.ddram[row][i+2] = ord(t[i])

    def scroll_text_line_icon(self, row: int, text: str, idx_attr: str, icon_index: int):
        avail = 14
        text = text or ""
        idx = getattr(self, idx_attr)
        if len(text) <= avail:
            self.write_icon_prefix_line(row, icon_index, text)
            setattr(self, idx_attr, 0)
            return
        buf = text + "    "
        pos = idx % len(buf)
        seg = "".join(buf[(pos+i) % len(buf)] for i in range(avail))
        self.write_icon_prefix_line(row, icon_index, seg)
        setattr(self, idx_attr, idx + 1)

    def handle_cmd(self, cmd: str):
        cmd = cmd.strip()
        if cmd.startswith("MODE:"):
            try:
                self.set_mode_by_num(int(cmd[5:]))
            except Exception:
                pass
            return

        if cmd.startswith("LIVE:"):
            try:
                comma = cmd.find(",")
                astro = int(cmd[5:comma])
                core = int(cmd[comma+1:])
                if self.mode == "VISIT":
                    self.draw_visit_header_counts(astro, core)
                    self.box_step = 0
                    self.visit_anim_active = True
                    self.last_anim = time.time()
                    self.ddram[1][15] = self.box_step
            except Exception:
                pass
            return

        if cmd.startswith("CLOCK:"):
            try:
                body = cmd[6:]
                if "|" in body:
                    top, bottom = body.split("|", 1)
                else:
                    top, bottom = body, ""
                top = pad16(clean_string(top))
                bottom = pad16(clean_string(bottom))
                if self.mode == "CLOCK":
                    self.write_line(0, top)
                    self.write_line(1, bottom)
            except Exception:
                pass
            return

        if cmd.startswith("MUSIC:"):
            try:
                body = cmd[6:]
                if "|" in body:
                    top, bottom = body.split("|", 1)
                else:
                    top, bottom = body, ""
                top = clean_string(top) or "Unknown Title"
                bottom = clean_string(bottom) or "Unknown Artist"
                self.scroll_top = top
                self.scroll_bottom = bottom
                self.scroll_i_top = 0
                self.scroll_i_bottom = 0
                self.last_scroll = time.time()
                if self.mode == "MUSIC" and not self.volume_overlay:
                    self.write_icon_prefix_line(0, 0, self.scroll_top[:15])
                    self.write_icon_prefix_line(1, 1, self.scroll_bottom[:15])
            except Exception:
                pass
            return

        if cmd.startswith("TEXT:"):
            try:
                txt = clean_string(cmd[5:])
                if self.mode == "TEXT":
                    top = pad16(txt[:16])
                    bottom = pad16(txt[16:32]) if len(txt) > 16 else pad16("")
                    self.write_line(0, top)
                    self.write_line(1, bottom)
            except Exception:
                pass
            return

        if cmd.startswith("VOL:"):
            try:
                body = cmd[4:]
                if "|" in body:
                    pct_s, dev = body.split("|", 1)
                else:
                    pct_s, dev = body.strip(), ""

                pct_s = clean_string(pct_s)
                dev = clean_string(dev)

                for i in range(8):
                    self.cgram[i] = [0]*8
                for k, v in _MUSIC_ICONS.items():
                    self.cgram[k] = v[:]

                self.volume_overlay = True
                self._vol_until = time.time() + 1.5

                line0 = f"Volume: {pct_s}"
                line1 = dev or ""
                self.write_icon_prefix_line(0, 2, line0)
                self.write_icon_prefix_line(1, 3, line1)
            except Exception:
                pass
            return

    def tick(self):
        now = time.time()

        if self.volume_overlay and self._vol_until and now >= self._vol_until:
            self.volume_overlay = False

            if self.mode == "VISIT":
                self.cgram = {i: _VISIT_BAR_CHARS[i][:] for i in range(8)}
                self.draw_visit_header_counts(self.last_visit_astro, self.last_visit_core)
                self.ddram[1][15] = self.box_step

            elif self.mode == "MUSIC":
                for i in range(8):
                    self.cgram[i] = [0]*8
                for k, v in _MUSIC_ICONS.items():
                    self.cgram[k] = v[:]
                self.write_icon_prefix_line(0, 0, self.scroll_top[:14])
                self.write_icon_prefix_line(1, 1, self.scroll_bottom[:14])
                self.last_scroll = now

            elif self.mode == "SYSTEM":
                for i in range(8):
                    self.cgram[i] = [0]*8
                for k, v in _SYSTEM_ICONS.items():
                    self.cgram[k] = v[:]

        if self.mode == "VISIT" and self.visit_anim_active:
            if (now - self.last_anim) >= self.anim_interval:
                self.ddram[1][15] = self.box_step
                if self.box_step < 7:
                    self.box_step += 1
                    self.last_anim = now
                else:
                    self.visit_anim_active = False

        if self.mode == "MUSIC" and not self.volume_overlay:
            if (now - self.last_scroll) >= self.scroll_interval:
                self.scroll_text_line_icon(0, self.scroll_top, "scroll_i_top", 0)
                self.scroll_text_line_icon(1, self.scroll_bottom, "scroll_i_bottom", 1)
                self.last_scroll = now


# ---------------- Dot matrix state (32x8) ----------------
class MatrixState:
    def __init__(self):
        self.mode = "NONE"
        self.pixels = [[0]*32 for _ in range(8)]
        self.vu_levels = [0]*32
        self._last_decay = time.time()

    def clear(self):
        self.pixels = [[0]*32 for _ in range(8)]

    def _render_vu_pixels(self):
        self.clear()
        for x in range(32):
            h = self.vu_levels[x]
            for y in range(8):
                self.pixels[7-y][x] = 1 if y < h else 0

    def apply_vu(self, levels_0_8):
        self.mode = "VU"
        self.vu_levels = [max(0, min(8, int(v))) for v in levels_0_8[:32]] + [0]*(32-len(levels_0_8[:32]))
        self._render_vu_pixels()
        self._last_decay = time.time()

    def apply_fb_payload(self, hex_payload):
        if len(hex_payload) < 8*8:
            return
        self.mode = "FB"
        self.clear()
        try:
            rows = [int(hex_payload[i*8:(i+1)*8], 16) for i in range(8)]
            for y in range(8):
                row = rows[y]
                for x in range(32):
                    bit = (row >> (31-x)) & 1
                    self.pixels[y][x] = 1 if bit else 0
        except Exception:
            pass

    def tick_decay(self, enabled: bool, step_ms: int = 90):
        if self.mode != "VU":
            return
        now = time.time()
        if enabled:
            self._last_decay = now
            return
        if (now - self._last_decay) * 1000.0 < step_ms:
            return
        self._last_decay = now
        changed = False
        for i in range(32):
            if self.vu_levels[i] > 0:
                self.vu_levels[i] -= 1
                changed = True
        if changed:
            self._render_vu_pixels()


# ---------------- Native worker processes ----------------
def _volume_worker(out_q, stop_ev):
    """Runs in a child process. Sends tuples: ('VOL', pct:int, devname:str)."""
    pythoncom = None
    try:
        try:
            import pythoncom as _pc
            pythoncom = _pc
            pythoncom.CoInitializeEx(2)  # STA
        except Exception:
            return

        try:
            import re as _re
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        except Exception:
            return

        EDF_RENDER, EROLE_MULTIMEDIA = 0, 1

        def friendly_name(dev):
            try:
                did = dev.GetId()
                for m in AudioUtilities.GetAllDevices():
                    mid = getattr(m, "id", None) or (m.GetId() if hasattr(m, "GetId") else None)
                    if mid and did and mid == did:
                        nm = getattr(m, "FriendlyName", None) or "Default"
                        return _re.sub(r"\s*\([^)]*\)\s*$", "", nm).strip() or "Default"
            except Exception:
                pass
            return "Default"

        def get_default():
            enum = AudioUtilities.GetDeviceEnumerator()
            dev = enum.GetDefaultAudioEndpoint(EDF_RENDER, EROLE_MULTIMEDIA)
            vol = cast(
                dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                POINTER(IAudioEndpointVolume),
            )
            return enum, dev, vol, dev.GetId()

        enum, dev, vol, dev_id = get_default()
        name = friendly_name(dev)
        last_pct = None
        last_check = time.time()

        POLL_DT = 0.20

        while not stop_ev.is_set():
            now = time.time()

            if now - last_check >= 1.5:
                last_check = now
                try:
                    _, _, _, id2 = get_default()
                    if id2 != dev_id:
                        enum, dev, vol, dev_id = get_default()
                        name = friendly_name(dev)
                        last_pct = None
                except Exception:
                    try:
                        enum, dev, vol, dev_id = get_default()
                        name = friendly_name(dev)
                        last_pct = None
                    except Exception:
                        time.sleep(POLL_DT)
                        continue

            try:
                scalar = float(vol.GetMasterVolumeLevelScalar())
                pct = int(round(scalar * 100.0))
                if pct != last_pct:
                    try:
                        out_q.put_nowait(("VOL", pct, name))
                    except Exception:
                        pass
                    last_pct = pct
            except Exception:
                try:
                    enum, dev, vol, dev_id = get_default()
                    name = friendly_name(dev)
                    last_pct = None
                except Exception:
                    pass

            time.sleep(POLL_DT)

    finally:
        try:
            if pythoncom is not None:
                pythoncom.CoUninitialize()
        except Exception:
            pass


def _vu_worker(out_q, stop_ev, enabled_ev, channel_enabled_ev, audio_mode_ev, rebind_ev):
    """
    Runs in a child process.
    Sends tuples: ('V', levels32_str) or ('CH', list_of_int_levels).
    """
    pythoncom = None
    try:
        try:
            import pythoncom as _pc
            pythoncom = _pc
            # Try to initialize COM for the main worker process
            pythoncom.CoInitializeEx(0) 
        except Exception:
            pass

        try:
            import numpy as np
            import soundcard as sc
        except Exception:
            return

        def q_put_latest(q, item):
            try: q.put_nowait(item); return
            except: pass
            try:
                while True: q.get_nowait()
            except: pass
            try: q.put_nowait(item)
            except: pass

        fps, frame_dt, blocksize, hop = 30.0, 1/30.0, 1024, 1024
        window = np.hanning(blocksize).astype(np.float32)

        def _hz_to_mel(f): return 2595.0 * np.log10(1.0 + f / 700.0)
        def _mel_to_hz(m): return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

        def build_bins(sr, n_bands=32):
            freqs = np.fft.rfftfreq(blocksize, 1.0 / sr)
            fmin, fmax = 40.0, min(20000.0, sr / 2.0)
            m_edges = np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_bands + 1)
            edges = _mel_to_hz(m_edges)
            bins, centers = [], []
            for i in range(n_bands):
                idx = np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0]
                if idx.size == 0:
                    mid = _mel_to_hz((m_edges[i] + m_edges[i + 1]) * 0.5)
                    idx = np.array([int(np.argmin(np.abs(freqs - mid)))], dtype=int)
                bins.append(idx)
                centers.append(_mel_to_hz((m_edges[i] + m_edges[i + 1]) * 0.5))
            return bins, np.array(centers, dtype=np.float32)

        import re as _re
        def pick_sc_loopback_once():
            try:
                spk = sc.default_speaker()
                if not spk: return None
                def guid_tail(dev_id: str) -> str:
                    if not dev_id: return ""
                    m = _re.search(r"\}\.\{([0-9a-fA-F\-]+)\}", dev_id)
                    return m.group(1).lower() if m else dev_id.lower()
                spk_guid = guid_tail(getattr(spk, "id", "") or "")
                candidates = sc.all_microphones(include_loopback=True)
                loopbacks = [m for m in candidates if getattr(m, "isloopback", False)]
                exact = [m for m in loopbacks if guid_tail(getattr(m, "id", "") or "") == spk_guid]
                name_match = [m for m in loopbacks if spk.name.lower() in (m.name or "").lower()]
                pick = (exact or name_match or loopbacks)
                return pick[0] if pick else None
            except Exception:
                return None

        # --- Mic Capture (Threaded) ---
        mic_state = {"peak": 0.0}
        
        def mic_thread_entry():
            if pythoncom:
                try: pythoncom.CoInitializeEx(0)
                except: pass

            while not stop_ev.is_set():
                if not audio_mode_ev.is_set():
                    time.sleep(0.5)
                    continue
                try:
                    # FIX: Use sc.default_microphone() to follow Windows Default
                    mic = sc.default_microphone()
                    
                    if mic:
                        print(f"[Mic Thread] Listening to: {mic.name}", flush=True)
                        with mic.recorder(samplerate=48000, blocksize=1024) as rec:
                             # FIX: Check rebind_ev here so the mic thread also restarts
                             while audio_mode_ev.is_set() and not stop_ev.is_set() and not rebind_ev.is_set():
                                 d = rec.record(numframes=1024)
                                 # Calculate peak for the bar
                                 p = float(np.max(np.abs(d)))
                                 mic_state["peak"] = p
                    else:
                        time.sleep(1.0)
                except Exception as e:
                    print(f"[Mic Thread] Error: {e}", flush=True)
                    time.sleep(1.0)
                
                # If we exited because of a rebind, wait a moment for things to settle
                if rebind_ev.is_set():
                    time.sleep(0.2)
        
        mic_thr = threading.Thread(target=mic_thread_entry, daemon=True)
        mic_thr.start()
        # -----------------------------

        HIGH_TILT_DB_PER_OCT, alpha_up, alpha_dn = 3.0, 0.35, 0.15
        smooth = np.zeros(32, dtype=np.float32)
        agc_level, noise_floor, zero_hold_until, last_send = 1e-4, 0.0, 0.0, 0.0
        agc_p90, agc_p10, frame_i = 1e-4, 0.0, 0
        last_ch_send = 0.0

        def process_block(x_multi, bin_idx, tilt_gain):
            nonlocal smooth, agc_level, noise_floor, zero_hold_until, last_send, agc_p90, agc_p10, frame_i, last_ch_send
            x_multi = np.nan_to_num(x_multi, nan=0.0, posinf=0.0, neginf=0.0)
            
            if x_multi.ndim == 2:
                x = x_multi.mean(axis=1).astype(np.float32, copy=False)
            else:
                x = x_multi.astype(np.float32, copy=False)

            x = x - np.mean(x)
            if window is not None and len(x) == len(window):
                x = x * window

            X = np.fft.rfft(x, n=blocksize)
            mag = np.abs(X).astype(np.float32)

            bands = np.zeros(32, dtype=np.float32)
            for i, idx in enumerate(bin_idx):
                bands[i] = float(np.sum(mag[idx])) * float(tilt_gain[i])

            frame_i += 1
            if frame_i % 6 == 0:
                agc_p90 = float(np.percentile(bands, 90))
                agc_p10 = float(np.percentile(bands, 10))

            agc_level = 0.90 * agc_level + 0.10 * max(agc_p90, 1e-8)
            noise_floor = 0.95 * noise_floor + 0.05 * max(agc_p10, 0.0)

            now = time.time()
            if agc_level < 5e-7:
                zero_hold_until = now + 0.2

            if enabled_ev.is_set() and now >= zero_hold_until:
                b = np.maximum(bands - noise_floor, 0.0) / (agc_level + 1e-9)
                b = np.log1p(6.0 * b) / np.log1p(6.0)

                up = b > smooth
                smooth[up] = smooth[up] * (1.0 - alpha_up) + b[up] * alpha_up
                smooth[~up] = smooth[~up] * (1.0 - alpha_dn) + b[~up] * alpha_dn

                if now - last_send >= frame_dt:
                    levels = np.clip(np.rint(smooth * 8.0), 0, 8).astype(int).tolist()
                    s = "".join(str(int(v)) for v in levels[:32])
                    q_put_latest(out_q, ("V", s))
                    last_send = now
            elif enabled_ev.is_set() and now < zero_hold_until and now - last_send >= frame_dt:
                 q_put_latest(out_q, ("V", "0"*32))
                 last_send = now

            if (channel_enabled_ev.is_set() or audio_mode_ev.is_set()) and now - last_ch_send >= 0.05: 
                ch_peaks = np.max(np.abs(x_multi), axis=0)
                num_ch = len(ch_peaks)
                
                if audio_mode_ev.is_set():
                     l_val = ch_peaks[0] if num_ch >= 1 else 0.0
                     r_val = ch_peaks[1] if num_ch >= 2 else l_val
                     mic_val = mic_state["peak"] 

                     l_int = int(min(1.0, l_val * 1) * 100)
                     r_int = int(min(1.0, r_val * 1) * 100)
                     
                     # Boosted mic sensitivity for visibility
                     m_int = int(min(1.0, mic_val * 1.5) * 100) 

                     q_put_latest(out_q, ("CH", [l_int, r_int, m_int]))

                elif channel_enabled_ev.is_set():
                    out_levels = [0]*6
                    if num_ch >= 1: out_levels[0] = ch_peaks[0]
                    if num_ch >= 2: out_levels[1] = ch_peaks[1]
                    if num_ch >= 6:
                        out_levels[2], out_levels[3], out_levels[4], out_levels[5] = ch_peaks[2], ch_peaks[4], ch_peaks[5], ch_peaks[3]
                    elif num_ch >= 4:
                        out_levels[3], out_levels[4] = ch_peaks[2], ch_peaks[3]
                    
                    out_ints = [int(min(1.0, v * 1.5) * 100) for v in out_levels]
                    q_put_latest(out_q, ("CH", out_ints))
                
                last_ch_send = now


        while not stop_ev.is_set():
            if not enabled_ev.is_set() and not channel_enabled_ev.is_set() and not audio_mode_ev.is_set():
                time.sleep(0.2)
                continue

            loopmic = pick_sc_loopback_once()
            if not loopmic:
                time.sleep(0.5)
                continue

            sr = 48000
            try: sr = int(getattr(loopmic, "default_samplerate", sr) or sr)
            except: pass
            
            ch_count = 2
            try: ch_count = loopmic.channels
            except: ch_count = 2

            bin_idx, centers = build_bins(sr)
            fref = 1000.0
            tilt_gain = np.power(np.maximum(centers, 1.0) / fref, HIGH_TILT_DB_PER_OCT / 6.0).astype(np.float32)

            # --- Main Loopback Recording Loop ---
            try:
                with loopmic.recorder(samplerate=sr, channels=ch_count, blocksize=hop) as rec:
                    while (not stop_ev.is_set()):
                        if rebind_ev.is_set():
                            # This breaks the 'with' block, triggering a search for the speaker and mic again
                            print("[VU Worker] Rebind triggered: Refreshing devices...", flush=True)
                            # Wait briefly so the GUI has time to clear the flag or just clear it here
                            time.sleep(0.5)
                            rebind_ev.clear() 
                            break
                            
                        if not enabled_ev.is_set() and not channel_enabled_ev.is_set() and not audio_mode_ev.is_set():
                            time.sleep(0.1)
                            continue
                            
                        x = rec.record(numframes=hop)
                        process_block(x, bin_idx, tilt_gain)
            except Exception:
                time.sleep(0.2)

    finally:
        try:
            if pythoncom is not None:
                pythoncom.CoUninitialize()
        except Exception:
            pass


# ---------------- Backend ----------------
KNOWN_GAME_EXES = {
    "robloxplayerbeta.exe","robloxstudio.exe","robloxstudiobeta.exe",
    "hl2.exe","blender.exe",
    "cs2.exe","valorant-win64-shipping.exe","fortniteclient-win64-shipping.exe",
    "eldenring.exe","leagueclient.exe","dota2.exe","gta5.exe","rdr2.exe",
    "minecraft.exe","apex.exe"
}
GAME_DEBOUNCE_SEC = 2.0

class Backend:
    def __init__(self):
        self.running = True
        self.serial = SerialLink()
        self.serial.connect()

        self.VOLUME_ENABLED = True
        self.mode = "VISIT"
        self.AUTO_ENABLED = False
        self.MUSIC_PLAYING = False

        self.VU_ENABLED = False
        self.CHANNEL_ENABLED = False
        self.LOGO_ENABLED = False
        self.AUDIO_MODE_ENABLED = False # New flag

        self.lcd = LcdState()
        self.matrix = MatrixState()

        self.astro_api = "https://games.roblox.com/v1/games?universeIds=2176212732"
        self.core_api  = "https://games.roblox.com/v1/games?universeIds=6109192776"

        self._ui_callbacks = {"on_state": []}

        # --- Native worker isolation ---
        self._mp = mp.get_context('spawn')
        self._native_stop = self._mp.Event()

        self._vol_out = self._mp.Queue(maxsize=32)
        self._vol_proc = None

        self._vu_out = self._mp.Queue(maxsize=8)
        self._vu_enabled = self._mp.Event()
        self._vu_channel_enabled = self._mp.Event()
        self._vu_audio_mode_enabled = self._mp.Event() # New event
        self._vu_rebind = self._mp.Event()
        self._vu_proc = None

        self._native_consumer_thr = None
        self._native_lock = threading.Lock()

    def on(self, event_name, cb):
        self._ui_callbacks[event_name].append(cb)

    def _emit(self, event_name):
        for cb in list(self._ui_callbacks.get(event_name, [])):
            try:
                cb()
            except Exception:
                pass

    def start_native_workers(self):
        with self._native_lock:
            if self._native_consumer_thr is None:
                self._native_consumer_thr = threading.Thread(target=self._native_consumer_loop, daemon=True)
                self._native_consumer_thr.start()
            if self.VOLUME_ENABLED and (self._vol_proc is None or not self._vol_proc.is_alive()):
                self._start_volume_proc()
            if (self._vu_proc is None or not self._vu_proc.is_alive()):
                self._start_vu_proc()

    def _start_volume_proc(self):
        try:
            if self._vol_proc is not None and self._vol_proc.is_alive():
                return
            self._vol_proc = self._mp.Process(target=_volume_worker, args=(self._vol_out, self._native_stop), daemon=True)
            self._vol_proc.start()
            _log("Volume process started.")
        except Exception as e:
            _log(f"Volume process start failed: {e}")
            self.VOLUME_ENABLED = False

    def _start_vu_proc(self):
        try:
            if self._vu_proc is not None and self._vu_proc.is_alive():
                return
            self._vu_proc = self._mp.Process(
                target=_vu_worker,
                args=(self._vu_out, self._native_stop, self._vu_enabled, self._vu_channel_enabled, self._vu_audio_mode_enabled, self._vu_rebind),
                daemon=True
            )
            self._vu_proc.start()
            _log("VU process started.")
        except Exception as e:
            _log(f"VU process start failed: {e}")
            self.VU_ENABLED = False
            self._vu_enabled.clear()
            self._vu_channel_enabled.clear()
            self._vu_audio_mode_enabled.clear()

    def _native_consumer_loop(self):
        last_vu_send = 0.0
        VU_SEND_DT = 1.0 / 40.0  # 40 fps

        while self.running and not self._native_stop.is_set():
            try:
                # Volume
                try:
                    kind, pct, name = self._vol_out.get(timeout=0.01)
                    if kind == "VOL" and self.VOLUME_ENABLED:
                        self.send_to_device(f"VOL:{int(pct)}|{str(name)}")
                except Exception:
                    pass

                # VU / Channel drain
                latest_vu = None
                latest_ch = None
                
                # Drain the queue to get latest values
                while True:
                    try:
                        data = self._vu_out.get_nowait()
                        if data[0] == "V":
                            latest_vu = data[1]
                        elif data[0] == "CH":
                            latest_ch = data[1]
                    except Exception:
                        break

                now = time.time()
                
                # Send VU
                if self.VU_ENABLED and latest_vu is not None and (now - last_vu_send) >= VU_SEND_DT:
                    self.send_to_device("V:" + str(latest_vu))
                    last_vu_send = now
                
                # Send Channel Levels (Both Audio Mode and Channel Mode use this)
                if (self.CHANNEL_ENABLED or self.AUDIO_MODE_ENABLED) and latest_ch is not None:
                     # format: CH:50,75,100
                     s_vals = ",".join(str(v) for v in latest_ch)
                     self.send_to_device(f"CH:{s_vals}")

                # auto-restart dead workers
                with self._native_lock:
                    if self.VOLUME_ENABLED and self._vol_proc is not None and (not self._vol_proc.is_alive()):
                        _log("Volume process died; restarting.")
                        self._start_volume_proc()
                    if self._vu_proc is not None and (not self._vu_proc.is_alive()):
                        _log("VU process died; restarting.")
                        self._start_vu_proc()

                time.sleep(0.001)
            except BaseException:
                report_exception("native_consumer")

    def stop_native_workers(self):
        with self._native_lock:
            try:
                self._native_stop.set()
            except Exception:
                pass
            for p in (self._vol_proc, self._vu_proc):
                try:
                    if p is not None and p.is_alive():
                        p.terminate()
                except Exception:
                    pass
            for p in (self._vol_proc, self._vu_proc):
                try:
                    if p is not None:
                        p.join(timeout=1.5)
                except Exception:
                    pass
            self._vol_proc = None
            self._vu_proc = None

    def stop(self):
        self.running = False
        try:
            self.stop_native_workers()
        except Exception:
            pass
        try:
            self.serial.send_line("GOODBYE")
            time.sleep(0.25)
        except Exception:
            pass
        self.serial.close()

    def send_to_device(self, line: str):
        ok = self.serial.send_line(line)
        try:
            self.lcd.handle_cmd(line)
            if line.startswith("V:"):
                levels = [int(c) for c in line[2:].strip() if c.isdigit()]
                self.matrix.apply_vu(levels)
            elif line.startswith("FB:"):
                self.matrix.apply_fb_payload(line[3:].strip())
            self._emit("on_state")
        except Exception:
            pass
        return ok

    def send_mode(self, mode_num: int):
        return self.send_to_device(f"MODE:{mode_num}")

    def set_mode(self, name: str):
        old = self.mode
        self.mode = name
        if name == "VISIT":
            self.send_mode(1)
        elif name == "MUSIC":
            self.send_mode(3)
        elif name == "CLOCK":
            self.send_mode(4)
        elif name == "TEXT":
            self.send_mode(5)
        elif name == "SYSTEM":
            self.send_mode(7)
        elif name == "SCREEN":
            self.send_to_device("VUMODE:OFF")
            self.send_mode(8)
        if old != name:
            _log(f"Mode -> {name}")

    def toggle_auto(self):
        self.AUTO_ENABLED = not self.AUTO_ENABLED
        _log(f"AUTO_ENABLED={self.AUTO_ENABLED}")

    def toggle_vu(self):
        self.VU_ENABLED = not self.VU_ENABLED
        self.send_to_device("VUMODE:ON" if self.VU_ENABLED else "VUMODE:OFF")
        if self.VU_ENABLED:
            self._vu_enabled.set()
            self._vu_rebind.set()
        else:
            self._vu_enabled.clear()
        _log(f"VU_ENABLED={self.VU_ENABLED}")
        
    def toggle_channel_mode(self):
        self.CHANNEL_ENABLED = not self.CHANNEL_ENABLED
        if self.CHANNEL_ENABLED:
            self.LOGO_ENABLED = False # Mutually exclusive
            self.AUDIO_MODE_ENABLED = False # Mutually exclusive
            self._vu_audio_mode_enabled.clear()
            self.send_to_device("CHANNEL:ON")
            self._vu_channel_enabled.set()
            self._vu_rebind.set() 
        else:
            self.send_to_device("CHANNEL:OFF")
            self._vu_channel_enabled.clear()
        _log(f"CHANNEL_ENABLED={self.CHANNEL_ENABLED}")

    def toggle_audio_mode(self):
        self.AUDIO_MODE_ENABLED = not self.AUDIO_MODE_ENABLED
        if self.AUDIO_MODE_ENABLED:
            self.LOGO_ENABLED = False # Mutually exclusive
            self.CHANNEL_ENABLED = False # Mutually exclusive
            self._vu_channel_enabled.clear()
            self.send_to_device("AUDIO:ON")
            self._vu_audio_mode_enabled.set()
            self._vu_rebind.set()
        else:
            self.send_to_device("AUDIO:OFF")
            self._vu_audio_mode_enabled.clear()
        _log(f"AUDIO_MODE_ENABLED={self.AUDIO_MODE_ENABLED}")

    def toggle_logo_mode(self):
        self.LOGO_ENABLED = not self.LOGO_ENABLED
        if self.LOGO_ENABLED:
            self.CHANNEL_ENABLED = False 
            self.AUDIO_MODE_ENABLED = False
            self._vu_channel_enabled.clear()
            self._vu_audio_mode_enabled.clear()
            self.send_to_device("LOGO:ON")
        else:
            self.send_to_device("LOGO:OFF")
        _log(f"LOGO_ENABLED={self.LOGO_ENABLED}")

    def rebind_vu(self):
        self._vu_rebind.set()
        _log("VU_REBIND requested")

    def toggle_backlight(self):
        self.send_to_device("BACKLIGHT:TOGGLE")

    def reset_controller(self):
        self.serial.reset()

    def send_custom_text(self, text: str):
        self.set_mode("TEXT")
        self.send_to_device(f"TEXT:{text}")

    # ----- BACKEND LOOPS -----
    def loop_visit(self):
        try:
            last_mode_sent = None
            error_count = 0
            while self.running:
                if self.mode == "VISIT":
                    try:
                        if last_mode_sent != "VISIT":
                            if self.send_mode(1):
                                last_mode_sent, error_count = "VISIT", 0
                            else:
                                error_count += 1
                        if error_count < 5:
                            a = requests.get(self.astro_api, timeout=5)
                            c = requests.get(self.core_api, timeout=5)
                            if a.status_code == 200 and c.status_code == 200:
                                astro = max(0, int(a.json()['data'][0]['playing']))
                                core  = max(0, int(c.json()['data'][0]['playing']))
                                self.send_to_device(f"LIVE:{astro},{core}")
                                error_count = 0
                            else:
                                self.send_to_device("LIVE:0,0")
                    except Exception as e:
                        _log(f"Visit fetch error: {e}")
                        error_count += 1
                        if error_count < 5:
                            self.send_to_device("LIVE:-1,-1")
                    time.sleep(5)
                else:
                    last_mode_sent, error_count = None, 0
                    time.sleep(0.2)
        except BaseException:
            report_exception("loop_visit")

    def loop_clock(self):
        try:
            last_mode_sent = None
            while self.running:
                if self.mode == "CLOCK":
                    if last_mode_sent != "CLOCK":
                        self.send_mode(4)
                        last_mode_sent = "CLOCK"
                    now = datetime.now()
                    time_str = clean_string(now.strftime("%I:%M:%S %p"))
                    date_str = clean_string(now.strftime("%m/%d/%Y"))
                    self.send_to_device(f"CLOCK:{time_str}|{date_str}")
                    time.sleep(1.0)
                else:
                    last_mode_sent = None
                    time.sleep(0.2)
        except BaseException:
            report_exception("loop_clock")

    def loop_music(self):
        try:
            if not MUSIC_OK:
                _log("Music loop disabled: WinRT media API not available.")
                while self.running:
                    time.sleep(0.5)
                return

            async def get_current_media_async():
                try:
                    sessions = await MediaManager.request_async()
                    s = sessions.get_current_session()
                    if not s:
                        return None, None, False
                    playing = s.get_playback_info().playback_status == PlaybackStatus.PLAYING
                    props = await s.try_get_media_properties_async()
                    if not props:
                        return None, None, False
                    return props.title or "", props.artist or "", playing
                except Exception as e:
                    _log(f"Media API error: {e}")
                    return None, None, False

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            last_mode_sent = None
            last_music_local = ""
            while self.running:
                if self.mode == "MUSIC" or self.AUTO_ENABLED:
                    if last_mode_sent != "MUSIC" and self.mode == "MUSIC":
                        self.send_mode(3)
                        last_mode_sent = "MUSIC"

                    title, artist, playing = loop.run_until_complete(get_current_media_async())
                    self.MUSIC_PLAYING = bool(playing)

                    if not title or not artist or not playing:
                        msg = "No media|Player off"
                    else:
                        def cln(s): return ''.join(c for c in unidecode(s) if 32 <= ord(c) <= 126).strip()
                        msg = f"{cln(title)}|{cln(artist)}"

                    if msg != last_music_local and self.mode == "MUSIC":
                        self.send_to_device(f"MUSIC:{msg}")
                        last_music_local = msg

                    time.sleep(2)
                else:
                    last_mode_sent = None
                    last_music_local = ""
                    time.sleep(0.2)
        except BaseException:
            report_exception("loop_music")

    def loop_system(self):
        try:
            last_mode_sent = None
            while self.running:
                if self.mode == "SYSTEM":
                    if last_mode_sent != "SYSTEM":
                        self.send_mode(7)
                        last_mode_sent = "SYSTEM"
                    cpu_pct = int(round(psutil.cpu_percent(interval=None)))
                    try:
                        f = psutil.cpu_freq()
                        ghz = (f.current or f.max or 0) / 1000.0
                    except Exception:
                        ghz = 0.0
                    ram_pct = int(round(psutil.virtual_memory().percent))
                    gpu_pct = 0
                    self.send_to_device(f"SYS:{cpu_pct},{ghz:.2f}|{gpu_pct},{ram_pct}")
                    time.sleep(1.0)
                else:
                    last_mode_sent = None
                    time.sleep(0.2)
        except BaseException:
            report_exception("loop_system")

    def loop_auto(self):
        try:
            seen_game_since = 0.0
            while self.running:
                if not self.AUTO_ENABLED:
                    time.sleep(0.5)
                    continue
                desired = "MUSIC" if self.MUSIC_PLAYING else ("SYSTEM" if self._is_known_game_running() else "VISIT")
                if desired == "SYSTEM":
                    if seen_game_since == 0.0:
                        seen_game_since = time.time()
                    if time.time() - seen_game_since < GAME_DEBOUNCE_SEC:
                        desired = self.mode
                else:
                    seen_game_since = 0.0
                if desired != self.mode:
                    self.set_mode(desired)
                time.sleep(0.5)
        except BaseException:
            report_exception("loop_auto")

    def _is_known_game_running(self) -> bool:
        try:
            if not PDH_OK:
                return False
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd) or ""
            if "roblox" in title.lower():
                return True
            for p in psutil.process_iter(['name']):
                n = (p.info.get('name') or '').lower()
                if n in KNOWN_GAME_EXES:
                    return True
        except Exception:
            pass
        return False

    def loop_screen(self):
        try:
            last_mode_sent = None
            FPS = 15.0
            frame_interval = 1.0 / FPS
            last = 0.0

            while self.running:
                if self.mode != "SCREEN":
                    last_mode_sent = None
                    last = 0.0
                    time.sleep(0.2)
                    continue

                if last_mode_sent != "SCREEN":
                    self.send_mode(8)
                    self.send_to_device("VUMODE:OFF")
                    last_mode_sent = "SCREEN"

                now = time.time()
                if last != 0.0 and now - last < frame_interval:
                    time.sleep(0.005)
                    continue
                last = now

                try:
                    monitors = get_monitors()
                except Exception as e:
                    _log(f"get_monitors failed: {e}")
                    monitors = []

                if not monitors:
                    img_full = ImageGrab.grab().resize((32, 8), Image.BILINEAR)
                    img_combined = img_full
                elif len(monitors) == 1:
                    m0 = monitors[0]
                    bbox0 = (m0.x, m0.y, m0.x + m0.width, m0.y + m0.height)
                    img0 = ImageGrab.grab(bbox=bbox0).resize((32, 8), Image.BILINEAR)
                    img_combined = img0
                else:
                    m0, m1 = monitors[0], monitors[1]
                    bbox0 = (m0.x, m0.y, m0.x + m0.width, m0.y + m0.height)
                    bbox1 = (m1.x, m1.y, m1.x + m1.width, m1.y + m1.height)
                    img0 = ImageGrab.grab(bbox=bbox0).resize((16, 8), Image.BILINEAR)
                    img1 = ImageGrab.grab(bbox=bbox1).resize((16, 8), Image.BILINEAR)
                    img_combined = Image.new("RGB", (32, 8))
                    img_combined.paste(img0, (0, 0))
                    img_combined.paste(img1, (16, 0))

                gray = img_combined.convert("L")
                bw = gray.point(lambda p: 255 if p > 128 else 0, mode="1")

                rows32 = []
                for y in range(8):
                    row_val = 0
                    for x in range(32):
                        on = bw.getpixel((x, y)) != 0
                        row_val = (row_val << 1) | (1 if on else 0)
                    rows32.append(row_val)

                payload = "".join(f"{row:08X}" for row in rows32)
                self.send_to_device("FB:" + payload)

        except BaseException:
            report_exception("loop_screen")

    def loop_lcd_tick(self):
        try:
            while self.running:
                self.lcd.tick()
                self.matrix.tick_decay(enabled=self.VU_ENABLED)
                self._emit("on_state")
                time.sleep(0.05)
        except BaseException:
            report_exception("loop_lcd_tick")


# ---------------- GUI (PySide6) ----------------
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

AUDIOWIDE_FAMILY = None

def _load_font_if_exists(ttf_path: str):
    global AUDIOWIDE_FAMILY
    if ttf_path and os.path.exists(ttf_path):
        try:
            fid = QtGui.QFontDatabase.addApplicationFont(ttf_path)
            if fid != -1:
                fams = QtGui.QFontDatabase.applicationFontFamilies(fid)
                if fams:
                    if "Audiowide" in (ttf_path or ""):
                        AUDIOWIDE_FAMILY = fams[0]
        except Exception:
            pass


class TitleBar(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(S(42))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self._drag_pos = None
        self.root = parent

        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)

        self.title = QtWidgets.QLabel("VORTEX")
        f = QtGui.QFont(AUDIOWIDE_FAMILY or "Audiowide")
        if f.family() != "Audiowide":
            f = self.title.font()
        f.setPixelSize(S(18))
        self.title.setFont(f)
        self.title.setStyleSheet("color: white;")

        h.addWidget(self.title)
        h.addStretch(1)

        self.btn_tray = QtWidgets.QToolButton()
        self.btn_tray.setText("▾")
        self.btn_min = QtWidgets.QToolButton()
        self.btn_min.setText("—")
        self.btn_close = QtWidgets.QToolButton()
        self.btn_close.setText("✕")

        for b in (self.btn_tray, self.btn_min, self.btn_close):
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setStyleSheet("""
                QToolButton {
                    color: white;
                    background: transparent;
                    border: none;
                    padding: 2px 10px;
                    font-size: 16px;
                }
                QToolButton:hover { background: rgba(255,255,255,0.08); border-radius: 6px; }
            """)

        self.btn_tray.clicked.connect(self.root.hide_to_tray)
        self.btn_min.clicked.connect(self.root.showMinimized)
        self.btn_close.clicked.connect(self.root.full_close)

        h.addWidget(self.btn_tray)
        h.addWidget(self.btn_min)
        h.addWidget(self.btn_close)

        self.setStyleSheet("QWidget { background: rgba(0,0,0,0.0); }")

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.root.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos and (e.buttons() & QtCore.Qt.LeftButton):
            self.root.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


class MenuButton(QtWidgets.QPushButton):
    def __init__(self, text: str, active_indicator: bool):
        super().__init__(text)
        self.active_indicator = active_indicator
        self.active = False
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedHeight(S(46))
        self.setCheckable(False)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self._apply()

    def set_active(self, on: bool):
        self.active = bool(on)
        self._apply()

    def _apply(self):
        left_bar = "6px" if (self.active and self.active_indicator) else "0px"
        self.setStyleSheet(f"""
            QPushButton {{
                color: white;
                text-align: left;
                padding-left: 18px;
                font-size: 16px;
                border: none;
                background: transparent;
                border-left: {left_bar} solid #1f8fe5;
            }}
            QPushButton:hover {{
                background: rgba(255,255,255,0.05);
            }}
        """)


class LeftMenu(QtWidgets.QWidget):
    def __init__(self, root, assets_dir: str):
        super().__init__()
        self.root = root
        self.assets_dir = assets_dir
        self.setFixedWidth(S(270))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(22, 16, 22, 14)
        v.setSpacing(10)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)

        self.logo = QtWidgets.QLabel()
        self.logo.setFixedSize(54, 54)
        self.logo.setScaledContents(True)

        logo_path = os.path.join(self.assets_dir, "vortexlogo.png")
        if os.path.exists(logo_path):
            self.logo.setPixmap(QtGui.QPixmap(logo_path))
        else:
            self.logo.setPixmap(QtGui.QPixmap())

        brand_col = QtWidgets.QVBoxLayout()
        brand_col.setSpacing(2)
        self.brand = QtWidgets.QLabel("VORTEX")
        self.sub = QtWidgets.QLabel("Desk Peripherals")
        self.brand.setStyleSheet("color: white;")
        self.sub.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 18px;")

        f = QtGui.QFont(AUDIOWIDE_FAMILY or "Audiowide")
        if f.family() != "Audiowide":
            f = self.brand.font()
        f.setPixelSize(S(30))
        self.brand.setFont(f)

        brand_col.addWidget(self.brand)
        brand_col.addWidget(self.sub)

        top.addWidget(self.logo, 0, QtCore.Qt.AlignTop)
        top.addLayout(brand_col)
        top.addStretch(1)

        v.addLayout(top)
        v.addSpacing(6)

        def sep():
            line = QtWidgets.QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet("background: rgba(255,255,255,0.18);")
            return line

        self.btn_auto  = MenuButton("Auto Mode", True)
        self.btn_visit = MenuButton("Visit Mode", True)
        self.btn_music = MenuButton("Music Mode", True)
        self.btn_clock = MenuButton("Clock Mode", True)
        self.btn_text  = MenuButton("Text Mode", True)
        self.btn_system= MenuButton("System Mode", True)
        self.btn_screen= MenuButton("Screen Mode", True)

        self.btn_vu    = MenuButton("VU Meter", True)
        
        # New buttons added here
        self.btn_audio   = MenuButton("Audio Mode", True)
        self.btn_channel = MenuButton("Channel Mode", True)
        self.btn_logo    = MenuButton("Logo Mode", True)

        self.btn_rebind   = MenuButton("Rebind VU Source", False)
        self.btn_backlight= MenuButton("Toggle Backlight", False)
        self.btn_reset    = MenuButton("Reset Controller", False)
        self.btn_quit     = MenuButton("Quit", False)

        v.addWidget(self.btn_auto)
        v.addWidget(sep())
        for b in [self.btn_visit, self.btn_music, self.btn_clock, self.btn_text, self.btn_system, self.btn_screen]:
            v.addWidget(b)

        v.addWidget(sep())
        v.addWidget(self.btn_vu)
        v.addWidget(self.btn_audio)
        v.addWidget(self.btn_channel)
        v.addWidget(self.btn_logo)
        
        v.addWidget(sep())
        for b in [self.btn_rebind, self.btn_backlight, self.btn_reset]:
            v.addWidget(b)

        v.addStretch(1)
        v.addWidget(self.btn_quit)

        self.setStyleSheet("QWidget { background: rgba(0,0,0,0); }")

    def set_active_mode(self, mode_name: str, vu_on: bool, ch_on: bool, logo_on: bool, audio_on: bool, auto_on: bool):
        self.btn_auto.set_active(auto_on)
        self.btn_visit.set_active(mode_name == "VISIT")
        self.btn_music.set_active(mode_name == "MUSIC")
        self.btn_clock.set_active(mode_name == "CLOCK")
        self.btn_text.set_active(mode_name == "TEXT")
        self.btn_system.set_active(mode_name == "SYSTEM")
        self.btn_screen.set_active(mode_name == "SCREEN")
        self.btn_vu.set_active(vu_on)
        self.btn_channel.set_active(ch_on)
        self.btn_audio.set_active(audio_on)
        self.btn_logo.set_active(logo_on)


class LcdWidget(QtWidgets.QWidget):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.setFixedSize(S(450), S(129))

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        outer = QtCore.QRectF(0.5, 0.5, self.width()-1, self.height()-1)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0))
        p.drawRoundedRect(outer, 18, 18)

        border = 10
        inner = outer.adjusted(border, border, -border, -border)
        p.setBrush(QtGui.QColor(49, 132, 234))
        p.drawRoundedRect(inner, 14, 14)

        px = 4
        char_gap = 0 * px
        gap_col = 1 * px
        gap_row = 2 * px

        total_w = 16*(5*px) + 15*(char_gap + gap_col)
        total_h = 2*(8*px) + 1*(gap_row)

        x0 = int(inner.left()) + int((inner.width() - total_w) * 0.5)
        y0 = int(inner.top())  + int((inner.height() - total_h) * 0.5)

        on = QtGui.QColor(220, 245, 255)
        off = QtGui.QColor(49, 132, 234)

        for row in range(2):
            for col in range(16):
                ch = self.backend.lcd.ddram[row][col]
                if 0 <= ch <= 7:
                    cols = _cgram_to_cols(self.backend.lcd.cgram.get(ch, [0]*8))
                else:
                    cols = _glyph_cols_for_ascii(ch)

                base_x = x0 + col * (5*px + char_gap + gap_col)
                base_y = y0 + row * (8*px + gap_row)

                for gx in range(5):
                    col_bits = cols[gx] if gx < len(cols) else 0
                    for gy in range(8):
                        bit = (col_bits >> gy) & 1
                        p.fillRect(QtCore.QRectF(base_x + gx*px, base_y + gy*px, px, px), on if bit else off)
        p.end()


class MatrixWidget(QtWidgets.QWidget):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.setFixedSize(S(440), S(132))

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        p.fillRect(self.rect(), QtGui.QColor(0,0,0,0))

        led_on = QtGui.QColor(255, 60, 60)
        led_off = QtGui.QColor(102, 102, 102, 180)

        pad = 10
        cols, rows = 32, 8
        area_w = self.width() - pad*2
        area_h = self.height() - pad*2

        step_x = area_w / cols
        step_y = area_h / rows
        r = min(step_x, step_y) * 0.48

        for y in range(rows):
            for x in range(cols):
                cx = pad + (x + 0.5) * step_x
                cy = pad + (y + 0.5) * step_y
                onpx = bool(self.backend.matrix.pixels[y][x])
                p.setBrush(led_on if onpx else led_off)
                p.setPen(QtCore.Qt.NoPen)
                p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
        p.end()


class LogView(QtWidgets.QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setStyleSheet("""
            QPlainTextEdit {
                background: rgba(0,0,0,0.65);
                border: none;
                color: #1f8fe5;
                font-family: Consolas;
                font-size: 13px;
                padding: 10px;
            }
        """)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

    def append_line(self, line: str):
        self.appendPlainText(line)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())


class MainWindow(QtWidgets.QWidget):
    @QtCore.Slot()
    def _qt_show_from_tray(self):
        self.show_from_tray()

    @QtCore.Slot()
    def _qt_full_close(self):
        self.full_close()

    @QtCore.Slot()
    def _qt_hide_to_tray(self):
        self.hide_to_tray()

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.assets_dir = os.path.abspath(os.path.dirname(__file__))

        self.setWindowTitle("Vortex Desk Peripherals")
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(S(1280), S(720))

        # ---- Fonts FIRST ----
        _load_font_if_exists(os.path.join(self.assets_dir, "Font", "Audiowide-Regular.ttf"))
        _load_font_if_exists(os.path.join(self.assets_dir, "NotoSans-Regular.ttf"))

        self.qtray = None
        self._build_qt_tray()

        self.card = QtWidgets.QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            QFrame#card {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(18,22,32,245),
                    stop:1 rgba(8,10,14,245)
                );
                border-radius: 22px;
            }
        """)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(self.card)

        v = QtWidgets.QVBoxLayout(self.card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.titlebar = TitleBar(self)
        v.addWidget(self.titlebar)

        content = QtWidgets.QHBoxLayout()
        content.setContentsMargins(18, 10, 18, 18)
        content.setSpacing(18)
        v.addLayout(content)

        self.left = LeftMenu(self, self.assets_dir)
        content.addWidget(self.left)

        center = QtWidgets.QVBoxLayout()
        center.setSpacing(14)
        content.addLayout(center, 1)

        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(18)
        center.addLayout(top_row)

        self.lcd_widget = LcdWidget(self.backend)
        top_row.addWidget(self.lcd_widget)

        div = QtWidgets.QFrame()
        div.setFixedWidth(2)
        div.setStyleSheet("background: rgba(255,255,255,0.75);")
        top_row.addWidget(div)

        self.matrix_widget = MatrixWidget(self.backend)
        top_row.addWidget(self.matrix_widget)
        top_row.addStretch(1)

        self.log = LogView()
        center.addWidget(self.log, 1)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(10)
        center.addLayout(bottom)

        self.serial_input = QtWidgets.QLineEdit()
        self.serial_input.setPlaceholderText("Type here to send Serial Command")
        self.serial_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255,255,255,0.12);
                border: none;
                border-radius: 10px;
                padding: 12px 14px;
                color: white;
                font-size: 14px;
            }
        """)
        bottom.addWidget(self.serial_input, 1)

        self.btn_send = QtWidgets.QToolButton()
        self.btn_send.setText("➜")
        self.btn_send.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_send.setFixedSize(S(46), S(46))
        self.btn_send.setStyleSheet("""
            QToolButton {
                background: rgba(255,255,255,0.12);
                border: none;
                border-radius: 10px;
                color: white;
                font-size: 20px;
            }
            QToolButton:hover { background: rgba(255,255,255,0.18); }
        """)
        bottom.addWidget(self.btn_send)

        self.left.btn_auto.clicked.connect(self._on_auto_clicked)
        self.left.btn_visit.clicked.connect(lambda: self.backend.set_mode("VISIT"))
        self.left.btn_music.clicked.connect(lambda: self.backend.set_mode("MUSIC"))
        self.left.btn_clock.clicked.connect(lambda: self.backend.set_mode("CLOCK"))
        self.left.btn_system.clicked.connect(lambda: self.backend.set_mode("SYSTEM"))
        self.left.btn_screen.clicked.connect(lambda: self.backend.set_mode("SCREEN"))
        self.left.btn_vu.clicked.connect(self._on_vu_clicked)
        self.left.btn_text.clicked.connect(self._on_text_clicked)

        self.left.btn_channel.clicked.connect(self._on_channel_clicked)
        self.left.btn_audio.clicked.connect(self._on_audio_clicked)
        self.left.btn_logo.clicked.connect(self._on_logo_clicked)

        self.left.btn_rebind.clicked.connect(lambda: self.backend.rebind_vu())
        self.left.btn_backlight.clicked.connect(lambda: self.backend.toggle_backlight())
        self.left.btn_reset.clicked.connect(lambda: self.backend.reset_controller())
        self.left.btn_quit.clicked.connect(self.full_close)

        self.btn_send.clicked.connect(self._send_serial_text)
        self.serial_input.returnPressed.connect(self._send_serial_text)

        self.backend.on("on_state", self._refresh_previews)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._ui_tick)
        self.timer.start(50)

        self._refresh_left_indicator()

    # -------- TRAY (FIX: Qt-native tray, always present if Windows tray exists) --------
    def _build_qt_tray(self):
        try:
            if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
                _log("System tray not available.")
                self.qtray = None
                return

            icon_path = os.path.join(self.assets_dir, "Icon.ico")
            icon = QtGui.QIcon(icon_path) if os.path.exists(icon_path) else self.style().standardIcon(
                QtWidgets.QStyle.SP_ComputerIcon
            )

            self.qtray = QtWidgets.QSystemTrayIcon(icon, self)
            self.qtray.setToolTip("Vortex Desk Peripherals")

            menu = QtWidgets.QMenu()

            act_show = menu.addAction("Show")
            act_hide = menu.addAction("Hide to tray")
            menu.addSeparator()
            act_quit = menu.addAction("Quit")

            act_show.triggered.connect(self._qt_show_from_tray)
            act_hide.triggered.connect(self._qt_hide_to_tray)
            act_quit.triggered.connect(self._qt_full_close)

            self.qtray.setContextMenu(menu)

            def on_activated(reason):
                if reason in (QtWidgets.QSystemTrayIcon.Trigger, QtWidgets.QSystemTrayIcon.DoubleClick):
                    self.show_from_tray()

            self.qtray.activated.connect(on_activated)
            self.qtray.show()
            _log("Qt tray created and shown.")
        except Exception:
            report_exception("_build_qt_tray failed")
            self.qtray = None

    def _on_text_clicked(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "Custom Text", "Enter text to display on LCD:")
        if ok and text.strip():
            self.backend.send_custom_text(text.strip())
            self._refresh_left_indicator()

    def _on_auto_clicked(self):
        self.backend.toggle_auto()
        self._refresh_left_indicator()

    def _on_vu_clicked(self):
        self.backend.toggle_vu()
        self._refresh_left_indicator()

    def _on_channel_clicked(self):
        self.backend.toggle_channel_mode()
        self._refresh_left_indicator()

    def _on_audio_clicked(self):
        self.backend.toggle_audio_mode()
        self._refresh_left_indicator()

    def _on_logo_clicked(self):
        self.backend.toggle_logo_mode()
        self._refresh_left_indicator()

    def _send_serial_text(self):
        s = (self.serial_input.text() or "").strip()
        if not s:
            return
        self.backend.send_to_device(s)
        self.serial_input.clear()

    def _ui_tick(self):
        try:
            while True:
                line = _LOG_QUEUE.get_nowait()
                self.log.append_line(line)
        except Empty:
            pass

        self._refresh_left_indicator()
        self.lcd_widget.update()
        self.matrix_widget.update()

    def _refresh_previews(self):
        pass

    def _refresh_left_indicator(self):
        self.left.set_active_mode(
            self.backend.mode, 
            self.backend.VU_ENABLED, 
            self.backend.CHANNEL_ENABLED, 
            self.backend.LOGO_ENABLED,
            self.backend.AUDIO_MODE_ENABLED,
            self.backend.AUTO_ENABLED
        )

    # FIX: do not hide if tray failed to initialize
    def hide_to_tray(self):
        if getattr(self, "qtray", None) is None:
            _log("Tray missing; refusing to hide.")
            return
        self.hide()

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def full_close(self):
        try:
            if getattr(self, "qtray", None):
                self.qtray.hide()
        except Exception:
            pass
        self.backend.stop()
        QtWidgets.QApplication.quit()

    def closeEvent(self, e):
        e.ignore()
        self.hide_to_tray()


# ---------------- Bootstrap threads ----------------
def runner(backend, fn):
    def _w():
        while backend.running:
            try:
                fn()
            except BaseException:
                report_exception(f"{fn.__name__}")
            time.sleep(0.25)
    return _w


def main():
    mp.freeze_support()
    init_log_file(truncate=True)

    backend = Backend()
    backend.start_native_workers()

    threads = [
        threading.Thread(target=runner(backend, backend.loop_visit), daemon=True),
        threading.Thread(target=runner(backend, backend.loop_clock), daemon=True),
        threading.Thread(target=runner(backend, backend.loop_music), daemon=True),
        threading.Thread(target=runner(backend, backend.loop_system), daemon=True),
        threading.Thread(target=runner(backend, backend.loop_auto), daemon=True),
        threading.Thread(target=runner(backend, backend.loop_screen), daemon=True),
        threading.Thread(target=runner(backend, backend.loop_lcd_tick), daemon=True),
    ]
    for t in threads:
        t.start()

    app = QtWidgets.QApplication(sys.argv)

    # FIX: tray apps should not quit when main window is closed/hidden
    app.setQuitOnLastWindowClosed(False)

    base_font = QtGui.QFont("Noto Sans")
    if base_font.family() == "Noto Sans":
        base_font.setPointSize(10)
        app.setFont(base_font)

    w = MainWindow(backend)
    w.show()
    _log("GUI started.")
    try:
        return app.exec()
    finally:
        try:
            backend.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
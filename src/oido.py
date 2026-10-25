#!/usr/bin/env python3
"""
Oído — audio quality and mix/master analyzer, with an educational player and A/B comparison.

Instalar:  pip install -U PySide6 numpy        (requiere FFmpeg en el PATH)
Run:      python oido.py [files…]
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QIODevice, QObject, QPointF, QProcess, QRectF, QRunnable, QSettings, QSize, Qt,
                            QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QCursor, QDesktopServices, QFont, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget,
    QVBoxLayout, QWidget,
)

import app_runtime as RT  # noqa: I001  (primero: agrega FFmpeg incluido al PATH)
import i18n
import oido_engine as E
import locales
from i18n import tr
from oido_engine import BAD, GOOD, INFO, OK, WARN
from ui_icons import icon

__version__ = "1.0.0"
REPO_URL = "https://github.com/stgermanrobert/oido"

APP = "Oído"
IPC_NAME = "oido-ipc-v2"

# ──────────────────────────────────────────────────────────────────────────────
#  Style
# ──────────────────────────────────────────────────────────────────────────────
# Palette from the Oído style guide
BG, SURFACE, SURFACE2, BORDER = "#0B0D10", "#161A20", "#1D222A", "#232833"
TEXT, MUTED, ACCENT, ACCENT_INK = "#E6E8ED", "#9CA3AF", "#C6F44A", "#0B0D10"
BLUE, PURPLE, PINK = "#3B82F6", "#8B5CF6", "#EC4899"
LEVEL_COLOR = {GOOD: ACCENT, OK: "#9BD84A", WARN: "#F5B544", BAD: PINK, INFO: "#60A5FA"}
LUT_STOPS = [(0.00, (0, 0, 0)), (0.15, (14, 10, 58)), (0.35, (88, 22, 128)), (0.55, (196, 42, 112)),
             (0.72, (248, 112, 44)), (0.88, (255, 208, 64)), (1.00, (255, 255, 232))]
_x = np.linspace(0, 1, 256)
LUT = np.stack([np.interp(_x, [p for p, _ in LUT_STOPS], [c[i] for _, c in LUT_STOPS]) for i in range(3)],
               axis=1).astype(np.uint8)

QSS = f"""
* {{ font-family:'Inter','Segoe UI Variable Text','Segoe UI',sans-serif; color:{TEXT}; }}
QWidget#root {{ background:{BG}; }}
QLabel#brand {{ font-size:20px; font-weight:700; }}
QLabel#h {{ color:{MUTED}; font-size:11px; font-weight:600; letter-spacing:1.2px; }}
QLabel#muted {{ color:{MUTED}; font-size:12px; }}
QLabel#fname {{ font-size:17px; font-weight:700; }}
QLabel#chip {{ background:{SURFACE2}; border:1px solid {BORDER}; border-radius:8px; padding:4px 10px; font-size:11px; color:{MUTED}; }}
QFrame#card {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:14px; }}
QFrame#drop {{ background:{SURFACE}; border:1.5px dashed {BORDER}; border-radius:18px; }}
QFrame#drop[hot="true"] {{ border-color:{ACCENT}; }}
QLabel#cardTitle {{ font-size:12px; font-weight:600; color:{MUTED}; }}
QLabel#cardValue {{ font-size:22px; font-weight:700; }}
QLabel#body {{ font-size:13px; }}
QLabel#learn {{ font-size:12px; color:{MUTED}; }}
QFrame#segWrap {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:12px; }}
QPushButton#seg {{ background:transparent; border:none; border-radius:9px; padding:6px 14px; color:{MUTED}; font-weight:600; }}
QPushButton#seg:hover {{ color:{TEXT}; }}
QPushButton#seg:checked {{ background:{SURFACE2}; color:{TEXT}; }}
QPushButton#chipBtn {{ background:{SURFACE2}; border:1px solid {BORDER}; border-radius:9px; padding:5px 11px;
                      font-size:12px; font-weight:600; color:{MUTED}; }}
QPushButton#chipBtn:hover {{ color:{TEXT}; }}
QPushButton#chipBtn:checked {{ background:{ACCENT}; border-color:{ACCENT}; color:{ACCENT_INK}; }}
QPushButton#chipBtn:disabled {{ color:#4A4F59; }}
QPushButton#ghost {{ background:transparent; border:1px solid {BORDER}; border-radius:10px; padding:7px 14px; }}
QPushButton#ghost:hover {{ background:{SURFACE2}; }}
QPushButton#ghost:checked {{ border-color:{ACCENT}; color:{ACCENT}; }}
QComboBox#lang {{ min-width:0; padding:5px 8px; background:transparent; }}
QPushButton#verBtn {{ background:transparent; border:none; color:{MUTED}; font-size:11px; padding:4px 6px; }}
QPushButton#verBtn:hover {{ color:{TEXT}; }}
QPushButton#play {{ background:{ACCENT}; color:{ACCENT_INK}; border:none; border-radius:17px; font-size:14px;
                   font-weight:800; min-width:34px; max-width:34px; min-height:34px; max-height:34px; }}
QPushButton#play:disabled {{ background:{SURFACE2}; color:#4A4F59; }}
QPushButton#ab {{ background:{SURFACE2}; border:1px solid {BORDER}; border-radius:10px; padding:8px 22px;
                 font-size:15px; font-weight:800; color:{MUTED}; }}
QPushButton#ab:checked {{ background:{ACCENT}; color:{ACCENT_INK}; border-color:{ACCENT}; }}
QListWidget {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:14px; padding:6px; outline:none; }}
QListWidget::item {{ padding:8px 8px; border-radius:9px; color:{TEXT}; }}
QListWidget::item:selected {{ background:{SURFACE2}; }}
QListWidget::item:hover {{ background:#191C22; }}
QComboBox {{ background:{SURFACE2}; border:1px solid {BORDER}; border-radius:9px; padding:6px 10px; min-width:240px; }}
QComboBox QAbstractItemView {{ background:{SURFACE2}; selection-background-color:{BORDER}; }}
QCheckBox {{ color:{MUTED}; font-size:12px; spacing:8px; }}
QCheckBox::indicator {{ width:16px; height:16px; border-radius:5px; border:1px solid {BORDER}; background:{SURFACE2}; }}
QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
QMenu {{ background:{SURFACE2}; border:1px solid {BORDER}; padding:4px; }}
QMenu::item {{ padding:6px 18px; border-radius:6px; }}
QMenu::item:selected {{ background:{BORDER}; }}
QScrollArea {{ background:transparent; border:none; }}
QScrollArea > QWidget > QWidget {{ background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:4px; min-height:30px; }}
QScrollBar:horizontal {{ background:transparent; height:8px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{BORDER}; border-radius:4px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QSplitter::handle {{ background:transparent; }}
QSplitter::handle:hover {{ background:{BORDER}; border-radius:3px; }}
QToolTip {{ background:{SURFACE2}; color:{TEXT}; border:1px solid {BORDER}; padding:6px; }}
"""


def lbl(text, name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    w.setTextFormat(Qt.RichText)
    return w


def pill(text, level):
    q = QColor(LEVEL_COLOR[level])
    w = QLabel(text)
    w.setStyleSheet(f"background:rgba({q.red()},{q.green()},{q.blue()},36); color:{q.name()};"
                    f"border:1px solid rgba({q.red()},{q.green()},{q.blue()},90); border-radius:9px;"
                    f"padding:3px 10px; font-size:11px; font-weight:700;")
    w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return w


def btn(text, name="ghost", checkable=False, tip="", ico=None, fg=None, ac=None):
    b = QPushButton(text)
    if ico:
        b.setIcon(icon(ico, fg or TEXT, ac or ACCENT))
        b.setIconSize(QSize(16, 16))
    b.setObjectName(name)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def dot_icon(color):
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 10, 10)
    p.end()
    return pm


def clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            clear(it.layout())


def mmss(t):
    t = max(0, t)
    return f"{int(t // 60)}:{int(t % 60):02d}"


def card(title, value, level, pill_text, text, learn=""):
    c = QFrame()
    c.setObjectName("card")
    v = QVBoxLayout(c)
    v.setContentsMargins(18, 14, 18, 16)
    v.setSpacing(6)
    top = QHBoxLayout()
    top.addWidget(lbl(title, "cardTitle"))
    top.addStretch(1)
    top.addWidget(pill(pill_text, level))
    v.addLayout(top)
    v.addWidget(lbl(value, "cardValue"))
    v.addWidget(lbl(text, "body", wrap=True))
    if learn:
        v.addWidget(lbl("💡 " + learn, "learn", wrap=True))
    return c


# ──────────────────────────────────────────────────────────────────────────────
#  Player
# ──────────────────────────────────────────────────────────────────────────────
LISTEN_MODES = [  # key, label, ffmpeg filter, what it teaches
    ("normal", "Normal", None, "The track as it is."),
    ("mono", "Mono", None, "How it sounds on a phone or a Bluetooth speaker. If something disappears, there are phase issues."),
    ("side", "Side", None, "Only what differs between left and right: reverbs, backing vocals, wide guitars. The mix's width."),
    ("high", "Only >16 kHz", "highpass=f=16000,highpass=f=16000,highpass=f=16000",
     "Only what lives above 16 kHz, boosted so you can hear it. Exactly what a bad MP3 or YouTube cuts away."),
    ("low", "Only <150 Hz", "lowpass=f=150,lowpass=f=150,lowpass=f=150",
     "Only kick and bass. Listen for whether they're centered and whether they step on each other."),
]


class Track:
    def __init__(self, path, x, sr, gain_db=0.0):
        self.path, self.x, self.sr, self.gain_db = path, x, sr, gain_db
        self.cache: dict[str, np.ndarray] = {}


class Gen(QIODevice):
    """Pull-mode source for QAudioSink: serves interleaved float32 from the current position."""

    def __init__(self, player):
        super().__init__()
        self.p = player

    def readData(self, maxlen):
        buf = self.p.buf
        if buf is None or maxlen <= 0:
            return b""
        start = self.p.pos * 2
        if start >= len(buf):
            return b""
        end = min(len(buf), start + (maxlen // 8) * 2)
        self.p.pos = end // 2
        return buf[start:end].tobytes()

    def writeData(self, data):
        return 0

    def bytesAvailable(self):
        return (1 << 22) + super().bytesAvailable()

    def isSequential(self):
        return True


class PrepJob(QRunnable):
    def __init__(self, player, slot, path, sr, ch, mode, token):
        super().__init__()
        self.player, self.slot, self.path, self.sr, self.ch, self.mode, self.token = player, slot, path, sr, ch, mode, token

    def run(self):
        try:
            af = dict((k, f) for k, _, f, _ in LISTEN_MODES)[self.mode]
            x = E.decode(Path(self.path), self.sr, self.ch, af)
            if self.ch == 1:
                x = np.repeat(x, 2, axis=1)
            if self.mode == "mono":
                m = x.mean(axis=1, keepdims=True)
                x = np.repeat(m, 2, axis=1)
            elif self.mode == "side":
                s = (x[:, :1] - x[:, 1:]) / 2
                x = np.repeat(s, 2, axis=1)
            elif self.mode == "high":
                pk = float(np.max(np.abs(x))) or 1.0
                x = x * (0.5 / pk)  # amplificado para que se oiga
            self.player.prepared.emit(self.slot, self.mode, np.ascontiguousarray(x, dtype=np.float32), self.path)
        except Exception as e:  # noqa: BLE001
            self.player.error.emit(str(e))


class Player(QObject):
    prepared = Signal(str, str, object, str)
    error = Signal(str)
    tick = Signal(float)          # segundos
    state = Signal(bool)          # reproduciendo
    busy = Signal(bool)

    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.tracks: dict[str, Track] = {}
        self.slot = "A"
        self.mode = "normal"
        self.buf = None
        self.pos = 0
        self.sink = None
        self.gen = None
        self.playing = False
        self.start_t = 0.0
        self.token = 0
        self.want_play = False
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.prepared.connect(self._on_prepared)
        self._qtm = None
        self.ok = os.environ.get("OIDO_NO_AUDIO") != "1"   # audio is only initialized on the first ▶

    def _audio(self):
        if self._qtm is None and self.ok:
            try:
                from PySide6 import QtMultimedia as qtm
                if qtm.QMediaDevices.defaultAudioOutput().isNull():
                    self.ok = False
                else:
                    self._qtm = qtm
            except Exception:  # noqa: BLE001
                self.ok = False
        return self._qtm

    # ── loading ──
    def load(self, slot, path, info, gain_db=0.0):
        self.stop()
        self.tracks[slot] = Track(path, None, info["sr"], gain_db)
        self.tracks[slot].ch = 2 if info["channels"] >= 2 else 1
        self._prepare(slot, self.mode)

    def unload(self, slot):
        if slot in self.tracks:
            del self.tracks[slot]

    def _prepare(self, slot, mode):
        trk = self.tracks.get(slot)
        if not trk:
            return
        if mode in trk.cache:
            if slot == self.slot:
                self._apply()
            return
        self.token += 1
        self.busy.emit(True)
        self.pool.start(PrepJob(self, slot, trk.path, trk.sr, trk.ch, mode, self.token))

    def _on_prepared(self, slot, mode, x, path):
        trk = self.tracks.get(slot)
        if not trk or trk.path != path:   # arrived late: that slot now holds another track
            return
        trk.cache = {k: v for k, v in trk.cache.items() if k == "normal"}  # no acumular modos en memoria
        trk.cache[mode] = x
        if slot == self.slot and mode == self.mode:
            self.busy.emit(False)
            self._apply()
            if self.want_play:
                self.want_play = False
                self.play()

    def _apply(self):
        trk = self.tracks.get(self.slot)
        if not trk or self.mode not in trk.cache:
            self.buf = None
            return
        x = trk.cache[self.mode]
        g = 10 ** (trk.gain_db / 20)
        self.buf = (x * g).ravel() if abs(trk.gain_db) > 0.01 else x.ravel()

    # ── control ──
    def duration(self):
        trk = self.tracks.get(self.slot)
        return (len(self.buf) // 2) / trk.sr if trk and self.buf is not None else 0.0

    def current(self):
        trk = self.tracks.get(self.slot)
        if not trk:
            return 0.0
        if self.playing and self.sink:
            return self.start_t + self.sink.processedUSecs() / 1e6
        return self.pos / trk.sr

    def play(self):
        if not self._audio():
            self.error.emit(tr("No audio output device found."))
            return
        if self.buf is None:
            self.want_play = True
            return
        trk = self.tracks[self.slot]
        if self.pos * 2 >= len(self.buf):
            self.pos = 0
        qtm = self._audio()
        fmt = qtm.QAudioFormat()
        fmt.setSampleRate(trk.sr)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(qtm.QAudioFormat.SampleFormat.Float)
        dev = qtm.QMediaDevices.defaultAudioOutput()
        if not dev.isFormatSupported(fmt):   # p. ej. 96 kHz en placas que no lo soportan
            self.error.emit(tr("Your audio output doesn't support {sr} kHz float.", sr=f"{trk.sr / 1000:g}"))
            return
        self.sink = qtm.QAudioSink(dev, fmt, self)
        self.sink.setBufferSize(int(trk.sr * 2 * 4 * 0.12))
        self.sink.stateChanged.connect(self._on_state)
        self.gen = Gen(self)
        self.gen.open(QIODevice.ReadOnly)
        self.start_t = self.pos / trk.sr
        self.sink.start(self.gen)
        self.playing = True
        self.timer.start()
        self.state.emit(True)

    def pause(self):
        if self.sink:
            t = self.current()
            self.sink.stateChanged.disconnect(self._on_state)
            self.sink.stop()
            self.sink = None
            trk = self.tracks.get(self.slot)
            if trk:
                self.pos = int(t * trk.sr)
        self.playing = False
        self.timer.stop()
        self.state.emit(False)
        self.tick.emit(self.current())

    def stop(self):
        self.pause()
        self.pos = 0

    def toggle(self):
        self.pause() if self.playing else self.play()

    def seek(self, t):
        was = self.playing
        if was:
            self.pause()
        trk = self.tracks.get(self.slot)
        if trk:
            self.pos = int(max(0.0, t) * trk.sr)
        self.tick.emit(self.current())
        if was:
            self.play()

    def set_mode(self, mode):
        t, was = self.current(), self.playing
        if was:
            self.pause()
        self.mode = mode
        self.buf = None
        trk = self.tracks.get(self.slot)
        if trk:
            self.pos = int(t * trk.sr)
        self.want_play = was
        self._prepare(self.slot, mode)
        for s in self.tracks:
            if s != self.slot:
                self._prepare(s, mode)

    def set_slot(self, slot):
        if slot not in self.tracks or slot == self.slot:
            return
        t, was = self.current(), self.playing
        if was:
            self.pause()
        self.slot = slot
        self.pos = int(t * self.tracks[slot].sr)
        self.buf = None
        self.want_play = was
        self._prepare(slot, self.mode)

    def set_gain(self, slot, db):
        if slot in self.tracks:
            self.tracks[slot].gain_db = db
            if slot == self.slot:
                was = self.playing
                if was:
                    self.pause()
                self._apply()
                if was:
                    self.play()

    def _tick(self):
        self.tick.emit(self.current())

    def _on_state(self, st):
        qtm = self._audio()
        if st == qtm.QAudio.State.IdleState and self.buf is not None and self.pos * 2 >= len(self.buf):
            self.stop()


# ──────────────────────────────────────────────────────────────────────────────
#  Visualization widgets
# ──────────────────────────────────────────────────────────────────────────────
LOG_TICKS = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
M_LEFT, M_RIGHT = 52, 80


class TimeView(QObject):
    """Shared time window (zoom) for the spectrogram and the loudness curve."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.dur = 1.0
        self.t0, self.t1 = 0.0, 1.0

    def reset(self, dur=None):
        if dur:
            self.dur = dur
        self.t0, self.t1 = 0.0, self.dur
        self.changed.emit()

    def zoom(self, center_t, factor):
        span = min(self.dur, max(2.0, (self.t1 - self.t0) * factor))
        frac = (center_t - self.t0) / max(self.t1 - self.t0, 1e-9)
        t0 = center_t - frac * span
        t0 = min(max(0.0, t0), self.dur - span)
        self.t0, self.t1 = t0, t0 + span
        self.changed.emit()

    def follow(self, t):
        span = self.t1 - self.t0
        if span < self.dur and not (self.t0 <= t <= self.t1):
            self.t0 = min(max(0.0, t - span * 0.1), self.dur - span)
            self.t1 = self.t0 + span
            self.changed.emit()


class Spectrogram(QWidget):
    seek = Signal(float)

    def __init__(self, view: TimeView, compact=False):
        super().__init__()
        self.view = view
        view.changed.connect(self.update)
        self.setMinimumHeight(150 if compact else 170)
        self.setMouseTracking(True)
        self.r = None
        self.scale = "lin"
        self.imgs = {}
        self.hover = None
        self.playhead = None

    def set_data(self, r):
        self.r = r
        self.imgs = {}
        self.update()

    def set_scale(self, s):
        self.scale = s
        self.update()

    def _img(self):
        if self.scale not in self.imgs:
            lv = self.r["level_lin" if self.scale == "lin" else "level_log"]
            rgb = np.ascontiguousarray(LUT[lv])
            h, w, _ = rgb.shape
            self.imgs[self.scale] = (QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy(), lv)
        return self.imgs[self.scale]

    def plot(self):
        return QRectF(M_LEFT, 8, self.width() - M_LEFT - M_RIGHT, self.height() - 8 - 26)

    # frecuencia ↔ y
    def f_to_y(self, f, pr):
        nyq = self.r["nyq"]
        if self.scale == "lin":
            return pr.bottom() - f / nyq * pr.height()
        f = min(max(f, E.F_MIN_LOG), nyq)
        return pr.bottom() - np.log(f / E.F_MIN_LOG) / np.log(nyq / E.F_MIN_LOG) * pr.height()

    def y_to_f(self, y, pr):
        nyq = self.r["nyq"]
        fy = (pr.bottom() - y) / pr.height()
        return fy * nyq if self.scale == "lin" else E.F_MIN_LOG * (nyq / E.F_MIN_LOG) ** fy

    def t_to_x(self, t, pr):
        v = self.view
        return pr.left() + (t - v.t0) / max(v.t1 - v.t0, 1e-9) * pr.width()

    def x_to_t(self, x, pr):
        v = self.view
        return v.t0 + (x - pr.left()) / pr.width() * (v.t1 - v.t0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(SURFACE))
        if not self.r:
            return
        pr = self.plot()
        img, lv = self._img()
        v, dur = self.view, self.r["duration"]
        sx0, sx1 = v.t0 / dur * img.width(), v.t1 / dur * img.width()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(pr, img, QRectF(sx0, 0, max(sx1 - sx0, 1), img.height()))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        nyq = self.r["nyq"]
        ticks = (range(0, int(nyq) + 1, 2000 if nyq <= 24000 else 5000 if nyq <= 48000 else 10000)
                 if self.scale == "lin" else [t for t in LOG_TICKS if t < nyq])
        for fr in ticks:
            y = self.f_to_y(fr, pr)
            p.setPen(QColor(MUTED))
            lab = f"{fr // 1000}k" if fr >= 1000 else f"{fr}"
            p.drawText(QRectF(0, y - 8, M_LEFT - 6, 16), Qt.AlignRight | Qt.AlignVCenter, lab)
            p.setPen(QColor(255, 255, 255, 18))
            p.drawLine(QPointF(pr.left(), y), QPointF(pr.right(), y))
        span = v.t1 - v.t0
        tstep = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if span / s <= 9), 1200)
        t = (int(v.t0 // tstep) + 1) * tstep if v.t0 > 0 else 0
        p.setPen(QColor(MUTED))
        while t <= v.t1:
            x = self.t_to_x(t, pr)
            p.drawText(QRectF(x - 30, pr.bottom() + 5, 60, 16), Qt.AlignCenter, mmss(t))
            t += tstep
        # leyenda de color
        lg = QRectF(pr.right() + 14, pr.top(), 12, pr.height())
        for i in range(int(lg.height())):
            c = LUT[255 - int(i / lg.height() * 255)]
            p.setPen(QColor(int(c[0]), int(c[1]), int(c[2])))
            p.drawLine(QPointF(lg.left(), lg.top() + i), QPointF(lg.right(), lg.top() + i))
        p.setPen(QColor(MUTED))
        for db, yy in ((0, lg.top()), (-60, lg.center().y()), (-120, lg.bottom())):
            p.drawText(QRectF(lg.right() + 4, yy - 8, 44, 16), Qt.AlignLeft | Qt.AlignVCenter, f"{db} dB")
        # ceiling and flashes
        bw = self.r["bw"]
        lines = [(bw["eff"], (tr("ceiling") if bw["wall"] else tr("reaches")) + f" ≈ {bw['eff'] / 1000:.1f} kHz", Qt.DashLine, ACCENT)]
        if bw.get("sporadic"):
            lines.append((bw["sporadic"], tr("flashes") + f" ≈ {bw['sporadic'] / 1000:.1f} kHz", Qt.DotLine, BLUE))
        fm = p.fontMetrics()
        used = []
        for fr, tag, style, col in lines:
            y = self.f_to_y(fr, pr)
            p.setPen(QPen(QColor(col), 1.3, style))
            p.drawLine(QPointF(pr.left(), y), QPointF(pr.right(), y))
            tw = fm.horizontalAdvance(tag) + 14
            by = max(pr.top() + 2, y - 21)
            while any(abs(by - u) < 20 for u in used):
                by += 21
            used.append(by)
            box = QRectF(pr.right() - tw - 6, by, tw, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(ACCENT_INK))
            p.drawText(box, Qt.AlignCenter, tag)
        # playhead
        if self.playhead is not None and v.t0 <= self.playhead <= v.t1:
            x = self.t_to_x(self.playhead, pr)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            p.drawLine(QPointF(x, pr.top()), QPointF(x, pr.bottom()))
        # lectura bajo el mouse
        if self.hover and pr.contains(self.hover):
            t = self.x_to_t(self.hover.x(), pr)
            fr = self.y_to_f(self.hover.y(), pr)
            col = min(int(t / dur * lv.shape[1]), lv.shape[1] - 1)
            row = min(max(int((pr.bottom() - self.hover.y()) / pr.height() * lv.shape[0]), 0), lv.shape[0] - 1)
            db = E.DB_MIN + lv[lv.shape[0] - 1 - row, col] / 255 * -E.DB_MIN
            ftxt = f"{fr / 1000:.1f} kHz" if fr >= 1000 else f"{fr:.0f} Hz"
            txt = f"{ftxt} · {mmss(t)} · {db:.0f} dB"
            p.setPen(QPen(QColor(255, 255, 255, 60), 1))
            p.drawLine(QPointF(pr.left(), self.hover.y()), QPointF(pr.right(), self.hover.y()))
            p.drawLine(QPointF(self.hover.x(), pr.top()), QPointF(self.hover.x(), pr.bottom()))
            box = QRectF(pr.left() + 8, pr.top() + 8, fm.horizontalAdvance(txt) + 16, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(TEXT))
            p.drawText(box, Qt.AlignCenter, txt)

    def mouseMoveEvent(self, e):
        self.hover = e.position()
        self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        pr = self.plot()
        if self.r and e.button() == Qt.LeftButton and pr.contains(e.position()):
            self.seek.emit(self.x_to_t(e.position().x(), pr))

    def mouseDoubleClickEvent(self, _):
        self.view.reset()

    def wheelEvent(self, e):
        if not self.r:
            return
        pr = self.plot()
        t = self.x_to_t(min(max(e.position().x(), pr.left()), pr.right()), pr)
        self.view.zoom(t, 0.8 if e.angleDelta().y() > 0 else 1.25)


class LoudnessCurve(QWidget):
    seek = Signal(float)

    def __init__(self, view: TimeView):
        super().__init__()
        self.view = view
        view.changed.connect(self.update)
        self.setFixedHeight(96)
        self.setMouseTracking(True)
        self.r = None
        self.playhead = None
        self.hover = None

    def set_data(self, r):
        self.r = r
        self.update()

    def plot(self):
        return QRectF(M_LEFT, 6, self.width() - M_LEFT - M_RIGHT, self.height() - 12)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(SURFACE))
        r = self.r
        if not r or not len(r["curve_t"]):
            return
        pr = self.plot()
        v = self.view
        lo, hi = -40.0, 0.0
        y = lambda db: pr.bottom() - (min(max(db, lo), hi) - lo) / (hi - lo) * pr.height()  # noqa: E731
        x = lambda t: pr.left() + (t - v.t0) / max(v.t1 - v.t0, 1e-9) * pr.width()  # noqa: E731
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        for db in (-10, -20, -30):
            p.setPen(QColor(255, 255, 255, 16))
            p.drawLine(QPointF(pr.left(), y(db)), QPointF(pr.right(), y(db)))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y(db) - 8, M_LEFT - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{db}")
        t, m, s = r["curve_t"], r["curve_m"], r["curve_s"]
        sel = (t >= v.t0 - 1) & (t <= v.t1 + 1)
        step = max(1, int(sel.sum() / max(pr.width(), 1)))
        for arr, col, w in ((m, QColor(255, 255, 255, 40), 1.0), (s, QColor(ACCENT), 1.8)):
            path = QPainterPath()
            first = True
            for tt, vv in zip(t[sel][::step], arr[sel][::step]):
                pt = QPointF(x(tt), y(vv))
                path.moveTo(pt) if first else path.lineTo(pt)
                first = False
            p.setPen(QPen(col, w))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        fm = p.fontMetrics()
        used = []
        for val, col, tag in ((r["I"], TEXT, tr("integr.")), (E.SPOTIFY_LUFS, BLUE, "Spotify")):
            if val is None:
                continue
            p.setPen(QPen(QColor(col), 1, Qt.DashLine))
            p.drawLine(QPointF(pr.left(), y(val)), QPointF(pr.right(), y(val)))
            ly = y(val)
            while any(abs(ly - u) < 13 for u in used):
                ly += 13
            used.append(ly)
            p.setPen(QColor(col))
            p.drawText(QRectF(pr.right() + 6, ly - 8, M_RIGHT, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{val:.0f} {tag}")
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(pr.left() + 6, pr.top(), 600, 14), Qt.AlignLeft,
                   tr("LOUDNESS (LUFS) · green = short-term (3 s) · gray = momentary"))
        if self.playhead is not None and v.t0 <= self.playhead <= v.t1:
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
            p.drawLine(QPointF(x(self.playhead), pr.top()), QPointF(x(self.playhead), pr.bottom()))
        if self.hover and pr.contains(self.hover):
            tt = v.t0 + (self.hover.x() - pr.left()) / pr.width() * (v.t1 - v.t0)
            i = int(np.clip(np.searchsorted(t, tt), 0, len(t) - 1))
            txt = f"{mmss(tt)} · {s[i]:.1f} LUFS"
            box = QRectF(self.hover.x() + 10, pr.top() + 14, fm.horizontalAdvance(txt) + 14, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor(TEXT))
            p.drawText(box, Qt.AlignCenter, txt)

    def mouseMoveEvent(self, e):
        self.hover = e.position()
        self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        pr = self.plot()
        if self.r and pr.contains(e.position()):
            v = self.view
            self.seek.emit(v.t0 + (e.position().x() - pr.left()) / pr.width() * (v.t1 - v.t0))

    def wheelEvent(self, e):
        if self.r:
            pr = self.plot()
            v = self.view
            t = v.t0 + (min(max(e.position().x(), pr.left()), pr.right()) - pr.left()) / pr.width() * (v.t1 - v.t0)
            v.zoom(t, 0.8 if e.angleDelta().y() > 0 else 1.25)


class Vectorscope(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 330)
        self.static = None
        self.live = None
        self.corr_all = None
        self.corr_live = None
        self._cache = None   # (size, QImage)

    def set_static(self, pts, corr):
        self.static = pts
        self.corr_all = corr
        self.live = None
        self.corr_live = None
        self._cache = None
        self.update()

    def set_live(self, pts):
        self.live = pts
        self.corr_live = None
        if pts is not None and len(pts):
            l_, r_ = pts[:, 0].astype(np.float64), pts[:, 1].astype(np.float64)
            d = np.sqrt(np.sum(l_ ** 2) * np.sum(r_ ** 2))
            self.corr_live = float(np.sum(l_ * r_) / d) if d > 1e-12 else None
        self.update()

    @staticmethod
    def _ms(pts):
        pk = float(np.percentile(np.abs(pts), 99.5)) or 1.0   # like a goniometer: scale by percentile, not by peak
        lft, rgt = np.clip(pts[:, 0] / pk, -1.1, 1.1), np.clip(pts[:, 1] / pk, -1.1, 1.1)
        return (rgt - lft) / np.sqrt(2) * 0.9, (lft + rgt) / np.sqrt(2) * 0.9   # x = side, y = mid

    def _density(self, size):
        xs, ys = self._ms(self.static)
        h, _, _ = np.histogram2d(-ys, xs, bins=size, range=[[-1, 1], [-1, 1]])
        a = np.log1p(h)
        a = (a / (a.max() or 1) * 230).astype(np.uint8)
        q = QColor(BLUE)
        rgba = np.zeros((size, size, 4), np.uint8)
        rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3] = q.red(), q.green(), q.blue(), a
        rgba = np.ascontiguousarray(rgba)
        return QImage(rgba.data, size, size, 4 * size, QImage.Format_RGBA8888).copy()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(SURFACE))
        w, h = self.width(), self.height() - 46
        rad = min(w, h) / 2 - 22
        cx, cy = w / 2, h / 2 + 4
        if self.static is not None and len(self.static):
            size = max(64, int(rad * 2))
            if not self._cache or self._cache[0] != size:
                self._cache = (size, self._density(size))
            p.drawImage(QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad), self._cache[1])
        p.setPen(QPen(QColor(BORDER), 1))
        diamond = QPainterPath()
        diamond.moveTo(cx, cy - rad)
        diamond.lineTo(cx + rad, cy)
        diamond.lineTo(cx, cy + rad)
        diamond.lineTo(cx - rad, cy)
        diamond.closeSubpath()
        p.setBrush(Qt.NoBrush)
        p.drawPath(diamond)
        p.setPen(QPen(QColor(BORDER), 1, Qt.DashLine))
        p.drawLine(QPointF(cx, cy - rad), QPointF(cx, cy + rad))
        p.drawLine(QPointF(cx - rad / 2, cy - rad / 2), QPointF(cx + rad / 2, cy + rad / 2))
        p.drawLine(QPointF(cx + rad / 2, cy - rad / 2), QPointF(cx - rad / 2, cy + rad / 2))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(cx - 40, cy - rad - 18, 80, 14), Qt.AlignCenter, tr("M (center)"))
        p.drawText(QRectF(cx - rad / 2 - 40, cy - rad / 2 - 18, 36, 14), Qt.AlignRight, "L")
        p.drawText(QRectF(cx + rad / 2 + 4, cy - rad / 2 - 18, 40, 14), Qt.AlignLeft, "R")
        p.drawText(QRectF(cx + rad + 4, cy - 7, 40, 14), Qt.AlignLeft, "S")
        if self.live is not None and len(self.live):
            xs, ys = self._ms(self.live)
            p.setPen(QPen(QColor(200, 240, 81, 150), 2))
            p.drawPoints(QPolygonF([QPointF(cx + a * rad, cy - b * rad) for a, b in zip(xs, ys)]))
        bar = QRectF(24, self.height() - 34, w - 48, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SURFACE2))
        p.drawRoundedRect(bar, 4, 4)
        p.setPen(QColor(MUTED))
        for val, tag in ((-1, tr("-1 phase")), (0, "0"), (1, tr("+1 mono"))):
            xx = bar.left() + (val + 1) / 2 * bar.width()
            p.drawText(QRectF(xx - 40, bar.bottom() + 3, 80, 14), Qt.AlignCenter, tag)
        for val, col in ((self.corr_all, BLUE), (self.corr_live, ACCENT)):
            if val is None:
                continue
            xx = bar.left() + (val + 1) / 2 * bar.width()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(xx - 3, bar.top() - 4, 6, 16), 3, 3)


class BandBars(QWidget):
    def __init__(self, a, b=None, names=("A", "B")):
        super().__init__()
        self.a, self.b, self.names = a, b, names
        self.setMinimumHeight(220)

    def paintEvent(self, _):
        if not self.a:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.a)
        w, h = self.width(), self.height()
        top, bottom = 24, h - 52
        zero = (top + bottom) / 2
        allv = [x["rel"] for x in self.a] + ([x["rel"] for x in self.b] if self.b else [])
        span = max(6.0, max(abs(v) for v in allv))
        p.setPen(QPen(QColor(BORDER), 1, Qt.DashLine))
        p.drawLine(QPointF(0, zero), QPointF(w, zero))
        bw = w / n
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        series = [(self.a, ACCENT, BLUE)] if not self.b else [(self.a, ACCENT, ACCENT), (self.b, BLUE, BLUE)]
        k = len(series)
        for si, (data, cpos, cneg) in enumerate(series):
            for i, b in enumerate(data):
                slot_w = bw * 0.6 / k
                x = i * bw + bw * 0.2 + si * slot_w
                hh = b["rel"] / span * (bottom - top) / 2
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(cpos if b["rel"] >= 0 else cneg))
                p.drawRoundedRect(QRectF(x, zero - max(hh, 0), slot_w - 2, abs(hh) or 1), 3, 3)
                p.setPen(QColor(MUTED))
                yy = zero - hh - 15 if hh >= 0 else zero - hh + 2
                p.drawText(QRectF(x - 10, yy, slot_w + 18, 13), Qt.AlignCenter, f"{b['rel']:+.0f}")
        for i, b in enumerate(self.a):
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(i * bw, h - 32, bw, 14), Qt.AlignCenter, tr(b["name"]))
            p.setPen(QColor(MUTED))
            rng = f"{b['lo']}–{b['hi'] / 1000:g}k" if b["hi"] >= 1000 else f"{b['lo']}–{b['hi']:g}"
            p.drawText(QRectF(i * bw, h - 17, bw, 14), Qt.AlignCenter, rng + " Hz")
        if self.b:
            p.setPen(QColor(ACCENT))
            p.drawText(QRectF(4, 2, 200, 14), Qt.AlignLeft, f"■ {self.names[0]}")
            p.setPen(QColor(BLUE))
            p.drawText(QRectF(60, 2, 200, 14), Qt.AlignLeft, f"■ {self.names[1]}")


# ──────────────────────────────────────────────────────────────────────────────
#  "Learn" tab content
# ──────────────────────────────────────────────────────────────────────────────
LEARN_SECTIONS = [
    ("How to read the spectrogram",
     "<p>It's a picture of the sound: <b>left to right</b> is time, <b>bottom to top</b> goes from lows to highs, and "
     "<b>color</b> is intensity (black = nothing, yellow/white = a lot). Hover to read frequency, time and level. "
     "<b>Mouse wheel</b> = zoom in time · <b>double-click</b> = see everything · <b>click</b> = play from there.</p>"
     "<ul><li><b>Vertical lines</b> = hits (kick, snare, claps). Evenly spaced = the tempo.</li>"
     "<li><b>Parallel horizontal lines down low</b> = sustained notes. A pitched note is a 'comb': the fundamental with "
     "its harmonics stacked above. Use the <b>Log</b> scale to see them clearly.</li>"
     "<li><b>Blocks that light up or go dark</b> = the song's structure: intro, verse, chorus, drop, breakdown. You can "
     "read the arrangement without hearing it.</li>"
     "<li><b>An even wall of color with no edges</b> = a heavily compressed master. Dark 'air' between hits = more "
     "dynamics.</li>"
     "<li><b>A perfectly straight horizontal line up high</b> = an encoder's cutoff. Nature doesn't draw straight lines.</li>"
     "<li><b>Highs that fade out gradually</b> = that's the recording (tape, microphones, era). Not the file's fault.</li></ul>"),
    ("Linear vs. Log",
     "<p>The ear hears in <b>octaves</b>: each octave doubles the frequency. Between 20 Hz and 2 kHz there are 6.6 octaves "
     "(bass, vocals, harmony); between 2 and 22 kHz, only 3.5. The <b>linear</b> scale gives those 6.6 octaves just 9% of "
     "the height: great for spotting codec cutoffs. The <b>Log</b> scale spreads octaves evenly: great for reading music.</p>"),
    ("Listen to understand",
     "<ul><li><b>Mono</b>: if an instrument vanishes or the bass loses power, there are phase issues.</li>"
     "<li><b>Side</b>: only what's on the sides. You'll be surprised how much reverb and backing vocals live there.</li>"
     "<li><b>Only &gt;16 kHz</b>: the 'air' a bad MP3 or YouTube throws away. It's boosted so you can hear it; on a "
     "cut-off file you'll hear almost nothing.</li>"
     "<li><b>Only &lt;150 Hz</b>: kick and bass. Do they step on each other, or does each have its own space?</li></ul>"),
    ("The loudness curve",
     "<p>Under the spectrogram: the green line is perceived loudness over 3-second windows; the gray one, the momentary "
     "value. A loudness-war master is almost a flat line pinned to the top. A dynamic track rises and falls with the "
     "arrangement. The blue line is the level Spotify plays everything at.</p>"),
    ("The vectorscope",
     "<p>Each dot is an instant of audio. <b>Vertical</b> = mono/center. <b>Diagonals</b> = left only or right only. "
     "<b>Horizontal</b> = out of phase (bad). A vertical flame-shaped cloud = healthy stereo with a strong center; a wide "
     "circle = lots of information on the sides. The meter below is the correlation: blue = whole track, green = what's "
     "playing.</p>"),
    ("A/B comparison",
     "<p>Mastering's golden rule: <b>louder always seems better</b>. That's why A/B mode matches loudness (it turns the "
     "louder one down) before you compare. Quite often the 'commercial' master loses once both play at the same level.</p>"),
    ("YouTube and Opus",
     "<p>YouTube delivers audio as Opus at 48 kHz. Opus splits the spectrum into bands; the top one runs from 15.6 to "
     "20 kHz and is only filled when the highs carry enough energy. That's why tracks downloaded from YouTube show a "
     "straight line at ~16 kHz with flashes above it. Saving it as a 320 kbps MP3 won't bring back what Opus discarded.</p>"),
    ("References",
     "<p>LAME cutoff by CBR bitrate: 128 kbps ≈ 17.0 kHz · 192 ≈ 18.6 · 256 ≈ 19.7 · 320 ≈ 20.5. Spotify normalizes to "
     "{lufs} LUFS and recommends true peak ≤ -1 dBTP. The PLR, LRA and correlation ranges this app uses are rules of "
     "thumb, not standards.</p>"),
]


def learn_html() -> str:
    return "".join(f"<h3>{tr(t)}</h3>" + tr(h, **({"lufs": f"{E.SPOTIFY_LUFS:.0f}"} if "{lufs}" in h else {}))
                   for t, h in LEARN_SECTIONS)


# ──────────────────────────────────────────────────────────────────────────────
#  Background work
# ──────────────────────────────────────────────────────────────────────────────
class Bus(QObject):
    done = Signal(str, object)
    failed = Signal(str, str)


class Job(QRunnable):
    def __init__(self, path, bus):
        super().__init__()
        self.path, self.bus = path, bus

    def run(self):
        try:
            r = E.analyze(Path(self.path))
            r["quality"] = E.quality_report(r)
            r["mix"] = E.mix_report(r)
            r["stereo"] = E.stereo_report(r)
            self.bus.done.emit(self.path, r)
        except Exception as e:  # noqa: BLE001
            self.bus.failed.emit(self.path, str(e))


# ──────────────────────────────────────────────────────────────────────────────
#  Main window
# ──────────────────────────────────────────────────────────────────────────────
class PlayerBar(QWidget):
    """Playback controls + listening modes."""

    def __init__(self, player: Player, show_modes=True):
        super().__init__()
        self.player = player
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.play_btn = btn("", "play", tip=tr("Play / pause (Space)"), ico="play", fg=ACCENT_INK)
        self.play_btn.clicked.connect(player.toggle)
        h.addWidget(self.play_btn)
        self.time = lbl("0:00", "muted")
        self.time.setMinimumWidth(80)
        h.addWidget(self.time)
        self.mode_group = QButtonGroup(self)
        if show_modes:
            h.addWidget(lbl(tr("LISTEN"), "h"))
            for key, label, _, tip in LISTEN_MODES:
                b = btn(tr(label), "chipBtn", True, tr(tip), ico=key)
                b.setProperty("key", key)
                self.mode_group.addButton(b)
                h.addWidget(b)
                if key == "normal":
                    b.setChecked(True)
            self.mode_group.buttonClicked.connect(lambda b: player.set_mode(b.property("key")))
        h.addStretch(1)
        self.status = lbl("", "muted")
        h.addWidget(self.status)
        player.state.connect(lambda on: self.play_btn.setIcon(icon("pause" if on else "play", ACCENT_INK)))
        player.tick.connect(lambda t: self.time.setText(f"{mmss(t)} / {mmss(player.duration())}"))
        player.busy.connect(lambda b: self.status.setText(tr("Preparing audio…") if b else ""))
        player.error.connect(lambda e: self.status.setText(e))
        if not player.ok:
            self.play_btn.setEnabled(False)
            self.play_btn.setToolTip(tr("No audio output available"))


class Oido(QWidget):
    def __init__(self, isolated=False):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle(APP)
        self.setAcceptDrops(True)
        self.resize(1320, 900)
        self.setMinimumSize(1020, 720)
        self.cfg = QSettings("GermanRobert", APP)
        self.results: dict[str, dict] = {}
        self.items: dict[str, QListWidgetItem] = {}
        self.refs: list[str] = [] if isolated else [p for p in (self.cfg.value("refs", []) or []) if Path(p).exists()]
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(2)
        self.ppool = QThreadPool()
        self.ppool.setMaxThreadCount(2)
        self.bus = Bus()
        self.bus.done.connect(self._done)
        self.bus.failed.connect(self._failed)
        self.player = Player(self.ppool)
        self.player.tick.connect(self._on_tick)
        self.current = None
        self.ab = {"A": None, "B": None}

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(RT.logo_label(30))
        head.addSpacing(14)
        head.addWidget(lbl(tr("How much music is really in your file?"), "muted"))
        head.addStretch(1)
        ver = btn(f"v{__version__}", "verBtn", tip=tr("View the project on GitHub"), ico="github", fg=MUTED)
        ver.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        head.addWidget(ver)
        self.lang_box = QComboBox()
        self.lang_box.setObjectName("lang")
        self.lang_box.setToolTip(tr("Language"))
        for code, name in i18n.LANGS.items():
            self.lang_box.addItem(name, code)
        self.lang_box.setCurrentIndex(list(i18n.LANGS).index(i18n.current()))
        self.lang_box.currentIndexChanged.connect(self._change_lang)
        head.addWidget(self.lang_box)
        head.addSpacing(6)
        self.cmp_btn = btn(tr("Compare A/B"), checkable=True, tip=tr("Two tracks side by side, loudness-matched"), ico="ab")
        self.cmp_btn.toggled.connect(self._toggle_compare)
        head.addWidget(self.cmp_btn)
        exp = btn(tr("Export report"), tip=tr("CSV with every analyzed file (opens in Excel)"), ico="export")
        exp.clicked.connect(self._export)
        head.addWidget(exp)
        ob = btn(tr("Open files"), ico="folder")
        ob.clicked.connect(self._pick)
        head.addWidget(ob)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        side = QVBoxLayout()
        side.setSpacing(8)
        self.list = QListWidget()
        self.list.setFixedWidth(280)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context)
        self.list.currentItemChanged.connect(lambda cur, _: cur and self._select(cur.data(Qt.UserRole)))
        side.addWidget(self.list, 1)
        srt = btn(tr("Sort: worst quality first"), tip=tr("Review a whole folder quickly"))
        srt.clicked.connect(self._sort)
        side.addWidget(srt)
        side.addWidget(lbl(tr("Right-click a track to pin it as a reference or compare it."), "learn", wrap=True))
        body.addLayout(side)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())      # 0
        self.stack.addWidget(self._build_detail())     # 1
        self.msg = lbl("", "fname")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.stack.addWidget(self.msg)                 # 2
        self.stack.addWidget(self._build_compare())    # 3
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._pick)
        QShortcut(QKeySequence("Space"), self, activated=self.player.toggle)
        QShortcut(QKeySequence("Tab"), self, activated=self._ab_flip)
        if self.refs:
            self._add([Path(p) for p in self.refs], select=False)

    # ── build ──
    def _build_empty(self):
        drop = QFrame()
        drop.setObjectName("drop")
        dv = QVBoxLayout(drop)
        dv.setAlignment(Qt.AlignCenter)
        ic = lbl("◉")
        ic.setStyleSheet(f"font-size:30px;color:{ACCENT};")
        ic.setAlignment(Qt.AlignCenter)
        t1 = lbl(tr("Drop tracks or folders here"), "fname")
        t1.setAlignment(Qt.AlignCenter)
        t2 = lbl("MP3, FLAC, WAV, M4A, OGG, OPUS… · Ctrl+O", "muted")
        t2.setAlignment(Qt.AlignCenter)
        for w in (ic, t1, t2):
            dv.addWidget(w)
        self.drop = drop
        return drop

    def _build_detail(self):
        det = QWidget()
        dl = QVBoxLayout(det)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(10)
        top = QHBoxLayout()
        self.fname = lbl("", "fname")
        self.fname.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.fname, 1)
        self.ref_btn = btn(tr("Reference"), checkable=True, tip=tr("Save as a reference track to compare against"), ico="star")
        self.ref_btn.clicked.connect(lambda on: self._set_ref(self.current, on))
        top.addWidget(self.ref_btn)
        self.verdict_box = QHBoxLayout()
        top.addLayout(self.verdict_box)
        dl.addLayout(top)
        self.meta = QHBoxLayout()
        self.meta.setSpacing(6)
        dl.addLayout(self.meta)

        sc = QFrame()
        sc.setObjectName("card")
        sl = QVBoxLayout(sc)
        sl.setContentsMargins(10, 10, 10, 8)
        sl.setSpacing(6)
        bar = QHBoxLayout()
        self.pbar = PlayerBar(self.player)
        bar.addWidget(self.pbar, 1)
        seg = QFrame()
        seg.setObjectName("segWrap")
        sgl = QHBoxLayout(seg)
        sgl.setContentsMargins(3, 3, 3, 3)
        self.scale_group = QButtonGroup(self)
        for key, label, tip in (("lin", tr("Linear"), tr("To spot codec cutoffs (quality)")),
                                ("log", tr("Log"), tr("To read the music: low end and notes"))):
            b = btn(label, "seg", True, tip)
            b.setProperty("key", key)
            self.scale_group.addButton(b)
            sgl.addWidget(b)
            b.setChecked(key == (self.cfg.value("scale", "lin")))
        self.scale_group.buttonClicked.connect(self._set_scale)
        bar.addWidget(seg)
        sl.addLayout(bar)
        self.view = TimeView()
        self.spec = Spectrogram(self.view)
        self.spec.seek.connect(self._seek)
        self.spec.set_scale(self.cfg.value("scale", "lin"))
        sl.addWidget(self.spec, 1)
        self.curve = LoudnessCurve(self.view)
        self.curve.seek.connect(self._seek)
        sl.addWidget(self.curve)
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(10)
        self.split.addWidget(sc)
        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        dl.addWidget(self.split, 1)

        seg2 = QFrame()
        seg2.setObjectName("segWrap")
        sgl2 = QHBoxLayout(seg2)
        sgl2.setContentsMargins(4, 4, 4, 4)
        self.tabs = QButtonGroup(self)
        for i, (t, ic) in enumerate(((tr("File quality"), "quality"), (tr("Mix & master"), "loudness"),
                                     (tr("Stereo"), "scope"), (tr("Learn"), "learn"))):
            b = btn(t.replace("&", "&&"), "seg", True, ico=ic)  # a single & would become a keyboard mnemonic
            self.tabs.addButton(b, i)
            sgl2.addWidget(b)
        self.tabs.button(0).setChecked(True)
        row = QHBoxLayout()
        row.addWidget(seg2)
        row.addStretch(1)
        row.addWidget(lbl(tr("↕ drag the edge to enlarge the spectrogram"), "learn"))
        ll.addLayout(row)
        self.pages = QStackedWidget()
        self.tabs.idClicked.connect(self.pages.setCurrentIndex)
        self.scrolls = []
        for _ in range(2):
            s = QScrollArea()
            s.setWidgetResizable(True)
            s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scrolls.append(s)
            self.pages.addWidget(s)
        # stereo
        st = QWidget()
        sth = QHBoxLayout(st)
        sth.setContentsMargins(0, 0, 0, 0)
        sth.setSpacing(10)
        vc = QFrame()
        vc.setObjectName("card")
        vcl = QVBoxLayout(vc)
        vcl.setContentsMargins(12, 12, 12, 12)
        vcl.addWidget(lbl(tr("VECTORSCOPE"), "cardTitle"))
        self.scope = Vectorscope()
        vcl.addWidget(self.scope, 1)
        vc.setFixedWidth(380)
        sth.addWidget(vc)
        self.stereo_scroll = QScrollArea()
        self.stereo_scroll.setWidgetResizable(True)
        sth.addWidget(self.stereo_scroll, 1)
        self.pages.addWidget(st)
        learn = QScrollArea()
        learn.setWidgetResizable(True)
        lw = lbl(learn_html(), "body", wrap=True)
        lw.setContentsMargins(6, 0, 12, 12)
        lw.setAlignment(Qt.AlignTop)
        learn.setWidget(lw)
        self.pages.addWidget(learn)
        ll.addWidget(self.pages, 1)
        lower.setMinimumHeight(200)
        self.split.addWidget(lower)
        self.split.setStretchFactor(0, 6)
        self.split.setStretchFactor(1, 5)
        return det

    def _build_compare(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        sel = QHBoxLayout()
        self.combo = {}
        for slot, col in (("A", ACCENT), ("B", BLUE)):
            tag = lbl(slot)
            tag.setStyleSheet(f"color:{col}; font-size:18px; font-weight:800;")
            sel.addWidget(tag)
            cb = QComboBox()
            cb.currentIndexChanged.connect(lambda _, s=slot: self._ab_pick(s))
            self.combo[slot] = cb
            sel.addWidget(cb, 1)
            sel.addSpacing(10)
        sw = btn("", tip=tr("Swap A and B"), ico="swap")
        sw.clicked.connect(self._ab_swap)
        sel.addWidget(sw)
        v.addLayout(sel)
        self.ab_views = {}
        self.ab_specs = {}
        for slot in ("A", "B"):
            fr = QFrame()
            fr.setObjectName("card")
            fl = QVBoxLayout(fr)
            fl.setContentsMargins(8, 6, 8, 6)
            tv = TimeView()
            sp = Spectrogram(tv, compact=True)
            sp.seek.connect(self._seek)
            fl.addWidget(sp)
            self.ab_views[slot], self.ab_specs[slot] = tv, sp
            v.addWidget(fr, 3)
        ctl = QFrame()
        ctl.setObjectName("card")
        cl = QHBoxLayout(ctl)
        cl.setContentsMargins(14, 10, 14, 10)
        self.ab_bar = PlayerBar(self.player, show_modes=False)
        cl.addWidget(self.ab_bar)
        self.ab_group = QButtonGroup(self)
        for slot in ("A", "B"):
            b = btn(slot, "ab", True, tr("Toggle with Tab: hear the same passage on both"))
            self.ab_group.addButton(b)
            b.setProperty("slot", slot)
            cl.addWidget(b)
        self.ab_group.buttons()[0].setChecked(True)
        self.ab_group.buttonClicked.connect(lambda b: self.player.set_slot(b.property("slot")))
        cl.addSpacing(14)
        self.match = QCheckBox(tr("Match loudness (recommended)"))
        self.match.setChecked(True)
        self.match.toggled.connect(lambda _: self._ab_gains())
        cl.addWidget(self.match)
        self.gain_lbl = lbl("", "muted")
        cl.addWidget(self.gain_lbl)
        cl.addStretch(1)
        v.addWidget(ctl)
        self.ab_scroll = QScrollArea()
        self.ab_scroll.setWidgetResizable(True)
        v.addWidget(self.ab_scroll, 4)
        return w

    # ── files ──
    def _pick(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("Choose tracks"), str(Path.home() / "Downloads"),
            tr("Audio") + " (" + " ".join(f"*.{e}" for e in sorted(E.AUDIO_EXT)) + ");;" + tr("All files") + " (*)")
        self._add([Path(f) for f in files])

    def _add(self, paths, select=True):
        first = None
        for p in paths:
            files = ([p] if p.is_file() else
                     sorted(x for x in p.rglob("*") if x.suffix.lower().lstrip(".") in E.AUDIO_EXT) if p.is_dir() else [])
            for f in files:
                key = str(f)
                if key in self.items:
                    first = first or self.items[key]
                    continue
                it = QListWidgetItem(QPixmap(dot_icon(BORDER)), self._label(key))
                it.setData(Qt.UserRole, key)
                it.setToolTip(tr("Analyzing…"))
                self.list.addItem(it)
                self.items[key] = it
                first = first or it
                self.pool.start(Job(key, self.bus))
        if first and select:
            self.list.setCurrentItem(first)
        self._refresh_combos()

    def _label(self, key):
        return ("★ " if key in self.refs else "") + Path(key).stem

    def _done(self, key, r):
        self.results[key] = r
        q = r["quality"]
        it = self.items.get(key)
        if it:
            it.setIcon(QPixmap(dot_icon(LEVEL_COLOR[q["level"]])))
            it.setToolTip(f"{Path(key).name}\n" + tr("Quality: {grade}", grade=q["grade"]))
        if key == self.current:
            self._show(key)
        if key in self.ab.values():
            self._render_compare()
        self._refresh_combos()

    def _failed(self, key, err):
        self.results[key] = {"error": err}
        it = self.items.get(key)
        if it:
            it.setIcon(QPixmap(dot_icon("#5A5F69")))
            it.setToolTip(err)
        if key == self.current:
            self._show(key)

    # ── detail view ──
    def _select(self, key):
        if self.cmp_btn.isChecked():
            self.combo["A"].setCurrentIndex(max(0, self.combo["A"].findData(key)))
            return
        self._show(key)

    def _show(self, key):
        if key != self.current:
            self.player.stop()
            self.player.unload("B")
            self.player.slot = "A"
        self.current = key
        r = self.results.get(key)
        if r is None:
            self.msg.setText(tr("Analyzing {name}…", name=f"<span style='color:{ACCENT}'>{Path(key).name}</span>"))
            return self.stack.setCurrentIndex(2)
        if "error" in r:
            self.msg.setText(tr("Couldn't analyze this file:") + f"<br><span style='color:{MUTED};font-size:13px'>{r['error']}</span>")
            return self.stack.setCurrentIndex(2)
        self.stack.setCurrentIndex(1)
        if self.player.tracks.get("A") is None or self.player.tracks["A"].path != key:
            self.player.load("A", key, r["info"])
        self.fname.setText(Path(key).name)
        self.fname.setToolTip(key)
        self.ref_btn.setChecked(key in self.refs)
        self.ref_btn.setIcon(icon("star_fill" if key in self.refs else "star", TEXT, ACCENT))
        q = r["quality"]
        clear(self.verdict_box)
        self.verdict_box.addWidget(lbl(tr("QUALITY"), "h"))
        self.verdict_box.addWidget(pill(q["grade"], q["level"]))
        clear(self.meta)
        i = r["info"]
        for t in (i["codec"].upper(), f"{i['bitrate']:.0f} kbps", f"{i['sr'] / 1000:g} kHz",
                  f"{i['bits']}-bit" if i["bits"] and i["codec"] in E.LOSSLESS else None,
                  tr("mono") if r["mono"] else tr("stereo"), mmss(r["duration"]),
                  f"{r['I']:.1f} LUFS" if r["I"] is not None else None):
            if t:
                self.meta.addWidget(lbl(t, "chip"))
        self.meta.addStretch(1)
        self.view.reset(r["duration"])
        self.spec.set_data(r)
        self.curve.set_data(r)
        self.scope.set_static(r["scope"], None if r["mono"] else r["corr"])

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 8, 8)
        v.setSpacing(10)
        for title, lvl_, text in q["flags"]:
            v.addWidget(card(tr("ALERT"), title, lvl_, tr("Attention") if lvl_ in (WARN, BAD) else tr("Note"), text))
        for it in q["items"]:
            v.addWidget(card(it["title"].upper(), it["value"], it["level"], it["pill"], it["text"], it["learn"]))
        v.addStretch(1)
        self.scrolls[0].setWidget(w)

        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        v2.setContentsMargins(0, 0, 8, 8)
        v2.setSpacing(10)
        if q["level"] in (BAD, WARN) and r["bw"]["eff"] < 17500:
            v2.addWidget(card(tr("CONTEXT"), tr("This file has limited quality"), WARN, tr("Heads-up"),
                              tr("What follows describes this file. Some of the brightness was lost to compression, so "
                                 "the original master may sound different.")))
        v2.addLayout(self._grid(r["mix"]))
        if r["bands"]:
            v2.addWidget(self._bands_card(r["bands"]))
        v2.addStretch(1)
        self.scrolls[1].setWidget(w2)

        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        v3.setContentsMargins(0, 0, 8, 8)
        v3.setSpacing(10)
        for it in r["stereo"]:
            v3.addWidget(card(it["title"].upper(), it["value"], it["level"], it["pill"], it["text"], it["learn"]))
        v3.addWidget(lbl("💡 " + tr("Press ▶: the green dots show what's playing right now, over the blue cloud of the whole track."),
                         "learn", wrap=True))
        v3.addStretch(1)
        self.stereo_scroll.setWidget(w3)

    def _grid(self, items):
        grid = QHBoxLayout()
        grid.setSpacing(10)
        cols = (QVBoxLayout(), QVBoxLayout())
        for k, it in enumerate(items):
            cols[k % 2].setSpacing(10)
            cols[k % 2].addWidget(card(it["title"].upper(), it["value"], it["level"], it["pill"], it["text"], it["learn"]))
        for c in cols:
            c.addStretch(1)
            grid.addLayout(c, 1)
        return grid

    def _bands_card(self, bands, other=None, names=("A", "B")):
        bc = QFrame()
        bc.setObjectName("card")
        bl = QVBoxLayout(bc)
        bl.setContentsMargins(18, 14, 18, 16)
        bl.setSpacing(8)
        hl = QHBoxLayout()
        hl.addWidget(lbl(tr("TONAL BALANCE"), "cardTitle"))
        hl.addStretch(1)
        hl.addWidget(pill(tr("energy per octave, vs. the average"), INFO))
        bl.addLayout(hl)
        bl.addWidget(BandBars(bands, other, names))
        if other is None:
            hi = max(bands, key=lambda b: b["rel"])
            lo = min(bands, key=lambda b: b["rel"])
            bl.addWidget(lbl(tr("Pushing hardest: <b>{name}</b> ({db} dB) — {desc}", name=tr(hi["name"]),
                                db=f"{hi['rel']:+.1f}", desc=tr(hi["desc"])) + "<br><br>"
                             + tr("Most restrained: <b>{name}</b> ({db} dB) — {desc}", name=tr(lo["name"]),
                                  db=f"{lo['rel']:+.1f}", desc=tr(lo["desc"])), "body", wrap=True))
            bl.addWidget(lbl("💡 " + tr("Almost all music carries more energy in the lows than in the highs; the "
                                        "interesting part is comparing tracks against each other (A/B mode)."),
                             "learn", wrap=True))
        else:
            diffs = sorted(((b2["rel"] - b1["rel"], b1["name"], b1["desc"]) for b1, b2 in zip(bands, other)),
                           key=lambda d: -abs(d[0]))
            d, name, desc = diffs[0]
            who = names[1] if d > 0 else names[0]
            bl.addWidget(lbl(tr("The biggest difference is in <b>{band}</b>: <b>{who}</b> has {db} dB more.", band=tr(name),
                                who=who, db=f"{abs(d):.1f}") + " " + tr(desc),
                             "body", wrap=True))
        return bc

    def _set_scale(self, b):
        k = b.property("key")
        self.cfg.setValue("scale", k)
        self.spec.set_scale(k)
        for sp in self.ab_specs.values():
            sp.set_scale(k)

    # ── playback ──
    def _seek(self, t):
        self.player.seek(t)
        if not self.player.playing:
            self.player.play()

    def _on_tick(self, t):
        if self.stack.currentIndex() == 1:
            self.spec.playhead = t
            self.curve.playhead = t
            if self.player.playing:
                self.view.follow(t)
            self.spec.update()
            self.curve.update()
            if self.player.playing and self.player.buf is not None and self.pages.currentIndex() == 2:
                trk = self.player.tracks.get(self.player.slot)
                i = int(t * trk.sr)
                seg = self.player.buf[max(0, i - 2048) * 2:(i + 2048) * 2].reshape(-1, 2)
                self.scope.set_live(seg[::2] if len(seg) else None)
            elif not self.player.playing and self.scope.live is not None:
                self.scope.set_live(None)
        elif self.stack.currentIndex() == 3:
            for slot, sp in self.ab_specs.items():
                sp.playhead = t if slot == self.player.slot else None
                sp.update()

    # ── references ──
    def _set_ref(self, key, on):
        if not key:
            return
        if on and key not in self.refs:
            self.refs.append(key)
        elif not on and key in self.refs:
            self.refs.remove(key)
        self.cfg.setValue("refs", self.refs)
        if key in self.items:
            self.items[key].setText(self._label(key))
        if key == self.current:
            self.ref_btn.setChecked(on)
            self.ref_btn.setIcon(icon("star_fill" if on else "star", TEXT, ACCENT))
        self._refresh_combos()

    def _context(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        key = it.data(Qt.UserRole)
        m = QMenu(self)
        is_ref = key in self.refs
        a1 = m.addAction(tr("Remove from references") if is_ref else "★ " + tr("Pin as reference"))
        a2 = m.addAction(tr("Compare with the open track")) if self.current and self.current != key else None
        a3 = m.addAction(tr("Remove from list"))
        act = m.exec(QCursor.pos())
        if act == a1:
            self._set_ref(key, not is_ref)
        elif a2 and act == a2:
            self._open_compare(self.current, key)
        elif act == a3:
            if key == self.current:
                self.player.stop()
                self.current = None
                self.stack.setCurrentIndex(0)
            self.list.takeItem(self.list.row(it))
            self.items.pop(key, None)
            self.results.pop(key, None)
            self._refresh_combos()

    # ── compare ──
    def _refresh_combos(self):
        keys = [k for k in self.items if "error" not in self.results.get(k, {})]
        keys.sort(key=lambda k: (k not in self.refs, Path(k).stem.lower()))
        for slot, cb in self.combo.items():
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            for k in keys:
                cb.addItem(self._label(k), k)
            i = cb.findData(cur)
            cb.setCurrentIndex(i if i >= 0 else -1)
            cb.blockSignals(False)

    def _toggle_compare(self, on):
        if on:
            a = self.current or (next(iter(self.items)) if self.items else None)
            b = next((r for r in self.refs if r != a), None) or next((k for k in self.items if k != a), None)
            if not a or not b:
                self.cmp_btn.setChecked(False)
                QMessageBox.information(self, APP, tr("Load at least two tracks to compare."))
                return
            self._open_compare(a, b)
        else:
            self.player.stop()
            self.player.unload("B")
            self.player.slot = "A"
            self.ab = {"A": None, "B": None}
            if self.current:
                self.player.tracks.pop("A", None)
                self._show(self.current)
            else:
                self.stack.setCurrentIndex(0)

    def _open_compare(self, a, b):
        self.cmp_btn.blockSignals(True)
        self.cmp_btn.setChecked(True)
        self.cmp_btn.blockSignals(False)
        self.player.stop()
        self.player.slot = "A"
        self.player.set_mode("normal")
        self.ab = {"A": None, "B": None}
        self.stack.setCurrentIndex(3)
        self._refresh_combos()
        for slot, key in (("A", a), ("B", b)):
            self.combo[slot].blockSignals(True)
            self.combo[slot].setCurrentIndex(self.combo[slot].findData(key))
            self.combo[slot].blockSignals(False)
        self._ab_pick("A")
        self._ab_pick("B")

    def _ab_pick(self, slot):
        key = self.combo[slot].currentData()
        if not key or self.ab.get(slot) == key:
            return
        self.ab[slot] = key
        r = self.results.get(key)
        if r and "error" not in r:
            self.player.load(slot, key, r["info"])
        self._ab_gains()
        self._render_compare()

    def _ab_swap(self):
        a, b = self.ab["A"], self.ab["B"]
        if a and b:
            self._open_compare(b, a)

    def _ab_flip(self):
        if self.stack.currentIndex() != 3:
            return
        nxt = "B" if self.player.slot == "A" else "A"
        for b in self.ab_group.buttons():
            b.setChecked(b.property("slot") == nxt)
        self.player.set_slot(nxt)

    def _ab_gains(self):
        ra, rb = self.results.get(self.ab["A"] or ""), self.results.get(self.ab["B"] or "")
        if not ra or not rb or ra.get("I") is None or rb.get("I") is None:
            self.gain_lbl.setText("")
            return
        if self.match.isChecked():
            target = min(ra["I"], rb["I"])          # only the louder one is turned down: never clips
            ga, gb = target - ra["I"], target - rb["I"]
        else:
            ga = gb = 0.0
        self.player.set_gain("A", ga)
        self.player.set_gain("B", gb)
        self.gain_lbl.setText(f"A {ga:+.1f} dB · B {gb:+.1f} dB" if self.match.isChecked() else
                              tr("Not matched: the louder one will seem better"))

    def _render_compare(self):
        ra, rb = (self.results.get(self.ab[s] or "") for s in ("A", "B"))
        for slot, r in (("A", ra), ("B", rb)):
            if r and "error" not in r:
                self.ab_views[slot].reset(r["duration"])
                self.ab_specs[slot].set_scale(self.cfg.value("scale", "lin"))
                self.ab_specs[slot].set_data(r)
        if not (ra and rb and "error" not in ra and "error" not in rb):
            return
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 8, 8)
        v.setSpacing(10)
        tbl = QFrame()
        tbl.setObjectName("card")
        g = QGridLayout(tbl)
        g.setContentsMargins(18, 14, 18, 14)
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(8)
        na, nb = Path(self.ab["A"]).stem, Path(self.ab["B"]).stem
        for c, (t, col) in enumerate((("", MUTED), (f"A · {na}", ACCENT), (f"B · {nb}", BLUE), (tr("What it means"), MUTED))):
            h = lbl(t, "cardTitle")
            h.setStyleSheet(f"color:{col}; font-weight:700;")
            h.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            g.addWidget(h, 0, c)

        def fmt(v, unit, d=1):
            return "—" if v is None else f"{v:.{d}f} {unit}"
        plr = lambda r: (r["TP"] - r["I"]) if r["I"] is not None and r["TP"] is not None else None  # noqa: E731
        rows = [
            (tr("Quality"), ra["quality"]["grade"], rb["quality"]["grade"], tr("How much real information the file holds.")),
            (tr("Frequency ceiling"), fmt(ra["bw"]["eff"] / 1000, "kHz"), fmt(rb["bw"]["eff"] / 1000, "kHz"),
             tr("Higher = more top end preserved.")),
            ("Loudness", fmt(ra["I"], "LUFS"), fmt(rb["I"], "LUFS"), tr("Closer to 0 = louder master.")),
            ("True peak", fmt(ra["TP"], "dBTP"), fmt(rb["TP"], "dBTP"), tr("Above -1 = no headroom.")),
            (tr("Punch (PLR)"), fmt(plr(ra), "dB"), fmt(plr(rb), "dB"), tr("Higher = livelier hits, less squashed.")),
            (tr("Range (LRA)"), fmt(ra["LRA"], "LU"), fmt(rb["LRA"], "LU"), tr("How much the level varies between sections.")),
            (tr("Correlation"), tr("mono") if ra["mono"] else f"{ra['corr']:+.2f}",
             tr("mono") if rb["mono"] else f"{rb['corr']:+.2f}", tr("Lower = wider stereo image.")),
        ]
        for i, (name, a, b, mean) in enumerate(rows, 1):
            g.addWidget(lbl(f"<b>{name}</b>", "body"), i, 0)
            g.addWidget(lbl(a, "body"), i, 1)
            g.addWidget(lbl(b, "body"), i, 2)
            m = lbl(mean, "learn", wrap=True)
            g.addWidget(m, i, 3)
        g.setColumnStretch(1, 2)
        g.setColumnStretch(2, 2)
        g.setColumnStretch(3, 3)
        v.addWidget(tbl)
        if ra["bands"] and rb["bands"] and len(ra["bands"]) == len(rb["bands"]):
            v.addWidget(self._bands_card(ra["bands"], rb["bands"], ("A", "B")))
        v.addWidget(lbl("💡 " + tr("With 'Match loudness' on, toggle with <b>Tab</b> on the same passage. If, at equal "
                                   "loudness, you prefer the one that seemed weaker before, you've just discovered the "
                                   "loudness war."),
                        "learn", wrap=True))
        v.addStretch(1)
        self.ab_scroll.setWidget(w)

    # ── report and sorting ──
    def _sort(self):
        def key(k):
            r = self.results.get(k)
            if not r or "error" in r:
                return (9, 0)
            return (E.LEVEL_RANK[r["quality"]["level"]], r["bw"]["eff"])
        keys = sorted(self.items, key=key)
        cur = self.current
        self.list.blockSignals(True)
        for k in keys:
            it = self.items[k]
            self.list.takeItem(self.list.row(it))
            self.list.addItem(it)
        if cur in self.items:
            self.list.setCurrentItem(self.items[cur])
        self.list.blockSignals(False)

    def _export(self):
        done = {k: r for k, r in self.results.items() if "error" not in r}
        if not done:
            QMessageBox.information(self, APP, tr("No files analyzed yet."))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Save report"), str(Path.home() / "Downloads" / "oido_report.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        cols = [tr("File"), tr("Folder"), tr("Quality"), tr("Alerts"), tr("Format"), "kbps", "kHz", tr("Ceiling kHz"),
                tr("Wall"), tr("Flashes kHz"), "LUFS", "True peak dBTP", "PLR dB", "LRA LU", tr("Correlation"),
                tr("Duration")]
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            sep = "," if i18n.current() == "en" else ";"   # Excel in es/ru locales expects ';' and decimal commas
            wr = csv.writer(fh, delimiter=sep)
            wr.writerow(cols)
            for k, r in done.items():
                i, bw, q = r["info"], r["bw"], r["quality"]
                num = lambda v, d=1: "" if v is None else (f"{v:.{d}f}" if sep == "," else f"{v:.{d}f}".replace(".", ","))  # noqa: E731
                wr.writerow([Path(k).name, str(Path(k).parent), q["grade"], " | ".join(f[0] for f in q["flags"]),
                             i["codec"].upper(), f"{i['bitrate']:.0f}", num(i['sr'] / 1000, 1),
                             num(bw["eff"] / 1000), tr("yes") if bw["wall"] else tr("no"),
                             num(bw["sporadic"] / 1000) if bw["sporadic"] else "", num(r["I"]), num(r["TP"]),
                             num(r["TP"] - r["I"]) if r["I"] is not None and r["TP"] is not None else "",
                             num(r["LRA"]), "" if r["mono"] else num(r["corr"], 2), mmss(r["duration"])])
        QMessageBox.information(self, APP, tr("Report saved:") + f"\n{path}")

    # ── language ──
    def _change_lang(self, _):
        code = self.lang_box.currentData()
        if code == i18n.current():
            return
        self.cfg.setValue("lang", code)
        i18n.setup(locales.CATALOGS, code)
        r = QMessageBox.question(self, APP, tr("Restart Oído now to switch the language?"))
        if r == QMessageBox.Yes:
            restart_app([k for k in self.items])

    # ── drag & drop ──
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop.setProperty("hot", "true")
            self.drop.style().polish(self.drop)

    def dragLeaveEvent(self, _):
        self.drop.setProperty("hot", "false")
        self.drop.style().polish(self.drop)

    def dropEvent(self, e):
        self.dragLeaveEvent(e)
        self._add([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    def closeEvent(self, e):
        self.player.stop()
        e.accept()


# ──────────────────────────────────────────────────────────────────────────────
#  Single instance: if Oído is already open, hand it the files and exit
# ──────────────────────────────────────────────────────────────────────────────
_IPC = {"server": None}


def restart_app(paths=()):
    """Relaunch the app (used to switch language), reopening the loaded files."""
    if _IPC["server"]:
        _IPC["server"].close()   # otherwise the new instance would hand its files to this one and exit
    if getattr(sys, "frozen", False):
        prog, args = sys.executable, list(paths)
    else:
        prog, args = sys.executable, [str(Path(__file__).resolve()), *paths]
    QProcess.startDetached(prog, args)
    QApplication.quit()


def send_to_running(paths) -> bool:
    s = QLocalSocket()
    s.connectToServer(IPC_NAME)
    if not s.waitForConnected(300):
        return False
    s.write("\n".join(str(Path(p).resolve()) for p in paths).encode("utf-8"))
    s.flush()
    s.waitForBytesWritten(1000)
    s.disconnectFromServer()
    return True


def selftest(report: str) -> int:
    """Self-test used by the build: generates audio with FFmpeg, analyzes it and opens the window."""
    import tempfile
    import time
    lines, ok = [], True
    try:
        d = Path(tempfile.mkdtemp())
        wav, mp3 = d / "t.wav", d / "t.mp3"
        import subprocess as sp
        for cmd in ([E.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=8:c=pink:a=0.3", "-ac", "2", str(wav)],
                    [E.FFMPEG, "-v", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)]):
            sp.run(cmd, check=True, creationflags=E.NO_WINDOW)
        rw, rm = E.analyze(wav), E.analyze(mp3)
        lines.append(f"ffmpeg={E.FFMPEG}")
        lines.append(f"wav wall={rw['bw']['wall']} eff={rw['bw']['eff']:.0f} I={rw['I']}")
        lines.append(f"mp3 wall={rm['bw']['wall']} eff={rm['bw']['eff']:.0f} grade={E.quality_report(rm)['grade']}")
        ok &= rw["bw"]["wall"] is None and rm["bw"]["wall"] is not None and rm["bw"]["eff"] < 18500 and rw["I"] is not None
        app = QApplication.instance()
        w = Oido(isolated=True)
        w.show()
        w._add([wav, mp3])
        keys = [str(wav), str(mp3)]
        t = time.time()
        while not all(k in w.results for k in keys) and time.time() - t < 120:
            app.processEvents()
            time.sleep(0.05)
        good = [k for k in keys if "error" not in w.results.get(k, {"error": 1})]
        ok &= len(good) == 2
        lines.append(f"ui analyzed={len(good)}/2")
        w.pool.waitForDone(30000)
        w.ppool.waitForDone(30000)
        app.processEvents()
        w.close()
    except Exception as e:  # noqa: BLE001
        ok = False
        lines.append(f"ERROR {e!r}")
    lines.append("SELFTEST " + ("OK" if ok else "FAIL"))
    Path(report).write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def main():
    RT.set_windows_app_id("GermanRobert.Oido")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(RT.app_icon("oido"))
    family = RT.load_fonts()
    i18n.setup(locales.CATALOGS, QSettings("GermanRobert", APP).value("lang", None))
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    f = QFont(family)
    f.setPointSizeF(9.5)
    app.setFont(f)
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        os.environ["OIDO_NO_AUDIO"] = "1"
        return selftest(sys.argv[2])
    args = [a for a in sys.argv[1:] if Path(a).exists()]
    if send_to_running(args or []):
        return 0
    if not (E.FFMPEG and E.FFPROBE):
        QMessageBox.critical(None, APP, tr("FFmpeg not found.\n\nReinstall Oído or, if you're running from source, "
                                           "install FFmpeg with:\n    winget install Gyan.FFmpeg"))
        return 1
    w = Oido()
    w.setWindowTitle(f"{APP} {__version__}")
    server = QLocalServer()
    QLocalServer.removeServer(IPC_NAME)
    server.listen(IPC_NAME)
    _IPC["server"] = server

    def incoming():
        c = server.nextPendingConnection()

        def read():
            data = bytes(c.readAll()).decode("utf-8", "replace")
            ps = [Path(x) for x in data.splitlines() if x.strip()]
            if ps:
                w._add(ps)
            w.setWindowState(w.windowState() & ~Qt.WindowMinimized)
            w.raise_()
            w.activateWindow()
        c.readyRead.connect(read)
    server.newConnection.connect(incoming)
    w.show()
    if args:
        w._add([Path(a) for a in args])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

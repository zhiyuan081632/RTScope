#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scope_view.py — RTScope 主窗口 (Adobe Audition 风格)

界面构成
--------
- 顶部单行设置栏 (字体加大): 声卡 / 通道 / 采样率 / 块长 / 窗口 / 算法 / 增益(dB) / [显示源切换]。
  启动只进面板, 不自动录音; 录制/播放中锁定这些设置。
- 中央: 单通道波形轨 —— 黑底 + 浅绿色 min/max 包络。
  * 录制态: 短窗口, 时间轴左(旧)→右(新), 最新在右缘平滑左滚 (类 Audition 录制)。
  * 编辑态: 整段录音自适应铺满, 绝对时间标尺, 播放头竖线, 鼠标点击定位。
- 右侧: 竖直 RMS 标尺 (绿→黄→红渐变 + dB 刻度 + 峰值保持)。
- 底部走带条 (Audition 式, 居中): ● 录音 / ▶ 播放 / ■ 停止。
- 最后一行状态栏显示运行/编辑信息; 停止录音后在状态栏显示保存路径。

显示源 (热切换按钮): 'proc'=算法波束输出, 'raw'=直通 mic0 (已经前置增益放大)。
录制中算法处理器始终运行、proc.wav 始终录所选算法, 切换只改「显示/回放」的源,
保证算法持续收敛 (符合"切到直通时原算法仍在跑, 只是显示了直通的")。
前置增益 (gain_spin, dB, 默认 20): 仅麦克风通道放大 (ref 通道不变) 再送算法/直通显示, 并额外录 gain.wav;
raw.wav 保留未加增益的采集原貌。增益仅录音开始前可设置 (录制中锁定)。
"""

import math
import os
import queue
import subprocess

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from playback import Player


# ---- Audition 风格配色 (黑底浅绿) -------------------------------------------
BG_TRACK = (10, 10, 10)         # 波形轨近黑底
WAVE_GREEN = (140, 232, 140)    # 浅绿波形填充
CLIP_RED = (255, 92, 92)        # 削波亮红
CENTER_LINE = (60, 118, 72)     # 0 中线 (暗绿)
PLAYHEAD = (240, 200, 90)       # 编辑态播放头 (暖黄)
RULER_BG = "#141414"
METER_W = 80                    # 右侧 RMS 标尺宽度(px)
DB_RANGE = 60.0                 # 电平表动态范围 dB (-60..0)
WINDOWS = [2.0, 5.0, 10.0, 30.0, 60.0]
DEFAULT_WINDOW = 10.0
RATES = ["16000", "48000", "44100", "8000"]
BLOCKS = ["128", "256", "512", "1024"]
MAX_FULL_SEC = 30 * 60          # 编辑态全量缓冲上限 (30 分钟), 超限丢弃最早块
FONT_FAMILY = '"Microsoft YaHei UI","Segoe UI",sans-serif'

# 模式
MODE_IDLE = "idle"
MODE_REC = "rec"
MODE_EDIT = "edit"
MODE_PLAY = "play"


def _to_db(x):
    return 20.0 * math.log10(x) if x > 1e-6 else -float("inf")


def _envelope(data, cols):
    """把 1D 样本按 cols 个像素列聚合出 (min, max) 包络。"""
    n = data.shape[0]
    if n == 0 or cols < 2:
        z = np.zeros(max(cols, 1), dtype=np.float32)
        return z, z.copy()
    idx = np.linspace(0, n, cols, endpoint=False).astype(np.int64)
    np.clip(idx, 0, n - 1, out=idx)
    mins = np.minimum.reduceat(data, idx).astype(np.float32)
    maxs = np.maximum.reduceat(data, idx).astype(np.float32)
    return mins, maxs


# ----------------------------------------------------------------------------
# 波形轨 (黑底浅绿): live 短窗滚动 / editor 整段铺满 + 播放头 + 点击定位
# ----------------------------------------------------------------------------
class WaveTrack(QtWidgets.QWidget):
    seek = QtCore.pyqtSignal(float)         # 编辑态点击 → 归一化位置 0..1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "live"                  # 'live' | 'editor'
        self.live_data = None               # 短窗滚动缓冲 (1D)
        self.full_data = None               # 编辑态整段 (1D)
        self.playhead_frac = 0.0            # 编辑态播放头 0..1
        self.setMinimumHeight(140)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self._cache_img = None              # 编辑态波形 QImage 缓存
        self._cache_key = None

    def set_mode(self, mode):
        if self.mode != mode:
            self.mode = mode
            self._cache_key = None
            self.update()

    def set_live(self, col):
        self.live_data = col
        self.update()

    def set_full(self, col):
        self.full_data = col
        self._cache_key = None
        self.update()

    def set_playhead(self, frac):
        self.playhead_frac = float(max(0.0, min(1.0, frac)))
        self.update()

    def resizeEvent(self, ev):
        self._cache_key = None              # 宽度变化 → 编辑态缓存失效
        super().resizeEvent(ev)

    def mousePressEvent(self, ev):
        if self.mode == "editor" and ev.button() == QtCore.Qt.LeftButton:
            w = max(1, self.width())
            self.set_playhead(ev.pos().x() / float(w))
            self.seek.emit(self.playhead_frac)

    # ---- 绘制 --------------------------------------------------------------
    def _bg(self, img):
        img[..., 0] = BG_TRACK[0]
        img[..., 1] = BG_TRACK[1]
        img[..., 2] = BG_TRACK[2]
        img[..., 3] = 255

    def _draw_wave_into(self, img, data, w, h):
        if data is None or data.size == 0:
            return
        mins, maxs = _envelope(data, w)
        mid = h / 2.0
        usable = h / 2.0 - 2.0
        ytop = np.clip(mid - maxs * usable, 0, h - 1).astype(np.int32)
        ybot = np.clip(mid - mins * usable, 0, h - 1).astype(np.int32)
        rows = np.arange(h)[:, None]
        mask = (rows >= ytop[None, :]) & (rows <= ybot[None, :])
        clipcol = (maxs >= 0.999) | (mins <= -0.999)
        red = mask & clipcol[None, :]
        green = mask & ~clipcol[None, :]
        img[..., 0][green] = WAVE_GREEN[0]
        img[..., 1][green] = WAVE_GREEN[1]
        img[..., 2][green] = WAVE_GREEN[2]
        img[..., 0][red] = CLIP_RED[0]
        img[..., 1][red] = CLIP_RED[1]
        img[..., 2][red] = CLIP_RED[2]

    def paintEvent(self, _ev):
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)

        if self.mode == "editor":
            key = (id(self.full_data),
                   0 if self.full_data is None else self.full_data.shape[0], w, h)
            if self._cache_img is None or self._cache_key != key:
                img = np.empty((h, w, 4), dtype=np.uint8)
                self._bg(img)
                self._draw_wave_into(img, self.full_data, w, h)
                self._cache_img = QtGui.QImage(
                    img.data, w, h, 4 * w, QtGui.QImage.Format_RGBA8888).copy()
                self._cache_key = key
            p.drawImage(0, 0, self._cache_img)
        else:
            img = np.empty((h, w, 4), dtype=np.uint8)
            self._bg(img)
            self._draw_wave_into(img, self.live_data, w, h)
            qimg = QtGui.QImage(img.data, w, h, 4 * w, QtGui.QImage.Format_RGBA8888)
            p.drawImage(0, 0, qimg)
            self._keepalive = img

        # 中线 + ±参考线
        pen = QtGui.QPen(QtGui.QColor(*CENTER_LINE, 200))
        pen.setStyle(QtCore.Qt.DashLine)
        p.setPen(pen)
        midy = int(h / 2)
        p.drawLine(0, midy, w, midy)
        # Audition 式多条横向参考线
        p.setPen(QtGui.QColor(40, 60, 44, 110))
        for frac in (0.125, 0.25, 0.375, 0.625, 0.75, 0.875):
            yy = int(h * frac)
            p.drawLine(0, yy, w, yy)

        # 编辑态播放头
        if self.mode == "editor":
            x = int(self.playhead_frac * (w - 1))
            p.setPen(QtGui.QPen(QtGui.QColor(*PLAYHEAD, 235), 1))
            p.drawLine(x, 0, x, h - 1)

        # 边框
        p.setPen(QtGui.QColor(48, 48, 48))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


# ----------------------------------------------------------------------------
# 时间标尺: live 相对时间(右缘=现在) / editor 绝对时间(0..duration)
# ----------------------------------------------------------------------------
class RulerWidget(QtWidgets.QWidget):
    def __init__(self, window_sec=DEFAULT_WINDOW, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.mode = "live"
        self.window_sec = float(window_sec)
        self.duration = 0.0
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def set_window(self, sec):
        self.window_sec = float(sec)
        self.update()

    def set_duration(self, sec):
        self.duration = float(sec)
        self.update()

    def _nice_step(self, span, w):
        for cand in (0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0):
            if (cand / span) * w >= 72:
                return cand
        return 60.0

    def paintEvent(self, _ev):
        w, h = self.width(), self.height()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(0, 0, w, h, QtGui.QColor(RULER_BG))
        font = p.font(); font.setPointSizeF(8.0); p.setFont(font)

        if self.mode == "editor" and self.duration > 0:
            span = self.duration
            step = self._nice_step(span, w)
            t = 0.0
            while t <= span + 1e-9:
                x = int(t / span * (w - 1))
                major = abs(t % (step * 2)) < 1e-9 or t == 0.0
                p.setPen(QtGui.QColor(120, 150, 120))
                p.drawLine(x, h - (12 if major else 6), x, h - 1)
                if major:
                    p.setPen(QtGui.QColor(195, 215, 195))
                    p.drawText(QtCore.QRect(x + 3, 0, 90, h - 12),
                                 QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "%.1fs" % t)
                t += step
        else:
            span = self.window_sec
            step = self._nice_step(span, w)
            t = -span
            while t <= 1e-9:
                x = int((t + span) / span * (w - 1))
                major = abs(t % (step * 2)) < 1e-9 or abs(t) < 1e-9
                p.setPen(QtGui.QColor(120, 150, 120))
                p.drawLine(x, h - (12 if major else 6), x, h - 1)
                if major:
                    p.setPen(QtGui.QColor(195, 215, 195))
                    label = "0" if abs(t) < 1e-9 else ("%.1fs" % t)
                    p.drawText(QtCore.QRect(x + 3, 0, 90, h - 12),
                                 QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label)
                t += step

        p.setPen(QtGui.QColor(58, 58, 58))
        p.drawLine(0, h - 1, w, h - 1)
        p.end()


# ----------------------------------------------------------------------------
# 右侧竖直 RMS 标尺
# ----------------------------------------------------------------------------
class RmsMeter(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(METER_W)
        self.setMinimumHeight(140)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                           QtWidgets.QSizePolicy.Expanding)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)
        self.rms = 0.0
        self.hold = 0.0

    def set_levels(self, rms, peak):
        self.rms = float(rms)
        self.hold = max(float(peak), self.hold * 0.90)
        self.update()

    def decay(self):
        self.hold *= 0.90
        self.rms *= 0.90
        self.update()

    def _frac(self, x):
        d = _to_db(x)
        if d == -float("inf"):
            return 0.0
        return max(0.0, min(1.0, (d + DB_RANGE) / DB_RANGE))

    def _y(self, frac, h, top, bot):
        return int(bot - frac * (bot - top))

    def paintEvent(self, _ev):
        w, h = self.width(), self.height()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(0, 0, w, h, QtGui.QColor("#101010"))
        top, bot = 10, h - 40
        bar_x, bar_w = 44, 18
        # Audition 式多条横向参考线 (贯穿标尺, 柱体之下)
        for db in (0, -6, -12, -24, -36, -48, -60):
            yy = self._y((db + DB_RANGE) / DB_RANGE, h, top, bot)
            p.setPen(QtGui.QColor(38, 48, 40))
            p.drawLine(0, yy, w, yy)
        p.fillRect(bar_x, top, bar_w, bot - top, QtGui.QColor(30, 30, 30))
        rf = self._frac(self.rms)
        if rf > 0:
            grad = QtGui.QLinearGradient(0, bot, 0, top)
            grad.setColorAt(0.0, QtGui.QColor(60, 200, 90))
            grad.setColorAt(0.65, QtGui.QColor(225, 200, 60))
            grad.setColorAt(1.0, QtGui.QColor(225, 70, 60))
            yy = self._y(rf, h, top, bot)
            p.fillRect(bar_x, yy, bar_w, bot - yy, QtGui.QBrush(grad))
        py = self._y(self._frac(self.hold), h, top, bot)
        p.setPen(QtGui.QPen(QtGui.QColor(235, 235, 235)))
        p.drawLine(bar_x - 2, py, bar_x + bar_w + 2, py)
        font = p.font(); font.setPointSizeF(7.0); p.setFont(font)
        for db in (0, -6, -12, -24, -36, -48, -60):
            frac = (db + DB_RANGE) / DB_RANGE
            yy = self._y(frac, h, top, bot)
            p.setPen(QtGui.QColor(130, 150, 130))
            p.drawLine(bar_x + bar_w + 3, yy, bar_x + bar_w + 7, yy)
            p.setPen(QtGui.QColor(165, 185, 165))
            p.drawText(QtCore.QRect(2, yy - 9, bar_x - 8, 18),
                       QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, "%d" % db)
        p.setPen(QtGui.QColor(58, 58, 58))
        p.drawRect(bar_x, top, bar_w, bot - top)
        p.setPen(QtGui.QColor(150, 230, 150))
        font.setPointSizeF(8.0); p.setFont(font)
        rms_db = _to_db(self.rms)
        p.drawText(QtCore.QRect(0, h - 22, w, 20), QtCore.Qt.AlignCenter,
                   "%.0f" % rms_db if rms_db != -float("inf") else "-inf")
        p.end()


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------
class ScopeWindow(QtWidgets.QMainWindow):
    def __init__(self, controller, window_sec=DEFAULT_WINDOW, fps=50, initial=None):
        super().__init__()
        self.controller = controller
        self.window_sec = float(window_sec)
        self.rate = 16000
        self.mode = MODE_IDLE
        self.disp_source = "proc"            # 'proc' 算法波束 | 'raw' 直通 mic0

        self.W = int(self.window_sec * self.rate)
        self.buf_proc = np.zeros(self.W, dtype=np.float32)
        self.buf_raw0 = np.zeros(self.W, dtype=np.float32)
        self._full_proc = []                 # 录制时累积的块 (list of 1D)
        self._full_raw0 = []
        self._full_n = 0
        self._live_n = 0                     # 录制态已填充帧数 (<W 时波形自左向右生长)
        self.full_proc = np.zeros(0, dtype=np.float32)
        self.full_raw0 = np.zeros(0, dtype=np.float32)

        self.player = Player(samplerate=self.rate)

        self.setWindowTitle("RTScope")
        self._apply_default_geometry()
        self.setStyleSheet(self._qss())

        self._build_panel()
        self._build_central()
        self._apply_initial(initial or {})
        self.track.seek.connect(self._on_seek)
        self._set_mode(MODE_IDLE)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._refresh)
        self.timer.start(int(1000 / fps))

    # ---- 外观 --------------------------------------------------------------
    @staticmethod
    def _qss():
        return (
            "* { font-family: %s; }"
            "QMainWindow, QWidget#central { background:#161616; }"
            "QWidget#panel { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            " stop:0 #2a2a2a, stop:1 #1d1d1d); border-bottom:1px solid #0c0c0c; }"
            "QLabel { color:#cfcfcf; background:transparent; font-size:11pt; }"
            "QLabel#cap { color:#9aa79a; font-size:10pt; }"
            "QComboBox, QSpinBox, QDoubleSpinBox { background:#333333; color:#eaeaea; font-size:11pt;"
            " border:1px solid #4d4d4d; padding:3px 8px; border-radius:4px;"
            " min-height:22px; }"
            "QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color:#6a8f6a; }"
            "QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#7a7a7a; background:#262626; }"
            "QComboBox QAbstractItemView { background:#2f2f2f; color:#eaeaea;"
            " font-size:11pt; selection-background-color:#3a5a3a; }"
            "QPushButton { background:#333333; color:#eaeaea; border:1px solid #4d4d4d;"
            " padding:5px 16px; border-radius:4px; font-size:11pt; font-weight:bold; }"
            "QPushButton:hover:!disabled { background:#3d3d3d; border-color:#6a8f6a; }"
            "QPushButton:pressed:!disabled { background:#2a2a2a; }"
            "QPushButton:disabled { color:#6f6f6f; background:#252525; border-color:#3a3a3a; }"
            "QPushButton#recBtn { color:#ff8080; }"
            "QPushButton#recBtn:checked { background:#5a2020; color:#ff9b9b; }"
            "QPushButton#playBtn { color:#8ce88c; }"
            "QPushButton#stopBtn { color:#d0d0d0; }"
            "QPushButton#srcBtn { color:#9fd0ff; }"
            "QPushButton#srcBtn:checked { background:#20384f; color:#bfe0ff; }"
            "QLabel#saveLink { color:#7fb2e5; font-size:10pt; }"
            "QLabel#saveLink a { color:#7fb2e5; text-decoration:underline; }"
            "QPushButton#recBtn, QPushButton#playBtn, QPushButton#stopBtn {"
            " font-size:13pt; padding:8px 30px; min-height:34px; border-radius:5px; }"
            % FONT_FAMILY
        )

    def _apply_default_geometry(self):
        w, h = 1440, 900
        try:
            screen = QtWidgets.QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                w = min(max(1280, int(avail.width() * 0.88)), avail.width())
                h = min(max(800, int(avail.height() * 0.88)), avail.height())
        except Exception:
            pass
        self.resize(w, h)
        try:
            screen = QtWidgets.QApplication.primaryScreen()
            if screen is not None:
                fg = self.frameGeometry()
                fg.moveCenter(screen.availableGeometry().center())
                self.move(fg.topLeft())
        except Exception:
            pass

    # ---- 顶部单行设置栏 ----------------------------------------------------
    def _build_panel(self):
        panel = QtWidgets.QWidget()
        panel.setObjectName("panel")
        row = QtWidgets.QHBoxLayout(panel)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(14)

        row.addWidget(self._cap("声卡"))
        self.device_combo = QtWidgets.QComboBox()
        self.device_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToContents)   # 完整显示声卡名
        self._reload_devices()
        row.addWidget(self.device_combo)

        row.addWidget(self._cap("通道"))
        self.channels_spin = QtWidgets.QSpinBox()
        self.channels_spin.setRange(1, 32)
        self.channels_spin.setValue(self.controller.hardware.channels)
        row.addWidget(self.channels_spin)

        row.addWidget(self._cap("采样率"))
        self.rate_combo = QtWidgets.QComboBox()
        self.rate_combo.addItems(RATES)
        self.rate_combo.setCurrentText("16000")
        self.rate_combo.setEditable(True)
        row.addWidget(self.rate_combo)

        row.addWidget(self._cap("块长"))
        self.block_combo = QtWidgets.QComboBox()
        self.block_combo.addItems(BLOCKS)
        self.block_combo.setCurrentText("256")
        row.addWidget(self.block_combo)

        row.addWidget(self._cap("窗口"))
        self.win_combo = QtWidgets.QComboBox()
        for s in WINDOWS:
            self.win_combo.addItem("%gs" % s, s)
        idx = WINDOWS.index(self.window_sec) if self.window_sec in WINDOWS else 1
        self.win_combo.setCurrentIndex(idx)
        self.win_combo.currentIndexChanged.connect(self._on_window)
        row.addWidget(self.win_combo)

        row.addWidget(self._cap("算法"))
        self.alg_combo = QtWidgets.QComboBox()
        names = self.controller.algorithm_names()
        if names:
            self.alg_combo.addItems(names)
            self.alg_combo.setCurrentIndex(0)
        else:
            self.alg_combo.addItem("(无可用算法)")
            self.alg_combo.setEnabled(False)
        row.addWidget(self.alg_combo)

        row.addWidget(self._cap("增益"))
        self.gain_spin = QtWidgets.QDoubleSpinBox()
        self.gain_spin.setRange(-20.0, 60.0)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSingleStep(1.0)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setValue(20.0)
        self.gain_spin.setToolTip(
            "数字前置增益: 仅麦克风通道按此放大 (参考信号通道不变), 再送算法处理 / 直通显示 / gain.wav 录音\n"
            "0 dB = 不放大; 例 10 dB ≈ ×3.16, 20 dB ≈ ×10 (默认)。仅录音开始前可设置, 录制中锁定")
        self.gain_spin.valueChanged.connect(self._on_gain)
        row.addWidget(self.gain_spin)

        self.src_lbl = QtWidgets.QLabel("显示：")
        self.src_lbl.setObjectName("cap")
        self.src_btn = QtWidgets.QPushButton("算法")
        self.src_btn.setObjectName("srcBtn")
        self.src_btn.setCheckable(True)
        self.src_btn.setChecked(False)
        self.src_btn.setToolTip("热切换显示/回放源: 算法波束 ↔ 直通 mic0 (算法始终在跑)")
        self.src_btn.clicked.connect(self._on_toggle_source)
        srcbox = QtWidgets.QHBoxLayout()
        srcbox.setContentsMargins(0, 0, 0, 0); srcbox.setSpacing(2)
        srcbox.addWidget(self.src_lbl)
        srcbox.addWidget(self.src_btn)
        row.addLayout(srcbox)

        row.addStretch(1)
        self.setMenuWidget(panel)

    @staticmethod
    def _cap(text):
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("cap")
        return lbl

    def _reload_devices(self):
        self.device_combo.clear()
        for idx, label in self.controller.input_devices():
            self.device_combo.addItem(label, idx)
        default_idx = self.controller.default_device()
        if default_idx is not None:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == default_idx:
                    self.device_combo.setCurrentIndex(i)
                    break

    # ---- 中央 + 底部走带条 -------------------------------------------------
    def _build_central(self):
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 8)
        outer.setSpacing(8)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(0)
        left = QtWidgets.QWidget(); left.setObjectName("central")
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(0)
        self.ruler = RulerWidget(self.window_sec)
        self.track = WaveTrack()
        lv.addWidget(self.ruler)
        lv.addWidget(self.track, 1)
        body.addWidget(left, 1)

        right = QtWidgets.QWidget(); right.setObjectName("central")
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0); rv.setSpacing(0)
        corner = QtWidgets.QWidget(); corner.setObjectName("central")
        corner.setFixedHeight(self.ruler.height())
        self.meter = RmsMeter()
        rv.addWidget(corner)
        rv.addWidget(self.meter, 1)
        body.addWidget(right)
        outer.addLayout(body, 1)

        # 底部走带条 (居中)
        transport = QtWidgets.QWidget(); transport.setObjectName("central")
        tr = QtWidgets.QHBoxLayout(transport)
        tr.setContentsMargins(2, 4, 2, 4); tr.setSpacing(16)
        self.rec_btn = QtWidgets.QPushButton("● 录音")
        self.rec_btn.setObjectName("recBtn")
        self.rec_btn.clicked.connect(self._on_start)
        self.play_btn = QtWidgets.QPushButton("▶ 播放")
        self.play_btn.setObjectName("playBtn")
        self.play_btn.clicked.connect(self._on_play)
        self.stop_btn = QtWidgets.QPushButton("■ 停止")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.clicked.connect(self._on_stop)
        tr.addStretch(1)
        tr.addWidget(self.rec_btn)
        tr.addWidget(self.play_btn)
        tr.addWidget(self.stop_btn)
        tr.addStretch(1)
        outer.addWidget(transport)

        self.status_lbl = QtWidgets.QLabel("待机 — 选择声卡/参数/算法后点「● 录音」")
        self.status_lbl.setObjectName("cap")
        self.save_link = QtWidgets.QLabel("")
        self.save_link.setObjectName("saveLink")
        self.save_link.setOpenExternalLinks(False)
        self.save_link.linkActivated.connect(self._open_cap_dir)
        self.save_link.hide()
        srow = QtWidgets.QHBoxLayout()
        srow.setContentsMargins(0, 0, 0, 0); srow.setSpacing(12)
        srow.addWidget(self.status_lbl)
        srow.addWidget(self.save_link)
        srow.addStretch(1)
        outer.addLayout(srow)
        self.setCentralWidget(central)

    # ---- 初值 / 控件状态 ---------------------------------------------------
    def _apply_initial(self, ini):
        if not ini:
            return
        if ini.get("device") is not None:
            for i in range(self.device_combo.count()):
                if self.device_combo.itemData(i) == ini["device"]:
                    self.device_combo.setCurrentIndex(i)
                    break
        if ini.get("channels"):
            self.channels_spin.setValue(int(ini["channels"]))
        if ini.get("rate"):
            self.rate_combo.setCurrentText(str(int(ini["rate"])))
        if ini.get("blocksize"):
            self.block_combo.setCurrentText(str(int(ini["blocksize"])))
        if ini.get("window"):
            sec = float(ini["window"])
            for i in range(self.win_combo.count()):
                if float(self.win_combo.itemData(i)) == sec:
                    self.win_combo.setCurrentIndex(i)
                    break
            self.window_sec = sec
            self._resize_buffer(sec)
            self.ruler.set_window(sec)
        if ini.get("algorithm"):
            j = self.alg_combo.findText(ini["algorithm"])
            if j >= 0:
                self.alg_combo.setCurrentIndex(j)
        if ini.get("gain_db") is not None:
            self.gain_spin.setValue(float(ini["gain_db"]))

    def _set_mode(self, mode):
        self.mode = mode
        settings_locked = mode in (MODE_REC, MODE_PLAY)
        for wgt in (self.device_combo, self.channels_spin, self.rate_combo,
                    self.block_combo, self.alg_combo, self.gain_spin):
            wgt.setEnabled(not settings_locked)
        self.win_combo.setEnabled(mode in (MODE_IDLE, MODE_REC))
        self.src_btn.setEnabled(mode != MODE_IDLE or True)   # 始终可切源对比
        have_data = self.full_proc.size or self.full_raw0.size
        self.rec_btn.setEnabled(mode in (MODE_IDLE, MODE_EDIT))
        self.play_btn.setEnabled(mode == MODE_EDIT and bool(have_data))
        self.stop_btn.setEnabled(mode in (MODE_REC, MODE_PLAY))
        self.rec_btn.setChecked(mode == MODE_REC)

    def _src_name(self):
        if self.disp_source == "raw":
            return "直通 mic0"
        alg = self.controller.algorithm or "算法"
        return "算法 %s" % alg

    # ---- 交互 --------------------------------------------------------------
    def _current_params(self):
        device = self.device_combo.currentData()
        try:
            rate = int(self.rate_combo.currentText())
        except ValueError:
            rate = 16000
        try:
            block = int(self.block_combo.currentText())
        except ValueError:
            block = 256
        algorithm = self.controller.default_algorithm()
        if self.alg_combo.isEnabled() and self.alg_combo.count():
            txt = self.alg_combo.currentText()
            if txt != "(无可用算法)":
                algorithm = txt
        return device, self.channels_spin.value(), rate, block, algorithm

    def _on_start(self):
        if self.mode in (MODE_REC, MODE_PLAY):
            return
        self.player.stop()
        device, channels, rate, block, algorithm = self._current_params()
        try:
            info = self.controller.start(device=device, channels=channels,
                                         rate=rate, blocksize=block,
                                         algorithm=algorithm,
                                         record=self.controller.record,
                                         capture_dir=self.controller.capture_dir,
                                         gain_db=self.gain_spin.value())
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "无法开始", str(e))
            print("[ui] 录音启动失败: %s" % e)
            return
        self.rate = info["rate"]
        self.player.samplerate = self.rate
        self._resize_buffer(self.window_sec)
        self.buf_proc[:] = 0
        self.buf_raw0[:] = 0
        self._live_n = 0
        # 填充期标尺=绝对 0..W (波形自左向右生长, 类 Audition); 填满后切回 live 滚动
        self.ruler.set_mode("editor")
        self.ruler.set_duration(self.window_sec)
        self.track.set_mode("live")
        # 重置全量缓冲
        self._full_proc = []; self._full_raw0 = []; self._full_n = 0
        self.full_proc = np.zeros(0, dtype=np.float32)
        self.full_raw0 = np.zeros(0, dtype=np.float32)
        self._set_mode(MODE_REC)
        print("[ui] 录音开始: 设备 %s | %dHz %dch block%d | 算法 %s | 增益 %+.1fdB | 录音目录 %s"
              % (info["device_name"], info["rate"], info["channels"],
                 info["blocksize"], info["algorithm"], self.gain_spin.value(),
                 info.get("cap_dir") or "(未录音)"))

    def _on_stop(self):
        if self.mode == MODE_REC:
            self.controller.stop()
            self._enter_editor()
            cap = self.controller.cap_dir
            print("[ui] 录音停止, 保存于 %s" % (cap or "(未录音)"))
        elif self.mode == MODE_PLAY:
            self.player.stop()
            self._set_mode(MODE_EDIT)
            print("[ui] 回放停止 @ %.2fs" % (self.player.position / float(self.rate)))
        self._update_status()

    def _on_play(self):
        if self.mode != MODE_EDIT:
            return
        data = self._current_full()
        if data.size == 0:
            return
        self.player.load(data, self.rate)
        start = int(self.track.playhead_frac * self.player.n_samples)
        if self.player.play(start):
            self._set_mode(MODE_PLAY)
            print("[ui] 回放开始: 源=%s 位置=%.2fs" %
                  (self.disp_source, start / float(self.rate)))

    def _on_seek(self, frac):
        if self.mode == MODE_PLAY:
            self.player.load(self._current_full(), self.rate)
            self.player.play(int(frac * self.player.n_samples))
        self._update_status()

    def _on_toggle_source(self):
        self.disp_source = "raw" if self.disp_source == "proc" else "proc"
        self.src_btn.setChecked(self.disp_source == "raw")
        self.src_btn.setText("直通" if self.disp_source == "raw" else "算法")
        print("[ui] 热切换显示/回放源 -> %s (算法处理器持续运行)" % self._src_name())
        if self.mode in (MODE_IDLE, MODE_REC):
            pass                                  # live 刷新时自动取对应缓冲
        else:
            self.track.set_full(self._current_full())
            if self.mode == MODE_PLAY:
                self.player.load(self._current_full(), self.rate)
                self.player.play(int(self.track.playhead_frac * self.player.n_samples))
        self._set_mode(self.mode)
        self._update_status()

    def _on_window(self, idx):
        sec = float(self.win_combo.itemData(idx))
        self._resize_buffer(sec)
        self.ruler.set_window(sec)
        if self.mode == MODE_REC:
            self.buf_proc[:] = 0
            self.buf_raw0[:] = 0
            self._live_n = 0
            self.ruler.set_mode("editor")
            self.ruler.set_duration(sec)

    def _on_gain(self, val):
        """前置增益编辑框: 仅录音开始前可设置 (录制中界面锁定), 作为下次录音初值。"""
        db = float(val)
        self.controller.set_gain_db(db)
        print("[ui] 前置增益 -> %+.1f dB (线性 ×%.3f)" % (db, 10.0 ** (db / 20.0)))
        self._update_status()

    def _resize_buffer(self, sec):
        W = max(2, int(sec * self.rate))
        for name in ("buf_proc", "buf_raw0"):
            old = getattr(self, name)
            new = np.zeros(W, dtype=np.float32)
            k = min(old.shape[0], W)
            if k > 0:
                new[W - k:] = old[old.shape[0] - k:]
            setattr(self, name, new)
        self.W = W
        self.window_sec = sec

    # ---- 数据源 ------------------------------------------------------------
    def _current_full(self):
        return self.full_raw0 if self.disp_source == "raw" else self.full_proc

    def _append_roll(self, arr, new):
        m = new.shape[0]
        if m == 0:
            return
        if m >= arr.shape[0]:
            arr[:] = new[-arr.shape[0]:]
        else:
            arr[:-m] = arr[m:]
            arr[-m:] = new

    def _push_live(self, proc1, raw1):
        """录制态写入短窗缓冲: 未填满时自左向右生长 (类 Audition), 填满后左滚。

        注意 proc/raw 每块长度可能略有差异, 各按自身长度计算填充量。
        """
        m = proc1.shape[0]
        for arr, new in ((self.buf_proc, proc1), (self.buf_raw0, raw1)):
            if new.shape[0] == 0:
                continue
            if self._live_n < self.W:
                k = min(new.shape[0], self.W - self._live_n)
                arr[self._live_n:self._live_n + k] = new[:k]
                if k < new.shape[0]:
                    self._append_roll(arr, new[k:])
            else:
                self._append_roll(arr, new)
        self._live_n = min(self.W, self._live_n + m)

    def _accum_full(self, proc1, raw1):
        self._full_proc.append(proc1)
        self._full_raw0.append(raw1)
        self._full_n += proc1.shape[0]
        cap = int(MAX_FULL_SEC * self.rate)
        while self._full_n > cap and len(self._full_proc) > 1:
            self._full_n -= self._full_proc[0].shape[0]
            self._full_proc.pop(0)
            self._full_raw0.pop(0)

    def _drain(self):
        engine = self.controller.engine
        if engine is None:
            return None
        blocks = []
        try:
            while True:
                blocks.append(engine.disp_q.get_nowait())
        except queue.Empty:
            pass
        if not blocks:
            return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
        procs, raws = [], []
        for raw, proc in blocks:
            p1 = proc[:, 0] if (proc is not None and proc.ndim == 2) else (
                proc if proc is not None else np.zeros(0, dtype=np.float32))
            r1 = raw[:, 0] if raw.ndim == 2 else raw
            procs.append(np.asarray(p1, dtype=np.float32))
            raws.append(np.asarray(r1, dtype=np.float32))
        return (np.concatenate(procs) if procs else np.zeros(0, dtype=np.float32),
                np.concatenate(raws) if raws else np.zeros(0, dtype=np.float32))

    def _enter_editor(self):
        self.full_proc = (np.concatenate(self._full_proc)
                          if self._full_proc else np.zeros(0, dtype=np.float32))
        self.full_raw0 = (np.concatenate(self._full_raw0)
                          if self._full_raw0 else np.zeros(0, dtype=np.float32))
        data = self._current_full()
        if data.size == 0:
            self.track.set_mode("live")
            self.ruler.set_mode("live")
            self._set_mode(MODE_IDLE)
            return
        self.track.set_mode("editor")
        self.ruler.set_mode("editor")
        self.ruler.set_duration(data.shape[0] / float(self.rate))
        self.track.set_playhead(0.0)
        self.track.set_full(data)
        self._set_mode(MODE_EDIT)

    # ---- 刷新循环 ----------------------------------------------------------
    def _refresh(self):
        if self.mode == MODE_REC:
            self._refresh_rec()
        elif self.mode == MODE_PLAY:
            self._refresh_play()
        else:
            self.meter.decay()
            self._update_status()

    def _refresh_rec(self):
        drained = self._drain()
        if drained is not None:
            proc1, raw1 = drained
            if proc1.size:
                self._accum_full(proc1, raw1)
                self._push_live(proc1, raw1)
                if self._live_n >= self.W and self.ruler.mode != "live":
                    self.ruler.set_mode("live")
                    self.ruler.set_window(self.window_sec)
                disp = self.buf_raw0 if self.disp_source == "raw" else self.buf_proc
                tail = raw1 if self.disp_source == "raw" else proc1
                rms = float(np.sqrt(np.mean(tail.astype(np.float64) ** 2)))
                peak = float(np.max(np.abs(tail))) if tail.size else 0.0
                self.meter.set_levels(rms, peak)
            else:
                self.meter.decay()
        self.track.set_live(self.buf_raw0 if self.disp_source == "raw" else self.buf_proc)
        self._update_status()

    def _refresh_play(self):
        pos = self.player.position
        n = max(1, self.player.n_samples)
        self.track.set_playhead(pos / float(n))
        data = self.player.data
        a = max(0, pos - 1024); b = min(data.shape[0], pos)
        if b > a:
            seg = data[a:b].astype(np.float64)
            self.meter.set_levels(float(np.sqrt(np.mean(seg ** 2))),
                                  float(np.max(np.abs(seg))))
        else:
            self.meter.decay()
        if self.player.finished or not self.player.playing:
            self.player.stop()
            self.track.set_full(self._current_full())
            self._set_mode(MODE_EDIT)
            print("[ui] 回放结束 @ %.2fs" % (pos / float(self.rate)))
        self._update_status()

    def _update_status(self):
        eng = self.controller.engine
        if self.mode == MODE_REC and eng is not None:
            rec_txt = " | 录音 %s" % self.controller.cap_dir if self.controller.cap_dir else ""
            self.status_lbl.setText(
                "录制 %.1fs | 算法 %s | 源 %s | 增益 %+.1fdB | %dHz·%dch·block%d | 窗口 %.0fs | xrun=%d%s"
                % (eng.elapsed, self.controller.algorithm or "-", self._src_name(),
                   self.controller.gain_db,
                   eng.samplerate, eng.channels, eng.blocksize, self.window_sec,
                   eng.xrun_count, rec_txt))
            self.save_link.hide()
        elif self.mode in (MODE_EDIT, MODE_PLAY):
            data = self._current_full()
            dur = data.shape[0] / float(self.rate)
            ph = self.track.playhead_frac * dur
            cap = self.controller.cap_dir
            self.status_lbl.setText(
                "编辑 | 源 %s | 时长 %.2fs | 播放头 %.2fs | 采样率 %dHz%s"
                % (self._src_name(), dur, ph, self.rate,
                   "  (回放中)" if self.mode == MODE_PLAY else ""))
            if cap:
                # 仅目录路径带下划线超链接, "已保存:" 前缀为普通文本
                self.save_link.setText(
                    '<span style="color:#9aa79a;">已保存: </span>'
                    '<a href="%s">%s</a>' % (cap, cap))
                self.save_link.show()
            else:
                self.save_link.hide()
        else:
            self.status_lbl.setText("待机 — 选择声卡/参数/算法后点「● 录音」")
            self.save_link.hide()

    def _open_cap_dir(self, path):
        """点击保存路径超链接 → 用资源管理器打开该 cap_* 目录。"""
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", os.path.normpath(path)])
            else:
                subprocess.Popen(["xdg-open", path])
            print("[ui] 打开保存目录: %s" % path)
        except Exception as e:
            print("[ui] 打开目录失败: %s" % e)

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.controller.stop()
        except Exception:
            pass
        super().closeEvent(event)

# -*- coding: utf-8 -*-
"""
Spek 风格频谱图显示组件
========================
- 高频在上/低频在下, Spek/sox 调色板
- 左侧频率轴 (kHz), 底部时间轴 (mm:ss)
- 支持叠加显示检测到的截止频率线
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.spectrogram import spectrogram_to_rgb


class SpectrogramWidget(QWidget):
    LEFT_PAD = 52
    BOTTOM_PAD = 24
    TOP_PAD = 8
    RIGHT_PAD = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self._rgb: np.ndarray | None = None
        self._freqs: np.ndarray | None = None
        self._duration: float = 0.0
        self._cutoff_khz: float | None = None
        self._title = "将音频文件添加到列表后, 点击文件名查看频谱图"

    # ------------------------------------------------------------------
    def set_spectrogram(self, s_db, freqs, duration, cutoff_khz=None):
        self._rgb = spectrogram_to_rgb(s_db)
        self._freqs = np.asarray(freqs)
        self._duration = float(duration)
        self._cutoff_khz = cutoff_khz
        self.update()

    def clear(self, title=None):
        self._rgb = None
        self._cutoff_khz = None
        if title:
            self._title = title
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(10, 10, 12))
        w, h = self.width(), self.height()
        area = self.rect().adjusted(self.LEFT_PAD, self.TOP_PAD,
                                    -self.RIGHT_PAD, -self.BOTTOM_PAD)

        if self._rgb is None:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect(), Qt.AlignCenter, self._title)
            p.end()
            return

        rgb = np.ascontiguousarray(self._rgb)      # 确保 C 连续
        hh, ww = rgb.shape[:2]
        img = QImage(rgb.data, ww, hh, ww * 3, QImage.Format_RGB888)
        p.drawImage(area, img.copy())

        # ── 频率轴 (左) ──
        p.setPen(QColor(180, 180, 180))
        fmax = float(self._freqs[-1])
        # 自适应刻度
        step = 5000 if fmax > 30000 else 2000
        f = 0.0
        while f <= fmax + 1:
            y = area.bottom() - (f / fmax) * area.height()
            label = f"{f / 1000:.0f}k" if f >= 1000 else f"{f:.0f}"
            p.drawText(2, int(y) - 6, self.LEFT_PAD - 6, 14,
                       Qt.AlignRight | Qt.AlignVCenter, label)
            p.setPen(QColor(60, 60, 60))
            p.drawLine(area.left(), int(y), area.right(), int(y))
            p.setPen(QColor(180, 180, 180))
            f += step

        # ── 时间轴 (下) ──
        if self._duration > 0:
            n_ticks = 6
            for i in range(n_ticks + 1):
                t = self._duration * i / n_ticks
                x = area.left() + area.width() * i / n_ticks
                mm, ss = divmod(int(t), 60)
                p.drawText(int(x) - 20, area.bottom() + 4, 44, 16,
                           Qt.AlignHCenter, f"{mm:02d}:{ss:02d}")

        # ── 截止频率标注线 ──
        if self._cutoff_khz and self._cutoff_khz * 1000 <= fmax:
            y = area.bottom() - (self._cutoff_khz * 1000 / fmax) * area.height()
            p.setPen(QPen(QColor(255, 80, 80), 1, Qt.DashLine))
            p.drawLine(area.left(), int(y), area.right(), int(y))
            p.setPen(QColor(255, 120, 120))
            p.drawText(area.right() - 110, int(y) - 4,
                       f"截止 {self._cutoff_khz:.1f}kHz")

        # 边框
        p.setPen(QColor(70, 70, 70))
        p.drawRect(area)
        p.end()

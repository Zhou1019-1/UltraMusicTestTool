# -*- coding: utf-8 -*-
"""
频谱图计算模块 (Spek 风格)
==========================
STFT -> 幅度谱 -> dB -> Spek 风格调色板 RGB 图像
所有运算基于 numpy/scipy, 无质量损耗 (仅用于显示与频域分析)
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft


def compute_spectrogram(samples: np.ndarray, samplerate: int,
                        nperseg: int = 4096, db_floor: float = -120.0,
                        max_points: int = 2_000_000):
    """
    计算频谱图
    返回 (freqs, times, S_db): S_db shape = (len(freqs), len(times)), 单位 dB
    对超长文件自动抽取时间帧, 限制内存
    """
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    nperseg = min(nperseg, max(256, len(x) // 4) if len(x) >= 1024 else len(x))
    nperseg = max(256, nperseg)
    noverlap = nperseg // 2
    freqs, times, Z = stft(x, fs=samplerate, window="hann",
                           nperseg=nperseg, noverlap=noverlap,
                           boundary=None, padded=False)
    mag = np.abs(Z)
    mag = np.maximum(mag, 1e-12)
    s_db = 20.0 * np.log10(mag)
    # 归一化到峰值 0 dB
    s_db -= s_db.max()
    s_db = np.clip(s_db, db_floor, 0.0)

    # 限制规模, 防止大图撑爆内存
    while s_db.size > max_points and s_db.shape[1] > 100:
        s_db = s_db[:, ::2]
        times = times[::2]
    while s_db.size > max_points and s_db.shape[0] > 100:
        s_db = s_db[::2, :]
        freqs = freqs[::2]
    return freqs, times, s_db


# Spek/sox 风格调色板: 黑 -> 深蓝 -> 蓝 -> 青 -> 绿 -> 黄 -> 红 -> 白
_PALETTE_STOPS = [
    (0.00, (0, 0, 0)),
    (0.25, (0, 0, 96)),
    (0.45, (0, 64, 200)),
    (0.60, (0, 200, 220)),
    (0.72, (0, 220, 60)),
    (0.85, (240, 240, 0)),
    (0.94, (255, 80, 0)),
    (1.00, (255, 255, 255)),
]


def _build_palette() -> np.ndarray:
    xs = np.array([s[0] for s in _PALETTE_STOPS])
    lut = np.zeros((256, 3), dtype=np.uint8)
    grid = np.linspace(0.0, 1.0, 256)
    for ch in range(3):
        ys = np.array([s[1][ch] for s in _PALETTE_STOPS])
        lut[:, ch] = np.interp(grid, xs, ys).astype(np.uint8)
    return lut


_PALETTE = _build_palette()


def spectrogram_to_rgb(s_db: np.ndarray, db_floor: float = -120.0) -> np.ndarray:
    """dB 矩阵 -> RGB uint8 图像 (H, W, 3), 低频在下, 高频在上"""
    norm = (s_db - db_floor) / (0.0 - db_floor)
    idx = np.clip(norm * 255.0, 0, 255).astype(np.uint8)
    rgb = _PALETTE[idx]                # (freq, time, 3)
    # 翻转使高频在上 (Spek 风格); 负步长数组需转为 C 连续供 QImage 使用
    return np.ascontiguousarray(rgb[::-1, :, :])

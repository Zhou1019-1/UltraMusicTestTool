# -*- coding: utf-8 -*-
"""
方法一: 频谱截止检测 (Spectral Cutoff / Brickwall Lowpass Detection)
=====================================================================
原理 (业界通行做法, auCDtect / Lossless Audio Checker / Tau Analyzer 同源):
  有损编码器 (MP3/AAC/OGG) 受码率限制必须使用陡峭的低通滤波器切除高频:
    - MP3 128kbps  ≈ 15-16 kHz 截止
    - MP3 192kbps  ≈ 18 kHz
    - MP3 320kbps  ≈ 20 kHz
    - AAC/OGG 类似
  真无损录音的高频是"自然衰减"的: 斜率平缓、随时间变化、含音乐泛音。
  有损转码的截止是"砖墙式"的: 过渡带极窄 (< 1 kHz), 截止之上只剩平坦量化噪声。

实现:
  1. 对整个文件做 STFT, 对时间轴求平均功率谱 -> 平均频谱剖面 (dB)
  2. 平滑后扫描候选截止点 fc (10kHz ~ Nyquist-1kHz), 计算 fc 上下 2kHz
     频带的能量差 (对比度), 取对比度最大的 fc
  3. 陡峭度 = 对比度 / 过渡带宽 (dB/kHz)
  4. 截止之上频带能量 vs 全局噪声底 -> 判断是否存在有效高频内容
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft

from ..audio_loader import AudioData
from .base import DetectionMethod, MethodResult


class SpectralCutoffMethod(DetectionMethod):
    method_id = "cutoff"
    name = "频谱截止检测"
    weight = 0.35

    def applicable(self, audio: AudioData) -> bool:
        return audio.duration >= 1.0

    # ------------------------------------------------------------------
    def analyze(self, audio: AudioData) -> MethodResult:
        if not self.applicable(audio):
            return self._na("音频过短 (<1s)")

        x = audio.mono
        sr = audio.samplerate
        nperseg = 8192 if sr >= 44100 else 4096
        freqs, _, Z = stft(x, fs=sr, window="hann", nperseg=nperseg,
                           noverlap=nperseg * 3 // 4, boundary=None, padded=False)
        power = (np.abs(Z) ** 2).mean(axis=1)          # 时间平均功率谱
        db = 10.0 * np.log10(np.maximum(power, 1e-20))
        db -= db.max()                                  # 峰值归一 0 dB

        # 平滑 (~200Hz 窗口)
        bw = freqs[1] - freqs[0]
        win = max(3, int(round(200.0 / bw)) | 1)
        kernel = np.ones(win) / win
        dbs = np.convolve(db, kernel, mode="same")

        nyq = sr / 2.0
        band = 2000.0          # 对比频带 2 kHz
        step = 100.0
        lo_f, hi_f = 10000.0, nyq - 1000.0
        best = None
        f = lo_f
        while f <= hi_f:
            lo = dbs[(freqs >= f - band) & (freqs < f)].mean() \
                if np.any((freqs >= f - band) & (freqs < f)) else 0
            hi = dbs[(freqs >= f) & (freqs < f + band)].mean() \
                if np.any((freqs >= f) & (freqs < f + band)) else 0
            drop = lo - hi
            # 要求截止之上确实"没什么东西"才算截止 (排除普通频谱起伏)
            if best is None or drop > best[1]:
                best = (f, drop, lo, hi)
            f += step

        cutoff_hz, drop_db, lo_db, hi_db = best
        sharpness = drop_db / (band / 1000.0)           # dB/kHz

        # 截止之上频带是否还有结构 (真实高频内容随时间变化)
        above_mask = freqs >= cutoff_hz
        above_time_var = 0.0
        if np.any(above_mask):
            above_energy = (np.abs(Z[above_mask]) ** 2).mean(axis=0)
            if above_energy.mean() > 0:
                above_time_var = float(above_energy.std() /
                                       (above_energy.mean() + 1e-20))

        # 全局高频参考: 16k~min(20k,nyq) 平均电平
        hf_ref_mask = (freqs >= 16000) & (freqs <= min(20000, nyq))
        hf_level = float(dbs[hf_ref_mask].mean()) if np.any(hf_ref_mask) else -120.0

        # ── 判定规则 ──
        score = 100.0
        deductions = []
        cutoff_khz = cutoff_hz / 1000.0
        rel_cutoff = cutoff_hz / nyq                    # 相对 Nyquist

        has_brickwall = drop_db >= 25 and sharpness >= 12 and hi_db <= -40
        has_cutoff = drop_db >= 15 and sharpness >= 6 and hi_db <= -35

        if has_brickwall:
            deductions.append((45, f"检测到砖墙式频率截止 @ {cutoff_khz:.1f}kHz "
                                  f"(对比度 {drop_db:.0f}dB, 斜率 {sharpness:.0f}dB/kHz), "
                                  f"典型有损低通滤波器特征"))
        elif has_cutoff:
            if rel_cutoff > 0.93:   # 贴近 Nyquist, 可能只是自然滚降
                deductions.append((8, f"Nyquist 附近存在能量下降 @ {cutoff_khz:.1f}kHz, "
                                      f"可能是抗混叠滤波或自然滚降"))
            else:
                deductions.append((25, f"检测到明显频率截止 @ {cutoff_khz:.1f}kHz "
                                      f"(对比度 {drop_db:.0f}dB), 疑似有损转码"))

        if cutoff_khz < 16.5 and has_cutoff:
            deductions.append((10, f"截止频率极低 ({cutoff_khz:.1f}kHz < 16.5kHz), "
                                  f"符合低码率 MP3 (≤128kbps) 转码特征"))
        elif cutoff_khz < 19 and has_cutoff:
            deductions.append((5, f"截止频率偏低 ({cutoff_khz:.1f}kHz), "
                                  f"符合中等码率有损编码特征"))

        # 高频整体电平过低 (真录音 16-20k 也有内容)
        if hf_level < -55 and nyq >= 22000:
            deductions.append((10, f"16-20kHz 频段平均电平极低 ({hf_level:.0f}dB), "
                                  f"缺乏真实高频内容"))

        # 截止之上几乎无时间变化 -> 静态噪声/真空
        if has_cutoff and above_time_var < 0.25:
            deductions.append((10, f"截止频率以上区域无音乐性时间变化 "
                                  f"(变异系数 {above_time_var:.2f}), 疑似空带/静态噪声"))

        for pts, _ in deductions:
            score -= pts
        score = max(0.0, min(100.0, score))

        if has_brickwall:
            summary = f"砖墙截止 @ {cutoff_khz:.1f}kHz, 强烈疑似有损转码"
        elif has_cutoff:
            summary = f"存在频率截止 @ {cutoff_khz:.1f}kHz, 有转码嫌疑"
        else:
            summary = "未检测到低通滤波器截止特征"

        return MethodResult(
            self.method_id, self.name, True, score,
            confidence=0.9 if len(x) > sr * 5 else 0.6,
            summary=summary, deductions=deductions,
            metrics={
                "cutoff_khz": round(cutoff_khz, 2),
                "contrast_db": round(float(drop_db), 1),
                "sharpness_db_per_khz": round(float(sharpness), 1),
                "hf_16_20k_level_db": round(hf_level, 1),
                "above_cutoff_time_cv": round(above_time_var, 2),
            })

# -*- coding: utf-8 -*-
"""
方法四: 采样率上转换检测 (Upsampling / Fake Hi-Res Detection)
==============================================================
原理 (Hi-Res 真伪鉴别的通行做法):
  "假 Hi-Res" 第二类手法: 把 44.1k/48k 音频重采样到 96k/192k 出售。
  特征:
    1) 有效带宽止步于源采样率 Nyquist (44.1k -> 22.05kHz),
       之上只有重采样滤波器的阻带底噪 -> 出现"第二条砖墙"
    2) 劣质重采样器会在源 Nyquist 处产生镜像混叠:
       fc-Δ 与 fc+Δ 的频谱呈镜像对称

实现 (仅对 sr ≥ 88.2k 的 Hi-Res 文件启用):
  1. 平均功率谱 -> dB 剖面
  2. 在候选源 Nyquist 频率 (22.05k, 24k, 32k) 附近检测能量落差
  3. 镜像检测: 比较 fc 上下对称频带的相关性
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft

from ..audio_loader import AudioData
from .base import DetectionMethod, MethodResult

# 常见源采样率对应的 Nyquist 频率
_SOURCE_NYQUISTS = [22050.0, 24000.0, 32000.0, 16000.0]


class UpsamplingMethod(DetectionMethod):
    method_id = "upsampling"
    name = "采样率上转换检测"
    weight = 0.25

    def applicable(self, audio: AudioData) -> bool:
        return (not audio.is_lossy_container
                and audio.samplerate >= 88200
                and audio.duration >= 1.0)

    # ------------------------------------------------------------------
    def analyze(self, audio: AudioData) -> MethodResult:
        if not self.applicable(audio):
            reason = ("有损容器" if audio.is_lossy_container
                      else f"采样率 {audio.samplerate}Hz < 88.2kHz, 非 Hi-Res 无需检测")
            return self._na(reason)

        x = audio.mono
        sr = audio.samplerate
        nyq = sr / 2.0

        freqs, _, Z = stft(x, fs=sr, window="hann", nperseg=16384,
                           noverlap=12288, boundary=None, padded=False)
        power = (np.abs(Z) ** 2).mean(axis=1)
        db = 10.0 * np.log10(np.maximum(power, 1e-20))
        db -= db.max()
        bw = freqs[1] - freqs[0]
        win = max(3, int(round(200.0 / bw)) | 1)
        dbs = np.convolve(db, np.ones(win) / win, mode="same")

        score = 100.0
        deductions = []
        detected_src = None
        drop_db = 0.0

        # ── 候选源 Nyquist 处的能量落差 ──
        half = 1500.0
        for src_nyq in _SOURCE_NYQUISTS:
            if src_nyq + half >= nyq:
                continue
            lo = dbs[(freqs >= src_nyq - half) & (freqs < src_nyq)].mean()
            hi = dbs[(freqs >= src_nyq) & (freqs < src_nyq + half)].mean()
            drop = lo - hi
            if drop > drop_db:
                drop_db, detected_src = drop, src_nyq

        if drop_db >= 20 and detected_src is not None:
            src_sr = detected_src * 2 / 1000.0
            deductions.append((40, f"在 {detected_src / 1000:.2f}kHz 处检测到能量陡降 "
                                  f"({drop_db:.0f}dB), 精确对应 {src_sr:.1f}kHz 源采样率 "
                                  f"Nyquist, 典型低采样率→{sr / 1000:.0f}kHz 上转换"))
        elif drop_db >= 12 and detected_src is not None:
            deductions.append((15, f"在 {detected_src / 1000:.2f}kHz 附近存在能量下降 "
                                  f"({drop_db:.0f}dB), 可能经过采样率转换"))

        # ── 镜像混叠检测 (劣质 SRC 特征) ──
        mirror_corr = 0.0
        if detected_src is not None and detected_src + 3000 < nyq:
            m_lo = (freqs >= detected_src - 3000) & (freqs < detected_src - 200)
            m_hi = (freqs >= detected_src + 200) & (freqs < detected_src + 3000)
            if m_lo.sum() > 4 and m_hi.sum() > 4:
                a = dbs[m_lo][::-1]
                b = dbs[m_hi]
                n = min(len(a), len(b))
                a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
                denom = np.sqrt((a ** 2).sum() * (b ** 2).sum())
                if denom > 1e-12:
                    mirror_corr = float((a * b).sum() / denom)
            if mirror_corr >= 0.7:
                deductions.append((10, f"源 Nyquist 两侧频谱镜像相关 {mirror_corr:.2f}, "
                                      f"存在重采样镜像混叠痕迹"))

        # ── 超高频内容检查: 真 96k/192k 录音在 24k+ 应有内容 ──
        band_mask = (freqs >= 24000) & (freqs <= min(40000, nyq * 0.95))
        uhf_level = float(dbs[band_mask].mean()) if np.any(band_mask) else -120.0
        if uhf_level < -60 and not deductions:
            deductions.append((10, f"24kHz 以上频段平均电平 {uhf_level:.0f}dB, "
                                  f"缺乏超高频内容, 高采样率无实际信息收益"))

        for pts, _ in deductions:
            score -= pts
        score = max(0.0, min(100.0, score))

        summary = (f"疑似源采样率 {detected_src * 2 / 1000:.1f}kHz 上转换"
                   if detected_src is not None and drop_db >= 12
                   else "未发现采样率上转换特征")
        return MethodResult(
            self.method_id, self.name, True, score,
            confidence=0.85, summary=summary, deductions=deductions,
            metrics={
                "samplerate_khz": round(sr / 1000.0, 1),
                "suspected_source_nyquist_khz":
                    round(detected_src / 1000.0, 2) if detected_src else "无",
                "edge_drop_db": round(float(drop_db), 1),
                "mirror_correlation": round(mirror_corr, 2),
                "uhf_24k_level_db": round(uhf_level, 1),
            })

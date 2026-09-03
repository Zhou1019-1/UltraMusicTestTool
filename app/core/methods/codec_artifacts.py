# -*- coding: utf-8 -*-
"""
方法三: 有损编码帧痕迹检测 (Codec Frame Artifact Detection)
=============================================================
原理 (学术界/业界通行做法, 见音频取证文献:
  - "Detection of MP3 double compression" (音频取证领域经典课题)
  - MDCT 块边界周期性分析)
  MP3/AAC 等基于 MDCT 的编码器按固定帧长处理音频:
    - MP3: 1152 采样/帧 (576/granule)
    - AAC: 1024 采样/帧
    - Opus: 960 采样/帧 (20ms@48k)
  量化噪声在每帧边界重新分布, 会在高频段的短时能量上留下周期性调制。
  即使转码为 FLAC/WAV, 该周期痕迹依然保留 -> 可识别"有损→无损"转码。

  另有两个辅助子指标 (与原 Spek V4.0 工具思想一致):
    a) 高频谱平坦度 (Spectral Flatness): 截止之上若为均匀量化噪声,
       平坦度显著高于真实音乐内容
    b) 联合立体声痕迹: 低码率 MP3 的 Joint Stereo 会在高频段
       压缩 Side 声道能量

实现:
  1. 高频带 (12kHz ~ min(20k, Nyq)) 短时能量序列 (hop=128)
  2. 对候选帧周期 (MP3 1152, MP3 granule 576, AAC 1024, Opus 960)
     做"折叠平均": 按周期重排后求模板方差 / 总方差 = 周期性强度
  3. 谱平坦度 = 几何均值 / 算术均值 (Wiener entropy)
  4. Side/Mid 高频能量比 (仅立体声)
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft

from ..audio_loader import AudioData
from .base import DetectionMethod, MethodResult

# 候选编码帧周期 (单位: 采样点), 按采样率折算
_FRAME_CANDIDATES = {
    "MP3帧(1152)": 1152,
    "MP3颗粒(576)": 576,
    "AAC帧(1024)": 1024,
    "Opus帧(960)": 960,
}


class CodecArtifactMethod(DetectionMethod):
    method_id = "codec_artifact"
    name = "编码帧痕迹检测"
    weight = 0.25

    def applicable(self, audio: AudioData) -> bool:
        return (not audio.is_lossy_container
                and audio.samplerate >= 32000
                and audio.duration >= 3.0)

    # ------------------------------------------------------------------
    def analyze(self, audio: AudioData) -> MethodResult:
        if not self.applicable(audio):
            if audio.is_lossy_container:
                return self._na("文件本身即有损编码, 无需检测转码痕迹")
            return self._na("采样率过低或时长不足 (<3s)")

        x = audio.mono
        sr = audio.samplerate
        nyq = sr / 2.0

        # ── 高频带短时能量序列 ──
        nperseg = 512
        freqs, _, Z = stft(x, fs=sr, window="hann", nperseg=nperseg,
                           noverlap=nperseg - 128, boundary=None, padded=False)
        hf_mask = (freqs >= 12000) & (freqs <= min(20000, nyq * 0.95))
        if not np.any(hf_mask):
            hf_mask = freqs >= nyq * 0.5
        hf_energy = (np.abs(Z[hf_mask]) ** 2).mean(axis=0)
        hop_samples = 128

        # 线性域 + 去趋势: 编码帧调制是叠加在缓慢变化的音乐包络上的
        # 高频周期性波动, 先去均值去慢包络再折叠检测
        e = hf_energy.astype(np.float64)
        slow = np.convolve(e, np.ones(64) / 64, mode="same")
        e = e - slow
        e[:32] = 0
        e[-32:] = 0

        # ── 帧周期折叠检测 ──
        best_period, best_strength = None, 0.0
        total_var = float(e.var()) + 1e-20
        for label, period_samples in _FRAME_CANDIDATES.items():
            p = period_samples / hop_samples
            # 周期需为非整数 hop 时四舍五入到 hop 网格
            p_hops = max(2, round(p))
            n_epochs = len(e) // p_hops
            if n_epochs < 24:
                continue
            folded = e[:n_epochs * p_hops].reshape(n_epochs, p_hops)
            pattern = folded.mean(axis=0)
            strength = float(pattern.var() / total_var)
            if strength > best_strength:
                best_strength, best_period = strength, label

        periodicity = best_strength          # 0~1, 越大越可疑

        # ── 高频谱平坦度 ──
        hf_power = (np.abs(Z[hf_mask]) ** 2).mean(axis=1) + 1e-30
        flatness = float(np.exp(np.log(hf_power).mean()) / hf_power.mean())

        # ── 联合立体声痕迹 (Side/Mid 高频能量比) ──
        side_mid_ratio = None
        if audio.channels == 2:
            L, R = audio.samples[:, 0], audio.samples[:, 1]
            side = 0.5 * (L - R)
            mid = 0.5 * (L + R)
            _, _, Zs = stft(side, fs=sr, window="hann", nperseg=1024,
                            noverlap=768, boundary=None, padded=False)
            _, _, Zm = stft(mid, fs=sr, window="hann", nperseg=1024,
                            noverlap=768, boundary=None, padded=False)
            fs2 = np.fft.rfftfreq(1024, 1.0 / sr)
            m2 = (fs2 >= 10000) & (fs2 <= min(18000, nyq * 0.9))
            if np.any(m2):
                se = (np.abs(Zs[m2]) ** 2).mean()
                me = (np.abs(Zm[m2]) ** 2).mean()
                side_mid_ratio = float(se / (me + 1e-20))

        # ── 判定 ──
        score = 100.0
        deductions = []

        if periodicity >= 0.35:
            deductions.append((30, f"高频能量存在强周期性调制 (强度 {periodicity:.2f}), "
                                  f"周期与 {best_period} 吻合, 典型有损编码帧残留"))
        elif periodicity >= 0.20:
            deductions.append((15, f"高频能量存在周期性波动 (强度 {periodicity:.2f}, "
                                  f"接近 {best_period}), 有编码帧痕迹嫌疑"))

        if flatness >= 0.25:
            deductions.append((10, f"高频段谱平坦度过高 ({flatness:.2f}), "
                                  f"接近白噪声特征, 疑似量化噪声填充"))

        if side_mid_ratio is not None and side_mid_ratio < 0.02:
            deductions.append((10, f"高频段 Side/Mid 能量比极低 ({side_mid_ratio:.4f}), "
                                  f"符合 Joint Stereo 有损编码的高频合并特征"))

        for pts, _ in deductions:
            score -= pts
        score = max(0.0, min(100.0, score))

        summary = (f"帧周期痕迹强度 {periodicity:.2f}"
                   + (f" ({best_period})" if best_period else "")
                   + (", 检测到编码残留" if deductions else ", 未见明显编码残留"))
        return MethodResult(
            self.method_id, self.name, True, score,
            confidence=0.8, summary=summary, deductions=deductions,
            metrics={
                "frame_periodicity": round(periodicity, 3),
                "matched_period": best_period or "无",
                "hf_spectral_flatness": round(flatness, 3),
                "hf_side_mid_ratio": (round(side_mid_ratio, 4)
                                      if side_mid_ratio is not None else "单声道"),
            })

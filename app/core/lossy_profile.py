# -*- coding: utf-8 -*-
"""
有损文件画像 (MP3/OGG/Opus 等)
================================
有损容器文件无需判断"真假", 直接判定有损; 但用户关心"损在哪":
  1. 频率带宽损失: 截止频率 (低通滤波位置)
  2. 码率估算: 文件大小 / 时长
  3. 高频谱平坦度: 量化噪声粗糙程度
  4. 联合立体声程度: 高频 Side 能量是否被合并
  5. 编码帧周期: 反推编码器家族 (MP3 1152 / AAC 1024 / Opus 960)
"""
from __future__ import annotations

import numpy as np
from scipy.signal import stft

from .audio_loader import AudioData

# 截止频率 -> 常见编码配置经验表 (MP3 为主)
_BITRATE_HINTS = [
    (15.5, "≤96kbps 级别 (严重带宽损失)"),
    (16.5, "~128kbps 级别 (MP3 低码率典型截止 15-16kHz)"),
    (18.5, "~160-192kbps 级别 (中码率典型截止 17-18kHz)"),
    (20.0, "~256-320kbps 或 V0 级别 (高码率截止 19-20kHz)"),
    (99.0, "全带宽保留 (高码率/低压缩)"),
]


def analyze_lossy(audio: AudioData) -> dict:
    """对有损容器文件生成"损在哪"画像"""
    x = audio.mono
    sr = audio.samplerate
    nyq = sr / 2.0

    base = {"estimated_bitrate_kbps": round(audio.estimated_bitrate_kbps, 0)}
    # 过短音频(损坏文件只解出几个采样)无法做STFT, 直接返回最小画像
    if len(x) < 4096:
        return {**base, "cutoff_khz": 0.0, "quality_hint": "音频过短",
                "hf_flatness": 0.0, "hf_side_mid_ratio": "N/A",
                "losses": ["音频时长过短或解码不完整, 无法生成损失画像"]}

    # nperseg 自适应输入长度, 保证 noverlap < nperseg
    nseg = min(8192, 1 << int(np.log2(len(x))))
    nolap = nseg * 3 // 4
    freqs, _, Z = stft(x, fs=sr, window="hann", nperseg=nseg,
                       noverlap=nolap, boundary=None, padded=False)
    power = (np.abs(Z) ** 2).mean(axis=1)
    db = 10.0 * np.log10(np.maximum(power, 1e-20))
    db -= db.max()
    bw = freqs[1] - freqs[0]
    win = max(3, int(round(200.0 / bw)) | 1)
    dbs = np.convolve(db, np.ones(win) / win, mode="same")

    # 截止频率: 能量跌至 -45dB 以下且不再回升的位置
    cutoff_khz = nyq / 1000.0
    floor_mask = dbs < -45
    for i in range(len(freqs) - 1, int(np.searchsorted(freqs, 10000)), -1):
        if not floor_mask[i]:
            cutoff_khz = min(freqs[i] / 1000.0 + 0.3, nyq / 1000.0)
            break
    # 经验映射
    quality_hint = _BITRATE_HINTS[-1][1]
    for lim, hint in _BITRATE_HINTS:
        if cutoff_khz <= lim:
            quality_hint = hint
            break

    # 高频平坦度
    hf_mask = (freqs >= 12000) & (freqs <= min(18000, nyq * 0.9))
    flatness = 0.0
    if np.any(hf_mask):
        p = power[hf_mask] + 1e-30
        flatness = float(np.exp(np.log(p).mean()) / p.mean())

    # Side/Mid (立体声)
    side_mid_ratio = None
    if audio.channels == 2 and len(x) >= 2048:
        side = 0.5 * (audio.samples[:, 0] - audio.samples[:, 1])
        mid = 0.5 * (audio.samples[:, 0] + audio.samples[:, 1])
        _, _, Zs = stft(side, fs=sr, window="hann", nperseg=2048,
                        noverlap=1536, boundary=None, padded=False)
        _, _, Zm = stft(mid, fs=sr, window="hann", nperseg=2048,
                        noverlap=1536, boundary=None, padded=False)
        fs2 = np.fft.rfftfreq(2048, 1.0 / sr)
        m2 = (fs2 >= 10000) & (fs2 <= min(16000, nyq * 0.9))
        if np.any(m2):
            side_mid_ratio = float((np.abs(Zs[m2]) ** 2).mean() /
                                   ((np.abs(Zm[m2]) ** 2).mean() + 1e-20))

    losses = [f"带宽损失: 有效频率上限约 {cutoff_khz:.1f}kHz "
              f"(人耳可听范围 20kHz, 损失 {max(0.0, 20 - cutoff_khz):.1f}kHz 高频细节)",
              f"估算码率 ≈ {audio.estimated_bitrate_kbps:.0f}kbps, {quality_hint}"]
    if flatness >= 0.2:
        losses.append(f"高频量化噪声明显 (谱平坦度 {flatness:.2f}), "
                      f"镲片/泛音有涂抹感风险")
    if side_mid_ratio is not None and side_mid_ratio < 0.03:
        losses.append(f"高频声场被压缩 (Side/Mid 能量比 {side_mid_ratio:.3f}), "
                      f"采用联合立体声编码, 空间细节受损")

    return {
        "cutoff_khz": round(cutoff_khz, 2),
        "estimated_bitrate_kbps": round(audio.estimated_bitrate_kbps, 0),
        "quality_hint": quality_hint,
        "hf_flatness": round(flatness, 3),
        "hf_side_mid_ratio": (round(side_mid_ratio, 4)
                              if side_mid_ratio is not None else "单声道"),
        "losses": losses,
    }

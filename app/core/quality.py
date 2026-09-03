# -*- coding: utf-8 -*-
"""
音质维度分析 (借鉴 SoniqTools 分析维度)
======================================
- 峰值电平 / RMS 电平 / Crest Factor (动态余量)
- 动态范围估计 (短时 RMS 分位数差)
- 削波检测 (连续满幅采样)
- 立体声相关性 (左右声道皮尔逊相关)
- 简化音频指纹 (频谱特征量化哈希, 用于重复/同源识别)
每项输出 等级(pass/info/warn/fail) + 人话说明, 供 UI 三态卡片展示
"""
from __future__ import annotations

import hashlib

import numpy as np


def _db(x: float) -> float:
    return 20.0 * np.log10(max(float(x), 1e-12))


def analyze_quality(audio) -> dict:
    """
    输入 AudioData (samples: (frames, channels) float64 [-1,1])
    返回 dict(peak_dbfs, rms_dbfs, crest_db, dynamic_range_db,
              clipping_samples, clipping, stereo_correlation,
              fingerprint, checks=[(名称, 等级, 说明), ...])
    """
    x = audio.samples
    sr = audio.samplerate
    out = {"checks": []}

    if x.size == 0:
        out["checks"].append(("电平", "fail", "音频无有效采样"))
        return out

    mono = x.mean(axis=1) if x.ndim > 1 else x

    # ── 峰值 / RMS / Crest ──
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono ** 2)))
    out["peak_dbfs"] = round(_db(peak), 2)
    out["rms_dbfs"] = round(_db(rms), 2)
    out["crest_db"] = round(_db(peak) - _db(rms), 2)

    # ── 动态范围 (短时 RMS 的 P95-P10) ──
    win = max(1, int(sr * 0.4))  # 400ms 窗
    n_win = len(mono) // win
    if n_win >= 5:
        frames = mono[:n_win * win].reshape(n_win, win)
        short_rms = np.sqrt(np.mean(frames ** 2, axis=1))
        short_db = 20.0 * np.log10(np.maximum(short_rms, 1e-12))
        dr = float(np.percentile(short_db, 95) - np.percentile(short_db, 10))
        out["dynamic_range_db"] = round(dr, 1)
    else:
        out["dynamic_range_db"] = 0.0

    # ── 削波检测: ≥3 个连续采样达到满幅 ──
    clip_thresh = 0.999
    clipped = np.abs(x) >= clip_thresh
    clip_samples = int(clipped.sum())
    consec = 0
    max_consec = 0
    for v in clipped.any(axis=1) if x.ndim > 1 else clipped:
        consec = consec + 1 if v else 0
        max_consec = max(max_consec, consec)
    out["clipping_samples"] = clip_samples
    out["clipping"] = max_consec >= 3

    # ── 立体声相关性 ──
    if audio.channels >= 2 and x.ndim > 1 and x.shape[1] >= 2:
        l, r = x[:, 0], x[:, 1]
        if l.std() > 1e-9 and r.std() > 1e-9:
            out["stereo_correlation"] = round(float(np.corrcoef(l, r)[0, 1]), 3)
        else:
            out["stereo_correlation"] = 1.0
    else:
        out["stereo_correlation"] = None

    # ── 简化音频指纹: 频谱质心/ rolloff / 能量 量化哈希 ──
    out["fingerprint"] = _fingerprint(mono, sr)

    # ── 逐维度评级 (SoniqTools 风格 pass/info/warn/fail) ──
    checks = out["checks"]

    crest = out["crest_db"]
    if crest >= 14:
        checks.append(("动态范围", "pass", f"Crest {crest} dB，动态自然舒展"))
    elif crest >= 10:
        checks.append(("动态范围", "info", f"Crest {crest} dB，动态正常"))
    elif crest >= 7:
        checks.append(("动态范围", "warn", f"Crest {crest} dB，压缩感明显（响度战争）"))
    else:
        checks.append(("动态范围", "fail", f"Crest {crest} dB，过度压缩，听感扁平"))

    if out["clipping"]:
        checks.append(("削波", "fail",
                       f"检测到削波（连续满幅采样 {clip_samples} 个），存在可闻失真"))
    elif out["peak_dbfs"] > -1.0:
        checks.append(("削波", "warn",
                       f"峰值 {out['peak_dbfs']} dBFS，接近满幅，有削波风险"))
    else:
        checks.append(("削波", "pass", f"峰值 {out['peak_dbfs']} dBFS，余量健康"))

    corr = out["stereo_correlation"]
    if corr is None:
        checks.append(("立体声", "info", "单声道音轨"))
    elif corr >= 0.98:
        checks.append(("立体声", "info", f"相关性 {corr}，左右声道几乎一致（近单声道）"))
    elif corr >= 0.3:
        checks.append(("立体声", "pass", f"相关性 {corr}，立体声声场正常"))
    elif corr >= 0:
        checks.append(("立体声", "info", f"相关性 {corr}，声场较宽"))
    else:
        checks.append(("立体声", "warn", f"相关性 {corr}，存在反相，单声道播放可能抵消"))

    if sr >= 88200:
        checks.append(("采样率", "info", f"{sr} Hz 高解析规格（是否真 Hi-Res 见鉴别结论）"))
    elif sr >= 44100:
        checks.append(("采样率", "pass", f"{sr} Hz 标准规格"))
    else:
        checks.append(("采样率", "warn", f"{sr} Hz 低于 CD 规格"))

    return out


def _fingerprint(mono: np.ndarray, sr: int) -> str:
    """
    简化音频指纹: 将音轨分 32 段, 每段提取
    (频谱质心, 85% rolloff, log能量) 量化后拼接做 SHA1。
    同一录音的不同编码版本指纹相近率低, 相同文件指纹完全一致,
    用于重复文件/同源快速比对。
    """
    n_seg = 32
    if len(mono) < 2048:
        return "N/A(过短)"
    seg_len = len(mono) // n_seg
    feats = []
    freqs_cache = {}
    for i in range(n_seg):
        seg = mono[i * seg_len:(i + 1) * seg_len]
        nfft = 4096 if len(seg) >= 4096 else 1024
        if nfft not in freqs_cache:
            freqs_cache[nfft] = np.fft.rfftfreq(nfft, 1.0 / sr)
        freqs = freqs_cache[nfft]
        # 分段内取中间 nfft 采样做 FFT
        mid = max(0, (len(seg) - nfft) // 2)
        blk = seg[mid:mid + nfft]
        if len(blk) < nfft:
            blk = np.pad(blk, (0, nfft - len(blk)))
        mag = np.abs(np.fft.rfft(blk * np.hanning(nfft))) + 1e-12
        centroid = float(np.sum(freqs * mag) / np.sum(mag))
        cum = np.cumsum(mag)
        roll = float(freqs[np.searchsorted(cum, 0.85 * cum[-1])])
        energy = float(np.log10(np.sum(mag ** 2)))
        feats.append((int(centroid // 50), int(roll // 100), int(energy * 2)))
    raw = np.array(feats, dtype=np.int32).tobytes()
    return hashlib.sha1(raw).hexdigest()[:24]

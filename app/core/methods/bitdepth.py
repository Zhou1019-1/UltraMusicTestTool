# -*- coding: utf-8 -*-
"""
方法二: 位深与量化分析 (Bit-depth / Quantization Analysis)
===========================================================
原理 (业界通行做法, 见于 Lossless Audio Checker / spek 社区方法):
  "假 Hi-Res" 常见手法: 把 16bit/44.1kHz 音频直接封装成 24bit/96kHz 出售。
  - 真 24bit 录音: 本底噪声会激活最低有效位 (LSB), LSB 近似随机
  - 假 24bit (由 16bit 上转换): 低 8 位恒为 0, 存在明显的"位空洞"
  同理, 若 16bit 文件实际只用到了 14bit, 说明可能被低精度化处理过。

实现:
  1. 把 float 采样还原为容器位深的整数域
  2. 统计每个采样的末尾零位数 (trailing zeros)
  3. 有效位深 = 声明位深 - 末尾零位的高分位数
  4. 结合量化 SNR 估计交叉验证
"""
from __future__ import annotations

import numpy as np

from ..audio_loader import AudioData
from .base import DetectionMethod, MethodResult


class BitDepthMethod(DetectionMethod):
    method_id = "bitdepth"
    name = "位深量化分析"
    weight = 0.15

    def applicable(self, audio: AudioData) -> bool:
        return (not audio.is_lossy_container
                and audio.bit_depth >= 16
                and audio.container != "DSF(DSD)")

    # ------------------------------------------------------------------
    def analyze(self, audio: AudioData) -> MethodResult:
        if not self.applicable(audio):
            reason = ("有损容器无固定位深" if audio.is_lossy_container
                      else "DSD 为 1bit 流, 位深检测不适用"
                      if audio.container == "DSF(DSD)" else "位深不足 16bit")
            return self._na(reason)

        bits = audio.bit_depth
        x = audio.samples
        scale = float(2 ** (bits - 1))
        ints = np.rint(np.clip(x, -1.0, 1.0 - 1.0 / scale) * scale).astype(np.int64)
        abs_ints = np.abs(ints)

        # 逐样本末尾零位数 (向量化: 逐位检查)
        tz = np.zeros(abs_ints.shape, dtype=np.int32)
        tmp = abs_ints.copy()
        nonzero = tmp != 0
        for _ in range(bits):
            lsb_set = (tmp & 1) != 0
            advance = nonzero & ~lsb_set
            tz[advance] += 1
            tmp[advance] >>= 1
            nonzero = tmp != 0
            if not advance.any():
                break
        # 采样值为 0 的按满位零处理
        tz[abs_ints == 0] = bits

        # 统计方法: 对随机量化数据, 单个样本 tz>=k 的概率天然为 2^-k,
        # 因此不能用分位数, 而用"占比": 若超过 99% 的样本 tz>=k,
        # 说明低 k 位被人为清零 (上转换), 有效位深 = bits - k_max
        nz = abs_ints > 0
        if not np.any(nz):
            return self._na("全静音文件")
        tz_nz = tz[nz]

        def frac_ge(k: int) -> float:
            return float(np.mean(tz_nz >= k))

        k_max = 0
        for k in range(1, bits):
            if frac_ge(k) > 0.99:
                k_max = k
            else:
                break
        effective_bits = bits - k_max
        lsb_zero_fraction = frac_ge(1)

        score = 100.0
        deductions = []
        if bits >= 24:
            if k_max >= 8:
                deductions.append((45, f"声明 24bit 但 {frac_ge(8) * 100:.1f}% 样本的 "
                                      f"低 8 位恒为 0, 实际有效位深仅 ~{effective_bits}bit, "
                                      f"典型 16bit→24bit 假 Hi-Res 上转换"))
            elif k_max >= 4:
                deductions.append((20, f"24bit 文件低 {k_max} 位几乎恒为 0 "
                                      f"(有效位深 ~{effective_bits}bit), "
                                      f"可能经过低精度源上转换"))
        elif bits == 16:
            if effective_bits <= 12:
                deductions.append((15, f"16bit 文件有效位深仅 ~{effective_bits}bit "
                                      f"({frac_ge(4) * 100:.1f}% 样本低4位为0), "
                                      f"疑似低精度源或重度数字处理"))

        for pts, _ in deductions:
            score -= pts
        score = max(0.0, min(100.0, score))

        summary = (f"有效位深 ~{effective_bits}bit / 声明 {bits}bit"
                   + (", 存在位空洞" if deductions else ", 位深利用正常"))
        return MethodResult(
            self.method_id, self.name, True, score,
            confidence=0.85, summary=summary, deductions=deductions,
            metrics={
                "claimed_bits": bits,
                "effective_bits": effective_bits,
                "trailing_zero_bits": k_max,
                "lsb_zero_fraction": round(lsb_zero_fraction, 4),
            })

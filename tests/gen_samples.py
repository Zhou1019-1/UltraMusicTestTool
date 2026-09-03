# -*- coding: utf-8 -*-
"""
生成已知真/假无损测试样本
==========================
输出到 tests/samples/:
  真: true_16bit_44k.flac / true_16bit.wav / true_24bit_96k.flac / true_dsd64.dsf
  假: fake_mp3_to_flac.flac (真MP3转码) / fake_16to24bit.flac (位深上转换)
      fake_44kto96k.flac (采样率上转换)
  有损: real_lossy.mp3
"""
import os
import struct

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

OUT = os.path.join(os.path.dirname(__file__), "samples")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(42)


def music(sr, seconds, hf=True):
    """类音乐信号: 基频泛音列 + 时变包络 + 宽频噪声底"""
    n = int(sr * seconds)
    t = np.arange(n) / sr
    x = np.zeros(n)
    f0 = 220.0
    k = 1
    while f0 * k < sr * 0.45:
        amp = 0.3 / k
        env = 0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t + k)   # 时变包络
        x += amp * env * np.sin(2 * np.pi * f0 * k * t)
        k += 1
    if hf:  # 全带宽噪声底 (模拟真实录音的本底)
        x += 0.002 * rng.standard_normal(n)
    x *= 0.8 / max(1e-9, np.abs(x).max())
    stereo = np.stack([x, np.roll(x, 17) * 0.9], axis=1)
    return stereo


def main():
    # ── 真无损样本 ──
    m44 = music(44100, 12)
    sf.write(f"{OUT}/true_16bit_44k.flac", m44, 44100, subtype="PCM_16")
    sf.write(f"{OUT}/true_16bit.wav", m44, 44100, subtype="PCM_16")

    m96 = music(96000, 8)
    sf.write(f"{OUT}/true_24bit_96k.flac", m96, 96000, subtype="PCM_24")

    # ── 假无损 1: 真 MP3 转码 → FLAC ──
    mp3_path = f"{OUT}/_tmp.mp3"
    sf.write(mp3_path, m44, 44100, format="MP3", subtype="MPEG_LAYER_III")
    dec, sr = sf.read(mp3_path, dtype="float64", always_2d=True)
    sf.write(f"{OUT}/fake_mp3_to_flac.flac", dec, sr, subtype="PCM_16")
    os.replace(mp3_path, f"{OUT}/real_lossy.mp3")   # 同时保留 mp3 原件

    # ── 假无损 2: 16bit → 假 24bit ──
    q16 = np.round(m96 * (2 ** 15)) / (2 ** 15)      # 16bit 量化
    sf.write(f"{OUT}/fake_16to24bit.flac", q16, 96000, subtype="PCM_24")

    # ── 假无损 3: 44.1k → 假 96k ──
    up = resample_poly(m44, 320, 147, axis=0)         # 44100*320/147 = 96000
    sf.write(f"{OUT}/fake_44kto96k.flac", up, 96000, subtype="PCM_24")

    # ── 真 DSD64 (一阶 Sigma-Delta 调制) ──
    write_dsf(f"{OUT}/true_dsd64.dsf", seconds=5)

    print("样本生成完成:")
    for f in sorted(os.listdir(OUT)):
        print("  ", f, os.path.getsize(f"{OUT}/{f}") // 1024, "KB")


def write_dsf(path, seconds=5, dsd_rate=2822400):
    """写单声道 DSF (DSD64), 内容: 440Hz 正弦 + 噪声, 一阶 SDM"""
    n = dsd_rate * seconds
    t = np.arange(n) / dsd_rate
    sig = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.05 * rng.standard_normal(n)
    # 一阶 sigma-delta
    out = np.zeros(n, dtype=np.uint8)
    err = 0.0
    for i in range(n):
        err += sig[i]
        if err >= 0:
            out[i] = 1
            err -= 1.0
        else:
            err += 1.0
    block = 4096
    data = np.packbits(out)                       # MSB first
    pad = (-len(data)) % block
    if pad:
        data = np.concatenate([data, np.full(pad, 0x69, dtype=np.uint8)])
    sample_count = n
    file_size = 28 + 12 + 52 + 12 + len(data)

    with open(path, "wb") as f:
        f.write(b"DSD ")
        f.write(struct.pack("<Q", 28))
        f.write(struct.pack("<Q", file_size))
        f.write(struct.pack("<Q", 0))            # metadata offset
        f.write(b"fmt ")
        f.write(struct.pack("<Q", 52))
        f.write(struct.pack("<I", 1))            # version
        f.write(struct.pack("<I", 0))            # format id: DSD raw
        f.write(struct.pack("<I", 1))            # channel type: mono
        f.write(struct.pack("<I", 1))            # channels
        f.write(struct.pack("<I", dsd_rate))
        f.write(struct.pack("<I", 1))            # bits per sample
        f.write(struct.pack("<Q", sample_count))
        f.write(struct.pack("<I", block))        # block size per channel
        f.write(struct.pack("<I", 0))            # reserved
        f.write(b"data")
        f.write(struct.pack("<Q", 12 + len(data)))
        f.write(data.tobytes())


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""检测: 失败的 MP3 是否存在有效 MPEG 帧同步字 (区分损坏/加密)"""
import os

DIR = r"D:\musicFor播放器\另起炉灶"


def scan(name):
    p = os.path.join(DIR, name)
    with open(p, "rb") as f:
        data = f.read()
    # ID3v2 tag 大小 (syncsafe)
    if data[:3] == b"ID3":
        tag_size = ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
                    | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
        start = 10 + tag_size
    else:
        start = 0
    # 扫描 MPEG 帧同步: 0xFF 后跟 E0 掩码 (11 个同步位)
    hits = 0
    scan_len = min(len(data) - start, 300_000)
    for i in range(start, start + scan_len - 1):
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            hits += 1
    print(f"{name}: 大小={len(data)}, ID3标签={tag_size}B, "
          f"音频区前{scan_len // 1000}KB 内疑似帧同步 {hits} 次")
    # 真 MP3 (128kbps) 每 ~417 字节一帧, 300KB 应约 700 次
    # 加密数据随机碰撞约 scan_len/2048 ≈ 146 次但无法通过完整帧头校验


scan("Talking to the Moon - Bruno Mars.mp3")
scan("Tell me - milet.mp3")

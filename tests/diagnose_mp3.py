# -*- coding: utf-8 -*-
"""诊断: 批量失败的 MP3 文件头"""
import os

DIR = r"D:\musicFor播放器\另起炉灶"
FILES = [
    "Talking to the Moon - Bruno Mars.mp3",
    "City Hunter (Vantage Edit) - Vantage.mp3",
    "Tell me - milet.mp3",
    "Wild - Monogem.mp3",
    "Welcome Home, Son - Radical Face.mp3",
]

for name in FILES:
    p = os.path.join(DIR, name)
    if not os.path.exists(p):
        # 文件名可能不完全匹配, 模糊找
        cands = [f for f in os.listdir(DIR) if name[:12] in f]
        if not cands:
            print(f"未找到: {name}")
            continue
        p = os.path.join(DIR, cands[0])
        name = cands[0]
    with open(p, "rb") as f:
        head = f.read(32)
        # 再找文件中间位置采样
        f.seek(max(0, os.path.getsize(p) // 2))
        mid = f.read(16)
    print(f"{name}")
    print(f"  大小={os.path.getsize(p)}  头={head[:12].hex(' ')}  "
          f"ASCII={head[:12]!r}")
    print(f"  中部={mid.hex(' ')}")

# -*- coding: utf-8 -*-
"""诊断: 失败文件的文件头/大小/各库识别结果"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DIR = r"D:\musicFor播放器\另起炉灶"

FILES = [
    "10cmヒール - 松原みき.flac",
    "A Cut Above - Audiomachine.mp3",
    "A Lonely Night - The Weeknd.flac",
    "Back In Black - ACDC.flac",
    "All I Am - Jess Glynne.flac",      # 对照组: 成功的
    "Amaretto - Landon Sears.flac",     # 对照组: 成功的
]

for name in FILES:
    p = os.path.join(DIR, name)
    print("=" * 60)
    print(name)
    print("  存在:", os.path.exists(p), " 大小:",
          os.path.getsize(p) if os.path.exists(p) else "N/A")
    if not os.path.exists(p):
        continue
    with open(p, "rb") as f:
        head = f.read(32)
    print("  头部16进制:", head[:16].hex(" "))
    print("  头部ASCII :", repr(head[:16]))
    # soundfile
    try:
        import soundfile as sf
        info = sf.info(p)
        print("  soundfile :", info.format, info.subtype,
              info.samplerate, "Hz", info.channels, "ch")
    except Exception as e:
        print("  soundfile :", "失败 -", e)
    # mutagen
    try:
        import mutagen
        m = mutagen.File(p)
        print("  mutagen   :", type(m).__name__ if m else "无法识别")
    except Exception as e:
        print("  mutagen   :", "失败 -", e)

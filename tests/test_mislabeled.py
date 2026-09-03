# -*- coding: utf-8 -*-
"""回归测试: 用之前失败的真实文件验证 PyAV 兜底与元数据嗅探"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.engine import analyze_file          # noqa: E402
from app.core import metadata as meta_mod         # noqa: E402

DIR = r"D:\musicFor播放器\另起炉灶"
FILES = [
    "10cmヒール - 松原みき.flac",
    "A Cut Above - Audiomachine.mp3",
    "A Lonely Night - The Weeknd.flac",
    "Back In Black - ACDC.flac",
    "A Musical - Brad Oscar、Brian D'Arcy James、'Something Rotten' Ensemble、Wayne Kirkpatrick.flac",
]

for name in FILES:
    p = os.path.join(DIR, name)
    if not os.path.exists(p):
        print(f"跳过(不存在): {name}")
        continue
    rep = analyze_file(p)
    if rep.ok:
        warn = f"  ⚠{rep.warning}" if rep.warning else ""
        print(f"[OK] {name}\n     -> {rep.container} | 判定: {rep.verdict.grade} "
              f"{rep.verdict.score}分{warn}")
    else:
        print(f"[失败] {name}\n     -> {rep.error.splitlines()[0]}")
    m = meta_mod.read_metadata(p)
    print(f"     元数据: {'可读取' if m.ok else m.error}"
          f"  编码={m.codec} 标题={m.tags.get('title', '—')}")

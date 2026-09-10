# -*- coding: utf-8 -*-
"""诊断: In The Lonely Hour 文件夹文件类型与可解码性"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DIR = r"E:\Music\章鱼AM下载\In The Lonely Hour (Drowning Shadows Edition)"

files = []
for root, _, names in os.walk(DIR):
    for n in names:
        files.append(os.path.join(root, n))
print(f"共 {len(files)} 个文件")
for p in sorted(files)[:30]:
    ext = os.path.splitext(p)[1].lower()
    with open(p, "rb") as f:
        head = f.read(2_000_000 if ext in (".m4a", ".mp4") else 16)
    drm = (b"enca" in head or b"encv" in head) and b"sinf" in head
    print(f"{os.path.basename(p)[:55]:<57} {ext:>5} "
          f"{os.path.getsize(p)//1024:>6}KB  头={head[:12]!r}  DRM={'是' if drm else '否'}")

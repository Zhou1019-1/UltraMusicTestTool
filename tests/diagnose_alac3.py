# -*- coding: utf-8 -*-
"""扫描 m4a 中的 alac/stsd 原子, 提取真实编解码配置"""
PATH = r"E:\Music\章鱼AM下载\REQUEST (30th Anniversary Edition) [2017 Remaster]\1-13 Good Bye (Previously Unreleased) [2017 Remaster].m4a"

with open(PATH, "rb") as f:
    head = f.read(2_000_000)  # moov 通常在前面

for tag in (b"stsd", b"alac", b"moov", b"sinf", b"frma", b"drms", b"schi", b"encv", b"enca"):
    offs = []
    start = 0
    while True:
        i = head.find(tag, start)
        if i < 0 or len(offs) >= 5:
            break
        offs.append(i)
        start = i + 1
    print(f"{tag.decode():>5}: 出现于 {offs}")

i = head.find(b"alac")
if i >= 0:
    print("alac 原子上下文:", head[i - 40:i + 80].hex(" "))

# -*- coding: utf-8 -*-
"""诊断: m4a/ALAC 文件解码失败原因"""
import sys

PATH = r"E:\Music\章鱼AM下载\REQUEST (30th Anniversary Edition) [2017 Remaster]\1-13 Good Bye (Previously Unreleased) [2017 Remaster].m4a"

with open(PATH, "rb") as f:
    head = f.read(64)
print("文件头:", head[:32])
print("HEX:", head[:32].hex(" "))

import av
c = av.open(PATH)
for s in c.streams:
    print(f"流: type={s.type} codec={s.codec_context.name} "
          f"sr={getattr(s.codec_context, 'sample_rate', '?')} "
          f"ch={getattr(s.codec_context, 'channels', '?')} "
          f"extradata={'有' if s.codec_context.extradata else '无'}")
print("元数据:", dict(c.metadata))

# 尝试解码第一帧
try:
    for frame in c.decode(audio=0):
        print("解码成功:", frame.samples, "samples @", frame.sample_rate)
        break
except Exception as e:
    print("解码失败:", type(e).__name__, e)
sys.exit(0)

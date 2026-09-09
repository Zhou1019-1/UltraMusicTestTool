# -*- coding: utf-8 -*-
"""手工构造 ALAC magic cookie 作为 extradata, 测试能否解码"""
import struct

import av

PATH = r"E:\Music\章鱼AM下载\REQUEST (30th Anniversary Edition) [2017 Remaster]\1-13 Good Bye (Previously Unreleased) [2017 Remaster].m4a"


def alac_cookie(sample_rate: int, channels: int = 2, bit_depth: int = 16) -> bytes:
    """ALAC Specific Config (24 字节 magic cookie)"""
    return struct.pack(
        ">IBBBB B B H I I I".replace(" ", ""),
        4096,        # frameLength
        0,           # compatibleVersion
        bit_depth,   # bitDepth
        40,          # pb
        10,          # mb
        14,          # kb
        channels,    # numChannels
        255,         # maxRun
        0,           # maxFrameBytes
        0,           # avgBitRate
        sample_rate, # sampleRate
    )


c = av.open(PATH)
st = c.streams.audio[0]
cc = st.codec_context
print("尝试: sr=48000 ch=2 16bit")
cc.extradata = alac_cookie(48000, 2, 16)
try:
    for frame in c.decode(st):
        print(f"解码成功! samples={frame.samples} rate={frame.sample_rate} "
              f"layout={frame.layout.name} format={frame.format.name}")
        break
except Exception as e:
    print("仍失败:", e)

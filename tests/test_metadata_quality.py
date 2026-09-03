# -*- coding: utf-8 -*-
"""
单元测试: 元数据读写 / 质量分析 / 文件名模式解析
用法: python tests/test_metadata_quality.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import metadata as meta_mod           # noqa: E402
from app.core.audio_loader import load_audio        # noqa: E402
from app.core.quality import analyze_quality        # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def t_flac_roundtrip():
    print("== FLAC 标签读写回环 ==")
    src = os.path.join(SAMPLES, "true_16bit_44k.flac")
    tmp = os.path.join(tempfile.mkdtemp(), "t.flac")
    shutil.copy(src, tmp)
    data = {"title": "测试标题", "artist": "章鱼哥", "album": "测试专辑",
            "date": "2026", "genre": "Electronic", "tracknumber": "3",
            "composer": "作曲家A", "comment": "备注文字",
            "lyrics": "第一行歌词\n第二行歌词"}
    meta_mod.write_tags(tmp, data)
    m = meta_mod.read_metadata(tmp)
    check("读取成功", m.ok)
    for k, v in data.items():
        got = m.lyrics if k == "lyrics" else m.tags.get(k, "")
        check(f"字段 {k}", got == v, f"got={got!r}")
    check("标签标准含 Vorbis", any("Vorbis" in s for s in m.tag_standards),
          str(m.tag_standards))
    # 删除字段
    meta_mod.write_tags(tmp, {"title": ""})
    m2 = meta_mod.read_metadata(tmp)
    check("删除字段生效", m2.tags.get("title", "") == "")
    check("技术参数-采样率", m2.sample_rate == 44100, str(m2.sample_rate))


def t_mp3_roundtrip():
    print("== MP3 (ID3v2+ID3v1) 标签读写回环 ==")
    src = os.path.join(SAMPLES, "real_lossy.mp3")
    tmp = os.path.join(tempfile.mkdtemp(), "t.mp3")
    shutil.copy(src, tmp)
    meta_mod.write_tags(tmp, {"title": "海阔天空", "artist": "Beyond",
                              "album": "乐与怒", "date": "1993",
                              "tracknumber": "1"})
    m = meta_mod.read_metadata(tmp)
    check("读取成功", m.ok)
    check("标题", m.tags.get("title") == "海阔天空", m.tags.get("title"))
    check("艺术家", m.tags.get("artist") == "Beyond")
    check("含 ID3v2", any("ID3v2" in s for s in m.tag_standards),
          str(m.tag_standards))


def t_pattern():
    print("== 文件名 <-> 标签 模式解析 ==")
    r = meta_mod.parse_filename_pattern(
        "Beyond - 海阔天空.mp3", "%artist% - %title%")
    check("artist-title 解析",
          r.get("artist") == "Beyond" and r.get("title") == "海阔天空", str(r))
    r2 = meta_mod.parse_filename_pattern(
        "01. 夜曲.flac", "%tracknumber%. %title%")
    check("track-title 解析",
          r2.get("tracknumber") == "01" and r2.get("title") == "夜曲", str(r2))
    r3 = meta_mod.parse_filename_pattern("随便一个名字.mp3",
                                         "%artist% - %title%")
    check("不匹配返回空", r3 == {})


def t_quality():
    print("== 音质维度分析 ==")
    audio = load_audio(os.path.join(SAMPLES, "true_16bit_44k.flac"))
    q = analyze_quality(audio)
    check("峰值合理", -12 < q["peak_dbfs"] <= 0.1, str(q["peak_dbfs"]))
    check("Crest 合理", q["crest_db"] > 3, str(q["crest_db"]))
    check("无削波", q["clipping"] is False)
    check("立体声相关性存在", q["stereo_correlation"] is not None)
    check("指纹长度", len(q["fingerprint"]) == 24, q["fingerprint"])
    check("有评级项", len(q["checks"]) >= 3)
    # 指纹稳定性: 同一文件两次计算一致
    audio2 = load_audio(os.path.join(SAMPLES, "true_16bit_44k.flac"))
    q2 = analyze_quality(audio2)
    check("指纹稳定", q["fingerprint"] == q2["fingerprint"])


def main():
    t_flac_roundtrip()
    t_mp3_roundtrip()
    t_pattern()
    t_quality()
    print("-" * 50)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

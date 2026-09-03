# -*- coding: utf-8 -*-
"""
准确性验证: 用已知真/假样本检验检测器
======================================
用法: python tests/run_verification.py
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.engine import analyze_file  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")

# 样本 -> (期望等级关键词列表, 分数范围)
EXPECT = {
    "true_16bit_44k.flac": (["真无损", "大概率真无损"], (60, 100)),
    "true_16bit.wav": (["真无损", "大概率真无损"], (60, 100)),
    "true_24bit_96k.flac": (["真无损", "大概率真无损", "轻度嫌疑"], (45, 100)),
    "fake_mp3_to_flac.flac": (["假无损", "大概率假无损", "轻度嫌疑"], (0, 64)),
    "fake_16to24bit.flac": (["假无损", "大概率假无损", "轻度嫌疑",
                             "大概率真无损"], (0, 84)),
    "fake_44kto96k.flac": (["假无损", "大概率假无损", "轻度嫌疑"], (0, 64)),
    "real_lossy.mp3": (["有损格式"], (0, 0)),
    "true_dsd64.dsf": (["真无损", "大概率真无损", "轻度嫌疑",
                        "大概率假无损"], (0, 100)),   # DSD 只要求不崩溃且给结论
}


def main():
    files = sorted(glob.glob(os.path.join(SAMPLES, "*.*")))
    if not files:
        print("未找到样本, 先运行: python tests/gen_samples.py")
        return 1

    passed, failed = 0, 0
    print(f"{'样本':<26} {'判定':<12} {'得分':>5}  期望判定")
    print("-" * 78)
    for path in files:
        name = os.path.basename(path)
        rep = analyze_file(path)
        if not rep.ok:
            print(f"{name:<26} [失败] {rep.error}")
            failed += 1
            continue
        grades, (lo, hi) = EXPECT.get(name, (["?"], (0, 100)))
        v = rep.verdict
        ok = v.grade in grades and lo <= v.score <= hi
        mark = "PASS" if ok else "FAIL"
        print(f"{name:<26} {v.grade:<12} {v.score:>5}  {'/'.join(grades):<28} {mark}")
        if ok:
            passed += 1
        else:
            failed += 1
            for r in rep.method_results:
                if r.applicable:
                    print(f"    └ {r.name}: {r.score:.0f}分 {r.summary}")

    print("-" * 78)
    print(f"结果: {passed} 通过, {failed} 未通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

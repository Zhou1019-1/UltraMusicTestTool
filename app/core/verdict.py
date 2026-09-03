# -*- coding: utf-8 -*-
"""
判定融合模块
============
把各检测方法的分数按权重融合为最终判定。
分级沿用 Spek V4.0 标准, 并增加"有损格式"直接判定分支。
"""
from __future__ import annotations

from dataclasses import dataclass, field

GRADE_TABLE = [
    (85, "真无损", "#44FF44", "频谱形态自然, 未检测到转码痕迹"),
    (65, "大概率真无损", "#88FF88", "整体自然, 存在极轻微异常 (可能是音乐风格或母带特性)"),
    (45, "轻度嫌疑", "#FFCC00", "部分指标异常, 建议结合耳听判断"),
    (25, "大概率假无损", "#FF8844", "多项指标符合有损转码/上转换特征"),
    (0, "假无损", "#FF4444", "强烈疑似有损→无损转码或假 Hi-Res"),
]


@dataclass
class Verdict:
    score: float
    grade: str
    color: str
    detail: str
    is_lossy_container: bool = False
    lossy_profile: dict = field(default_factory=dict)


def grade_for_score(score: float):
    for threshold, grade, color, detail in GRADE_TABLE:
        if score >= threshold:
            return grade, color, detail
    return GRADE_TABLE[-1][1], GRADE_TABLE[-1][2], GRADE_TABLE[-1][3]


def fuse(method_results, weights, is_lossy_container=False,
         lossy_profile=None) -> Verdict:
    """
    method_results: list[MethodResult]
    weights: dict method_id -> weight
    """
    if is_lossy_container:
        losses = (lossy_profile or {}).get("losses", [])
        detail = "文件本身为有损编码格式。" + (" ".join(losses[:1]) if losses else "")
        return Verdict(0.0, "有损格式", "#FF4444", detail,
                       is_lossy_container=True,
                       lossy_profile=lossy_profile or {})

    total_w, acc = 0.0, 0.0
    for r in method_results:
        if not r.applicable:
            continue
        w = weights.get(r.method, 1.0) * max(0.2, r.confidence)
        acc += r.score * w
        total_w += w
    score = acc / total_w if total_w > 0 else 50.0

    # 决定性证据盖帽: 单一方法检出强证据时, 不允许被其他方法的高分稀释
    for r in method_results:
        if not r.applicable or r.confidence < 0.75:
            continue
        if r.score <= 40:
            score = min(score, 45.0)    # 强证据 -> 最多"轻度嫌疑"下沿
        elif r.score <= 55:
            score = min(score, 64.0)    # 明确异常 -> 最多"轻度嫌疑"
        elif r.score <= 65:
            score = min(score, 74.0)

    score = max(0.0, min(100.0, score))
    grade, color, detail = grade_for_score(score)
    return Verdict(round(score, 1), grade, color, detail)

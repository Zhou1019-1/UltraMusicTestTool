# -*- coding: utf-8 -*-
"""检测方法基类"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..audio_loader import AudioData


@dataclass
class MethodResult:
    """单个检测方法的输出"""
    method: str                 # 方法标识
    name: str                   # 中文名称
    applicable: bool            # 是否适用于该文件
    score: float = 100.0        # 0-100, 100 = 完全干净/真无损
    confidence: float = 1.0     # 0-1 置信度
    summary: str = ""           # 一句话结论
    deductions: list = field(default_factory=list)  # [(扣分, 原因)]
    metrics: dict = field(default_factory=dict)     # 关键量化指标


class DetectionMethod:
    """所有检测方法实现该接口"""
    method_id = "base"
    name = "基类"
    weight = 1.0                # 融合权重

    def applicable(self, audio: AudioData) -> bool:
        return True

    def analyze(self, audio: AudioData) -> MethodResult:  # pragma: no cover
        raise NotImplementedError

    # ---- 工具: 生成不适用结果 ----
    def _na(self, reason: str) -> MethodResult:
        return MethodResult(self.method_id, self.name, False,
                            summary=f"不适用: {reason}")

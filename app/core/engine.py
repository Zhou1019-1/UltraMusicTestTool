# -*- coding: utf-8 -*-
"""
并行分析引擎
============
- analyze_file(): 单文件完整分析 (加载 -> 多方法检测 -> 融合判定)
  顶层函数, 可跨进程 pickle
- run_batch(): 批量分析, 支持:
    * parallel=True  -> ProcessPoolExecutor 多进程并行 (充分利用多核)
    * parallel=False -> 顺序执行 (作为性能基准对照)
- benchmark(): 同批文件跑两种模式, 输出加速比

注意: Windows + PyInstaller 下使用多进程需要
  multiprocessing.freeze_support() 且入口受 if __name__ == "__main__" 保护
  (见 app/main.py)
"""
from __future__ import annotations

import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

from .audio_loader import AudioLoadError, load_audio
from .lossy_profile import analyze_lossy
from .methods import ALL_METHODS
from .quality import analyze_quality
from .verdict import Verdict, fuse

_METHODS = [cls() for cls in ALL_METHODS]
_WEIGHTS = {m.method_id: m.weight for m in _METHODS}


@dataclass
class FileReport:
    """单文件完整分析报告"""
    path: str
    ok: bool = False
    error: str = ""
    container: str = ""
    subtype: str = ""
    samplerate: int = 0
    channels: int = 0
    duration: float = 0.0
    bit_depth: int = 0
    method_results: list = field(default_factory=list)
    warning: str = ""
    verdict: Verdict = None
    elapsed: float = 0.0

    def to_text(self) -> str:
        """导出文本报告"""
        lines = [f"文件: {self.path}"]
        if self.warning:
            lines.append(f"警告: {self.warning}")
        if not self.ok:
            lines.append(f"分析失败: {self.error}")
            return "\n".join(lines)
        v = self.verdict
        lines += [
            f"格式: {self.container} / {self.subtype}  "
            f"{self.samplerate}Hz {self.channels}ch  "
            f"位深 {self.bit_depth}bit  时长 {self.duration:.1f}s",
            f"最终判定: 【{v.grade}】 综合得分 {v.score}/100",
            f"说明: {v.detail}",
        ]
        if v.is_lossy_container and v.lossy_profile:
            lines.append("── 有损画像 (损在哪) ──")
            for s in v.lossy_profile.get("losses", []):
                lines.append(f"  · {s}")
        if self.quality:
            q = self.quality
            lines.append("── 音质维度 ──")
            lines.append(
                f"  峰值 {q.get('peak_dbfs', '?')} dBFS  "
                f"RMS {q.get('rms_dbfs', '?')} dBFS  "
                f"Crest {q.get('crest_db', '?')} dB  "
                f"动态范围 {q.get('dynamic_range_db', '?')} dB  "
                f"削波 {'是' if q.get('clipping') else '否'}")
            corr = q.get("stereo_correlation")
            if corr is not None:
                lines.append(f"  立体声相关性: {corr}")
            lines.append(f"  音频指纹: {q.get('fingerprint', 'N/A')}")
            for name, grade, desc in q.get("checks", []):
                lines.append(f"  [{grade.upper()}] {name}: {desc}")
        lines.append("── 各检测方法明细 ──")
        for r in self.method_results:
            if not r.applicable:
                lines.append(f"  [{r.name}] 不适用 - {r.summary}")
                continue
            lines.append(f"  [{r.name}] 得分 {r.score:.0f}/100 - {r.summary}")
            for pts, reason in r.deductions:
                lines.append(f"      [-{pts}] {reason}")
            if r.metrics:
                kv = "  ".join(f"{k}={val}" for k, val in r.metrics.items())
                lines.append(f"      指标: {kv}")
        return "\n".join(lines)


def analyze_file(path: str) -> FileReport:
    """单文件分析入口 (子进程工作函数)"""
    t0 = time.perf_counter()
    rep = FileReport(path=path)
    try:
        audio = load_audio(path)
        rep.container = audio.container
        rep.subtype = audio.subtype
        rep.samplerate = audio.samplerate
        rep.channels = audio.channels
        rep.duration = round(audio.duration, 2)
        rep.bit_depth = audio.bit_depth
        rep.warning = audio.extra.get("warning", "")

        if audio.is_lossy_container:
            # 有损容器: 直接判定 + "损在哪"画像
            profile = analyze_lossy(audio)
            rep.verdict = fuse([], _WEIGHTS, is_lossy_container=True,
                               lossy_profile=profile)
        else:
            results = [m.analyze(audio) for m in _METHODS]
            rep.method_results = results
            rep.verdict = fuse(results, _WEIGHTS)
        # 音质维度 (动态范围/削波/立体声相关性/指纹) 对所有容器生效
        rep.quality = analyze_quality(audio)
        rep.ok = True
    except AudioLoadError as e:
        rep.error = str(e)
    except MemoryError:
        rep.error = ("内存不足: 系统可用虚拟内存耗尽。"
                     "请关闭其他程序, 或在系统设置中开启虚拟内存(页面文件)后重试")
    except Exception as e:  # 兜底, 防止单个文件搞崩整批
        rep.error = f"内部错误: {e}\n{traceback.format_exc(limit=3)}"
    rep.elapsed = round(time.perf_counter() - t0, 2)
    return rep


def _available_virtual_bytes() -> int:
    """系统剩余可提交虚拟内存 (Windows; 失败时返回足够大值)"""
    try:
        import ctypes

        class MEMSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        s = MEMSTATUSEX()
        s.dwLength = ctypes.sizeof(MEMSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        # ullAvailPageFile = 提交限额余量 (RAM+页面文件 中还可提交的部分)
        return int(s.ullAvailPageFile)
    except Exception:  # noqa: BLE001
        return 8 * 1024**3


# 每个分析进程的保守峰值内存估计 (大体积 Hi-Res 文件 STFT 峰值)
_WORKER_PEAK_BYTES = 1536 * 1024**2  # 1.5GB


def default_workers() -> int:
    cpu = os.cpu_count() or 4
    by_cpu = max(1, min(cpu - 1, 8))
    # 按可用虚拟内存限制并行度, 防止批量分析时整体 OOM
    by_mem = max(1, int(_available_virtual_bytes() * 0.8
                        // _WORKER_PEAK_BYTES))
    return max(1, min(by_cpu, by_mem))


def run_batch(paths, parallel=True, max_workers=None, progress_cb=None):
    """
    批量分析
    返回 (reports: list[FileReport], elapsed: float)
    progress_cb(done, total, path) 可选进度回调 (仅主进程内调用)
    """
    t0 = time.perf_counter()
    reports = [None] * len(paths)

    if parallel and len(paths) > 1:
        workers = max_workers or default_workers()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            fut_map = {pool.submit(analyze_file, p): i
                       for i, p in enumerate(paths)}
            done = 0
            for fut in as_completed(fut_map):
                i = fut_map[fut]
                try:
                    reports[i] = fut.result()
                except Exception as e:  # 子进程崩溃兜底
                    reports[i] = FileReport(path=paths[i], ok=False,
                                            error=f"子进程异常: {e}")
                done += 1
                if progress_cb:
                    progress_cb(done, len(paths), paths[i])
    else:
        for i, p in enumerate(paths):
            reports[i] = analyze_file(p)
            if progress_cb:
                progress_cb(i + 1, len(paths), p)

    return reports, time.perf_counter() - t0


def benchmark(paths, max_workers=None, progress_cb=None):
    """
    性能基准: 顺序 vs 并行
    返回 dict(seq_time, par_time, speedup, workers)
    """
    _, seq_time = run_batch(paths, parallel=False, progress_cb=None)
    workers = max_workers or default_workers()
    _, par_time = run_batch(paths, parallel=True, max_workers=workers,
                            progress_cb=progress_cb)
    speedup = seq_time / par_time if par_time > 0 else 0.0
    return {
        "seq_time": round(seq_time, 2),
        "par_time": round(par_time, 2),
        "speedup": round(speedup, 2),
        "workers": workers,
        "files": len(paths),
    }

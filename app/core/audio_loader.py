# -*- coding: utf-8 -*-
"""
音频加载模块
============
支持格式:
  - 无损容器: WAV / FLAC / AIFF / DSF(DSD64/128/256, 1bit)
  - 有损容器: MP3 / OGG(Vorbis) / OPUS / 其他 libsndfile 可解码格式
  - DFF(DSDIFF) 暂不支持解码, 给出明确错误提示

设计要点:
  - 所有解码输出 float64 [-1, 1], 不做任何重采样/音量处理 -> 零质量损耗
  - 记录容器位深 (subtype) 供位深检测方法使用
  - DSF 通过内置极简解析器解码: 1bit PDM -> 移动平均抽取 -> PCM
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

import numpy as np

# libsndfile 中属于有损编码的容器/编码标识
LOSSY_FORMATS = {"MP3", "OGG", "OPUS", "MPEG", "WMA", "MP4", "AAC", "VORBIS"}
LOSSY_EXTS = {".mp3", ".ogg", ".opus", ".wma", ".m4a", ".aac", ".mp4", ".webm"}

# 容器位深映射 (libsndfile subtype)
SUBTYPE_BITS = {
    "PCM_S8": 8, "PCM_U8": 8,
    "PCM_16": 16, "PCM_24": 24, "PCM_32": 32,
    "FLOAT": 32, "DOUBLE": 64,
    "DPCM_8": 8, "DPCM_16": 16,
}

SUPPORTED_EXTS = {".wav", ".flac", ".aiff", ".aif", ".aifc",
                  ".mp3", ".ogg", ".opus", ".dsf", ".dff",
                  ".m4a", ".aac", ".mp4", ".wma", ".ape"}

# FFmpeg 编码名 -> 有损判定 (PyAV 兜底解码时使用)
LOSSY_CODECS = {"mp3", "mp2", "aac", "vorbis", "opus", "wmav1", "wmav2",
                "musepack7", "musepack8", "wmapro", "cook", "sipr"}


def sniff_container(path: str) -> str:
    """按文件头魔数嗅探真实容器 (不信任扩展名), 返回大写容器名或空串"""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return ""
    if head[:4] == b"fLaC":
        return "FLAC"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "WAV"
    if head[:4] == b"FORM":
        return "AIFF"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF
                              and (head[1] & 0xE0) == 0xE0):
        return "MP3"
    if head[4:8] == b"ftyp":
        return "MP4"
    if head[:4] == b"OggS":
        return "OGG"
    if head[:4] == b"MAC ":
        return "APE"
    if head[:4] == b"DSD ":
        return "DSF"
    if head[:16].hex().upper().startswith("3026B2758E66CF11"):
        return "ASF"
    return ""


class AudioLoadError(Exception):
    """音频加载失败"""


@dataclass
class AudioData:
    """统一的音频数据表示 (所有检测方法的输入)"""
    path: str
    samples: np.ndarray          # shape (frames, channels), float64 [-1,1]
    samplerate: int
    channels: int
    container: str               # WAV / FLAC / MP3 / DSF ...
    subtype: str                 # PCM_16 / PCM_24 ...
    bit_depth: int               # 容器声明位深
    duration: float              # 秒
    is_lossy_container: bool     # 有损容器直接判定
    file_size: int = 0
    extra: dict = field(default_factory=dict)   # dsf 原始采样率等

    @property
    def mono(self) -> np.ndarray:
        if self.channels == 1:
            return self.samples[:, 0]
        return self.samples.mean(axis=1)

    @property
    def estimated_bitrate_kbps(self) -> float:
        if self.duration <= 0:
            return 0.0
        return self.file_size * 8.0 / self.duration / 1000.0


def is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTS


def load_audio(path: str) -> AudioData:
    """加载任意受支持的音频文件, 失败抛 AudioLoadError"""
    ext = os.path.splitext(path)[1].lower()
    if not os.path.isfile(path):
        raise AudioLoadError(f"文件不存在: {path}")
    if ext == ".dff":
        raise AudioLoadError("DFF (DSDIFF) 暂不支持, 请转换为 DSF 后重试")
    if ext == ".dsf":
        return _load_dsf(path)
    if not is_supported(path):
        raise AudioLoadError(f"不支持的格式: {ext}")
    return _load_soundfile(path)


def _load_soundfile(path: str) -> AudioData:
    try:
        import soundfile as sf
    except ImportError as e:  # pragma: no cover
        raise AudioLoadError("缺少 soundfile 组件") from e
    try:
        info = sf.info(path)
        data, sr = sf.read(path, dtype="float64", always_2d=True)
    except Exception as e:
        # libsndfile 解不开 (如伪装扩展名的 MP4/AAC) -> PyAV(FFmpeg) 兜底
        return _load_pyav(path, sf_error=str(e))

    fmt = (info.format or "").upper()
    subtype = (info.subtype or "").upper()
    ext = os.path.splitext(path)[1].lower()
    is_lossy = fmt in LOSSY_FORMATS or ext in LOSSY_EXTS
    bit_depth = SUBTYPE_BITS.get(subtype, 16)

    extra = _mismatch_note(path, fmt)
    frames = data.shape[0]
    duration = frames / float(sr) if sr else 0.0
    return AudioData(
        path=path, samples=data, samplerate=int(sr),
        channels=data.shape[1], container=fmt, subtype=subtype,
        bit_depth=bit_depth, duration=duration,
        is_lossy_container=is_lossy, file_size=os.path.getsize(path),
        extra=extra,
    )


def _mismatch_note(path: str, detected_container: str) -> dict:
    """扩展名与实际容器不符时生成提示"""
    real = sniff_container(path)
    ext = os.path.splitext(path)[1].lower().lstrip(".").upper()
    if real and ext and real != ext and not (
            ext == "MP3" and real == "MP3"):
        return {"warning": f"扩展名(.{ext.lower()})与实际内容({real})不符"}
    return {}


def _load_pyav(path: str, sf_error: str = "") -> AudioData:
    """PyAV(FFmpeg) 兜底解码: 支持 AAC/M4A/WMA/APE 等 libsndfile 不认的格式"""
    try:
        import av
    except ImportError as e:  # pragma: no cover
        raise AudioLoadError(f"解码失败: {sf_error} (且无 PyAV 兜底)") from e
    try:
        container = av.open(path)
    except Exception as e:
        raise AudioLoadError(
            f"解码失败: {e} (文件损坏、被平台加密或内容并非音频)") from e

    stream = next((s for s in container.streams if s.type == "audio"), None)
    if stream is None:
        container.close()
        raise AudioLoadError("文件中没有音频流")

    codec = (stream.codec_context.name or "").lower()
    sr = int(stream.codec_context.sample_rate or 44100)
    channels = int(stream.codec_context.channels or 2)

    resampler = av.AudioResampler(format="fltp")
    chunks = []
    try:
        for frame in container.decode(stream):
            for r in resampler.resample(frame):
                arr = np.asarray(r.to_ndarray(), dtype=np.float64)
                chunks.append(arr)
        for r in resampler.resample(None):  # 冲刷重采样器尾部
            chunks.append(np.asarray(r.to_ndarray(), dtype=np.float64))
    finally:
        container.close()
    if not chunks:
        raise AudioLoadError("解码结果为空 (文件损坏)")

    data = np.concatenate(chunks, axis=1).T  # (frames, channels)
    fmt = sniff_container(path) or os.path.splitext(path)[1].upper().lstrip(".")
    frames = data.shape[0]
    duration = frames / float(sr) if sr else 0.0
    extra = _mismatch_note(path, fmt)
    extra["decoded_by"] = "FFmpeg"
    return AudioData(
        path=path, samples=data, samplerate=sr, channels=data.shape[1],
        container=f"{fmt}/{codec.upper()}", subtype="",
        bit_depth=0 if codec in LOSSY_CODECS else 16,
        duration=duration,
        is_lossy_container=codec in LOSSY_CODECS,
        file_size=os.path.getsize(path), extra=extra,
    )


# ═══════════════════════════════════════════════════════════
# DSF (DSD) 极简解码器
# ═══════════════════════════════════════════════════════════
def _load_dsf(path: str) -> AudioData:
    """解析 DSF: DSD 1bit PDM -> 移动平均抽取到 PCM (约44.1k/48k)"""
    with open(path, "rb") as f:
        blob = f.read()
    if blob[0:4] != b"DSD ":
        raise AudioLoadError("不是合法的 DSF 文件")

    # ---- DSD chunk ----
    file_size = struct.unpack_from("<Q", blob, 12)[0]

    # ---- fmt chunk ----
    pos = 28
    if blob[pos:pos + 4] != b"fmt ":
        raise AudioLoadError("DSF 缺少 fmt 块")
    # 字段布局: version@12 format_id@16 channel_type@20 channels@24
    #           samplerate@28 bits@32 sample_count@36 block_size@44 reserved@48
    channels = struct.unpack_from("<I", blob, pos + 24)[0]
    dsd_rate = struct.unpack_from("<I", blob, pos + 28)[0]     # 2822400 等
    bits = struct.unpack_from("<I", blob, pos + 32)[0]         # 1 或 8
    sample_count = struct.unpack_from("<Q", blob, pos + 36)[0]
    block_size = struct.unpack_from("<I", blob, pos + 44)[0]   # 通常 4096 字节/声道

    # ---- data chunk ----
    # fmt 数据部分固定 40 字节; chunk size 字段存在 52(含头)/40(仅数据) 两种写法,
    # 直接在 fmt 之后的短窗口内搜索 "data" 标识, 兼容两种实现
    search_from = pos + 12 + 40
    idx = blob.find(b"data", search_from - 16, search_from + 64)
    if idx < 0:
        raise AudioLoadError("DSF 缺少 data 块")
    data_start = idx + 12
    data_end = min(int(file_size), len(blob))
    raw = blob[data_start:data_end]

    if channels < 1 or channels > 8:
        raise AudioLoadError(f"DSF 声道数异常: {channels}")

    # 数据按 block_size 字节每声道交错排列
    n_blocks = len(raw) // (block_size * channels)
    chan_bytes = [bytearray() for _ in range(channels)]
    for b in range(n_blocks):
        base = b * block_size * channels
        for c in range(channels):
            off = base + c * block_size
            chan_bytes[c] += raw[off:off + block_size]

    # 1bit PDM -> ±1, 移动平均抽取到 ~44.1kHz
    decim = max(1, round(dsd_rate / 44100))
    out_sr = dsd_rate / decim
    pcm = np.zeros((n_blocks * block_size * 8 // decim, channels), dtype=np.float64)
    for c in range(channels):
        arr = np.frombuffer(bytes(chan_bytes[c]), dtype=np.uint8)
        bits_arr = np.unpackbits(arr)              # MSB first, 符合 DSF 规范
        sig = bits_arr.astype(np.float64) * 2 - 1  # 1->+1, 0->-1
        n = (len(sig) // decim) * decim
        pcm[:, c] = sig[:n].reshape(-1, decim).mean(axis=1)

    duration = sample_count / float(dsd_rate) if dsd_rate else 0.0
    return AudioData(
        path=path, samples=pcm, samplerate=int(round(out_sr)),
        channels=channels, container="DSF(DSD)", subtype="DSD-1BIT",
        bit_depth=1, duration=duration, is_lossy_container=False,
        file_size=os.path.getsize(path),
        extra={"dsd_rate": dsd_rate, "bits_per_sample": bits,
               "note": "DSD 已抽取为 PCM 进行分析"},
    )

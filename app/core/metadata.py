# -*- coding: utf-8 -*-
"""
统一元数据层 (基于 mutagen)
===========================
- read_metadata(): 跨格式读取 标题/艺术家/专辑/.../歌词/封面/技术参数
- write_tags():    跨格式写回常用字段
- set_cover():     设置/替换封面 (MP3/FLAC/MP4)
- get_cover():     提取封面字节流
- detect_tag_standards(): 检测文件中存在的标签标准 (ID3v1/ID3v2/APEv2/VorbisComment...)
- delete_all_tags(): 清除全部标签

支持: MP3(ID3v1/v2) FLAC/Ogg(Vorbis Comment) MP4/M4A AAC ASF/WMA WAV/AIFF(ID3) DSF(ID3) APE(APEv2)
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass, field

import mutagen
from mutagen.asf import ASF, ASFUnicodeAttribute
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (APIC, COMM, ID3, ID3NoHeaderError, TALB, TCOM, TCON,
                         TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, USLT)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from .audio_loader import sniff_container


def _open(path: str):
    """按文件头魔数强制选择解析器, 兼容"扩展名与真实内容不符"的文件"""
    kind = sniff_container(path)
    forced = []
    if kind == "FLAC":
        forced = [FLAC]
    elif kind == "MP3":
        forced = [MP3]
    elif kind == "MP4":
        forced = [MP4]
    elif kind == "ASF":
        forced = [ASF]
    elif kind == "OGG":
        forced = [OggVorbis, OggOpus]
    elif kind == "WAV":
        from mutagen.wave import WAVE
        forced = [WAVE]
    elif kind == "AIFF":
        from mutagen.aiff import AIFF
        forced = [AIFF]
    elif kind == "DSF":
        from mutagen.dsf import DSF
        forced = [DSF]
    elif kind == "APE":
        from mutagen.monkeysaudio import MonkeysAudio
        forced = [MonkeysAudio]
    for cls in forced:
        try:
            audio = cls(path)
            if audio is not None:
                return audio
        except Exception:  # noqa: BLE001
            continue
    return mutagen.File(path)

# 统一字段名 (UI 与批量编辑共用)
FIELDS = ["title", "artist", "album", "albumartist", "date", "genre",
          "tracknumber", "discnumber", "composer", "comment"]
FIELD_NAMES = {
    "title": "标题", "artist": "艺术家", "album": "专辑",
    "albumartist": "专辑艺术家", "date": "年代", "genre": "流派",
    "tracknumber": "音轨号", "discnumber": "碟片号",
    "composer": "作曲", "comment": "备注",
}

_ID3_MAP = {"title": TIT2, "artist": TPE1, "album": TALB,
            "albumartist": TPE2, "date": TDRC, "genre": TCON,
            "tracknumber": TRCK, "discnumber": TPOS, "composer": TCOM}
_VORBIS_MAP = {k: k for k in FIELDS}
_MP4_MAP = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
            "albumartist": "aART", "date": "\xa9day", "genre": "\xa9gen",
            "composer": "\xa9wrt", "comment": "\xa9cmt"}
_ASF_MAP = {"title": "WM/Title", "artist": "WM/Author",
            "album": "WM/AlbumTitle", "albumartist": "WM/AlbumArtist",
            "date": "WM/Year", "genre": "WM/Genre",
            "tracknumber": "WM/TrackNumber", "discnumber": "WM/PartOfSet",
            "composer": "WM/Composer", "comment": "WM/Comments"}


@dataclass
class AudioMeta:
    """统一元数据结构"""
    path: str = ""
    ok: bool = False
    error: str = ""
    tags: dict = field(default_factory=dict)       # 统一字段 -> str
    lyrics: str = ""
    has_cover: bool = False
    cover_mime: str = ""
    tag_standards: list = field(default_factory=list)  # ["ID3v2.3", "ID3v1.1"]
    raw: list = field(default_factory=list)        # [(key, value)] 全部原始标签
    # 技术参数
    codec: str = ""
    sample_rate: int = 0
    channels: int = 0
    bit_depth: int = 0
    bitrate: int = 0          # bps
    duration: float = 0.0
    file_size: int = 0


# ═════════════════════════ 读取 ═════════════════════════

def read_metadata(path: str) -> AudioMeta:
    """读取任意受支持音频文件的元数据 (不含封面字节, 封面用 get_cover 按需取)"""
    meta = AudioMeta(path=path)
    meta.file_size = os.path.getsize(path)
    try:
        audio = _open(path)
    except Exception as e:
        meta.error = f"无法解析: {e}"
        return meta
    if audio is None:
        meta.error = "无法识别的格式"
        return meta

    meta.ok = True
    _read_technical(audio, meta)
    meta.tag_standards = detect_tag_standards(path, audio)

    try:
        if isinstance(audio, MP4):
            _read_mp4(audio, meta)
        elif isinstance(audio, ASF):
            _read_asf(audio, meta)
        elif isinstance(audio, (FLAC, OggVorbis, OggOpus)):
            _read_vorbis(audio, meta)
        elif hasattr(audio, "tags") and isinstance(audio.tags, ID3):
            _read_id3(audio.tags, meta)
        elif audio.tags is None and _id3_capable(path):
            pass  # 无标签
        elif audio.tags is not None:
            _read_generic(audio.tags, meta)
    except Exception as e:  # noqa: BLE001
        meta.error = f"标签读取异常: {e}"

    # 封面探测
    try:
        meta.has_cover, meta.cover_mime = _probe_cover(audio)
    except Exception:  # noqa: BLE001
        pass
    return meta


def _read_technical(audio, meta: AudioMeta):
    info = getattr(audio, "info", None)
    if info is None:
        return
    meta.codec = type(audio).__name__
    meta.sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    meta.channels = int(getattr(info, "channels", 0) or 0)
    meta.bitrate = int(getattr(info, "bitrate", 0) or 0)
    meta.duration = round(float(getattr(info, "length", 0.0) or 0.0), 2)
    meta.bit_depth = int(getattr(info, "bits_per_sample", 0) or 0)


def _first(v) -> str:
    if isinstance(v, (list, tuple)):
        return str(v[0]) if v else ""
    return str(v)


def _read_id3(tags: ID3, meta: AudioMeta):
    for key, cls in _ID3_MAP.items():
        frame = tags.get(cls.__name__)
        if frame is not None:
            meta.tags[key] = str(frame)
    comm = tags.get("COMM::eng") or next(
        (f for f in tags.getall("COMM")), None)
    if comm:
        meta.tags["comment"] = str(comm)
    uslt = tags.get("USLT::eng") or next(
        (f for f in tags.getall("USLT")), None)
    if uslt:
        meta.lyrics = str(uslt)
    meta.raw = [(f.FrameID, str(f)) for f in tags.values()]


def _read_vorbis(audio, meta: AudioMeta):
    tags = audio.tags or {}
    for key in FIELDS:
        if key in tags:
            meta.tags[key] = _first(tags[key])
    for lk in ("lyrics", "LYRICS", "unsyncedlyrics"):
        if lk in tags:
            meta.lyrics = _first(tags[lk])
            break
    meta.raw = [(k, _first(v)) for k, v in tags.items()]


def _read_mp4(audio: MP4, meta: AudioMeta):
    tags = audio.tags or {}
    for key, atom in _MP4_MAP.items():
        if atom in tags:
            meta.tags[key] = _first(tags[atom])
    if "trkn" in tags and tags["trkn"]:
        n, total = tags["trkn"][0]
        meta.tags["tracknumber"] = f"{n}/{total}" if total else str(n)
    if "disk" in tags and tags["disk"]:
        n, total = tags["disk"][0]
        meta.tags["discnumber"] = f"{n}/{total}" if total else str(n)
    if "\xa9lyr" in tags:
        meta.lyrics = _first(tags["\xa9lyr"])
    meta.raw = [(k, _first(v)[:200]) for k, v in tags.items()
                if k != "covr"]


def _read_asf(audio: ASF, meta: AudioMeta):
    tags = audio.tags or {}
    for key, wmk in _ASF_MAP.items():
        if wmk in tags:
            meta.tags[key] = _first(tags[wmk])
    if "WM/Lyrics" in tags:
        meta.lyrics = _first(tags["WM/Lyrics"])
    meta.raw = [(k, _first(v)[:200]) for k, v in tags.items()]


def _read_generic(tags, meta: AudioMeta):
    """APEv2 等其他 dict 风格标签"""
    for key in FIELDS:
        for cand in (key, key.capitalize(), key.upper()):
            if cand in tags:
                meta.tags[key] = _first(tags[cand])
                break
    try:
        meta.raw = [(k, _first(v)[:200]) for k, v in tags.items()]
    except Exception:  # noqa: BLE001
        pass


def _probe_cover(audio) -> tuple[bool, str]:
    if isinstance(audio, MP4):
        covr = (audio.tags or {}).get("covr")
        if covr:
            fmt = covr[0].imageformat
            return True, ("image/png" if fmt == MP4Cover.FORMAT_PNG
                          else "image/jpeg")
        return False, ""
    if isinstance(audio, FLAC):
        if audio.pictures:
            return True, audio.pictures[0].mime
        return False, ""
    if isinstance(audio, (OggVorbis, OggOpus)):
        tags = audio.tags or {}
        if tags.get("metadata_block_picture"):
            return True, "image/*"
        return False, ""
    if isinstance(audio, ASF):
        for v in (audio.tags or {}).get("WM/Picture", []):
            if hasattr(v, "data"):
                return True, getattr(v, "mime", "image/*")
        return False, ""
    tags = getattr(audio, "tags", None)
    if isinstance(tags, ID3):
        apics = tags.getall("APIC")
        if apics:
            return True, apics[0].mime
    return False, ""


def get_cover(path: str) -> tuple[bytes, str]:
    """提取封面 -> (图片字节, mime)。无封面/无法解析返回 (b"", "")"""
    try:
        audio = _open(path)
    except Exception:  # noqa: BLE001
        return b"", ""
    if audio is None:
        return b"", ""
    if isinstance(audio, MP4):
        covr = (audio.tags or {}).get("covr")
        if covr:
            mime = ("image/png" if covr[0].imageformat == MP4Cover.FORMAT_PNG
                    else "image/jpeg")
            return bytes(covr[0]), mime
    elif isinstance(audio, FLAC):
        if audio.pictures:
            return audio.pictures[0].data, audio.pictures[0].mime
    elif isinstance(audio, (OggVorbis, OggOpus)):
        vals = (audio.tags or {}).get("metadata_block_picture")
        if vals:
            pic = Picture(base64.b64decode(vals[0]))
            return pic.data, pic.mime
    elif isinstance(audio, ASF):
        for v in (audio.tags or {}).get("WM/Picture", []):
            if hasattr(v, "data"):
                return bytes(v.data), getattr(v, "mime", "image/jpeg")
    else:
        tags = getattr(audio, "tags", None)
        if isinstance(tags, ID3):
            apics = tags.getall("APIC")
            if apics:
                return apics[0].data, apics[0].mime
    return b"", ""


# ═════════════════════════ 写入 ═════════════════════════

def write_tags(path: str, changes: dict):
    """
    写回统一字段 (changes: {field: str}, 空字符串表示删除该字段)。
    自动按格式路由到 ID3v2.3(+ID3v1) / Vorbis Comment / MP4 atom / ASF / APEv2。
    """
    audio = _open(path)
    if audio is None:
        raise ValueError("无法识别的格式，无法写入标签")

    if isinstance(audio, MP4):
        _write_mp4(audio, changes)
    elif isinstance(audio, ASF):
        _write_asf(audio, changes)
    elif isinstance(audio, (FLAC, OggVorbis, OggOpus)):
        _write_vorbis(audio, changes)
    elif _id3_capable(path):
        _write_id3_file(audio, path, changes)
    elif audio is not None and hasattr(audio, "tags"):
        _write_generic(audio, changes)
    else:
        raise ValueError("该格式不支持标签写入")


def _write_id3_file(audio, path: str, changes: dict):
    tags = getattr(audio, "tags", None)
    if not isinstance(tags, ID3):
        tags = ID3()
    for key, value in changes.items():
        if key == "lyrics":
            if value:
                tags.setall("USLT", [USLT(encoding=3, lang="eng",
                                          desc="", text=value)])
            else:
                tags.delall("USLT")
            continue
        if key == "comment":
            if value:
                tags.setall("COMM", [COMM(encoding=3, lang="eng",
                                          desc="", text=value)])
            else:
                tags.delall("COMM")
            continue
        cls = _ID3_MAP.get(key)
        if cls is None:
            continue
        fid = cls.__name__
        if value:
            tags.setall(fid, [cls(encoding=3, text=value)])
        else:
            tags.delall(fid)
    # v2.3 兼容性最好, v1=2 同步更新已存在的 ID3v1
    tags.save(path, v2_version=3, v1=2)


def _write_vorbis(audio, changes: dict):
    if audio.tags is None:
        audio.add_tags()
    for key, value in changes.items():
        if value:
            audio.tags[key] = [value]
        elif key in audio.tags:
            del audio.tags[key]
    audio.save()


def _write_mp4(audio: MP4, changes: dict):
    if audio.tags is None:
        audio.add_tags()
    for key, value in changes.items():
        if key == "lyrics":
            atom = "\xa9lyr"
        elif key == "tracknumber":
            atom = "trkn"
        elif key == "discnumber":
            atom = "disk"
        else:
            atom = _MP4_MAP.get(key)
        if atom is None:
            continue
        if atom in ("trkn", "disk"):
            if value:
                n, _, total = value.partition("/")
                audio.tags[atom] = [(int(n or 0), int(total or 0))]
            elif atom in audio.tags:
                del audio.tags[atom]
        elif value:
            audio.tags[atom] = [value]
        elif atom in audio.tags:
            del audio.tags[atom]
    audio.save()


def _write_asf(audio: ASF, changes: dict):
    for key, value in changes.items():
        wmk = "WM/Lyrics" if key == "lyrics" else _ASF_MAP.get(key)
        if wmk is None:
            continue
        if value:
            audio.tags[wmk] = [ASFUnicodeAttribute(value)]
        elif wmk in audio.tags:
            del audio.tags[wmk]
    audio.save()


def _write_generic(audio, changes: dict):
    if audio.tags is None:
        audio.add_tags()
    for key, value in changes.items():
        if value:
            audio.tags[key] = value
        elif key in audio.tags:
            del audio.tags[key]
    audio.save()


def set_cover(path: str, image_path: str):
    """设置/替换封面 (MP3/FLAC/MP4; OGG 走 Vorbis 图片块)"""
    with open(image_path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"

    audio = _open(path)
    if audio is None:
        raise ValueError("无法识别的格式")
    if isinstance(audio, FLAC):
        audio.clear_pictures()
        pic = Picture()
        pic.type, pic.mime, pic.desc, pic.data = 3, mime, "", data
        audio.add_picture(pic)
        audio.save()
    elif isinstance(audio, MP4):
        if audio.tags is None:
            audio.add_tags()
        fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
        audio.save()
    elif isinstance(audio, (OggVorbis, OggOpus)):
        pic = Picture()
        pic.type, pic.mime, pic.desc, pic.data = 3, mime, "", data
        audio.tags["metadata_block_picture"] = [
            base64.b64encode(pic.write()).decode("ascii")]
        audio.save()
    elif _id3_capable(path):
        tags = getattr(audio, "tags", None)
        if not isinstance(tags, ID3):
            tags = ID3()
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="", data=data))
        tags.save(path, v2_version=3, v1=2)
    else:
        raise ValueError("该格式暂不支持封面写入")


def remove_cover(path: str):
    """移除封面"""
    audio = _open(path)
    if audio is None:
        return
    if isinstance(audio, FLAC):
        audio.clear_pictures()
        audio.save()
    elif isinstance(audio, MP4):
        (audio.tags or {}).pop("covr", None)
        audio.save()
    elif isinstance(audio, (OggVorbis, OggOpus)):
        if "metadata_block_picture" in (audio.tags or {}):
            del audio.tags["metadata_block_picture"]
        audio.save()
    else:
        tags = getattr(audio, "tags", None)
        if isinstance(tags, ID3):
            tags.delall("APIC")
            tags.save(path, v2_version=3, v1=2)


def delete_all_tags(path: str):
    """清除文件全部标签"""
    audio = _open(path)
    if audio is not None:
        audio.delete()


# ═══════════════════ 标签标准检测 ═══════════════════

def _id3_capable(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in (
        ".mp3", ".wav", ".aiff", ".aif", ".dsf", ".dff")


def detect_tag_standards(path: str, audio=None) -> list:
    """检测文件实际包含的标签标准"""
    standards = []
    ext = os.path.splitext(path)[1].lower()

    if ext == ".mp3":
        try:
            with open(path, "rb") as f:
                head = f.read(10)
                if head[:3] == b"ID3":
                    ver = head[3]
                    standards.append(f"ID3v2.{ver}")
                f.seek(-128, os.SEEK_END)
                if f.read(3) == b"TAG":
                    standards.append("ID3v1")
                f.seek(0)
                tail = f.read()[-4096:] if os.path.getsize(path) > 4096 else b""
                if b"APETAGEX" in tail:
                    standards.append("APEv2")
        except OSError:
            pass
        return standards or ["无标签"]

    if audio is None:
        try:
            audio = _open(path)
        except Exception:  # noqa: BLE001
            return []
    if isinstance(audio, (FLAC, OggVorbis, OggOpus)):
        if audio.tags:
            standards.append("Vorbis Comment")
        if isinstance(audio, FLAC) and audio.pictures:
            standards.append("FLAC Picture")
    elif isinstance(audio, MP4):
        if audio.tags:
            standards.append("MP4 Atom")
    elif isinstance(audio, ASF):
        if audio.tags:
            standards.append("ASF/WMA")
    elif isinstance(getattr(audio, "tags", None), ID3):
        standards.append("ID3v2")
    elif getattr(audio, "tags", None):
        standards.append(type(audio.tags).__name__.replace("APETag", "APEv2"))
    return standards or ["无标签"]


def parse_filename_pattern(filename: str, pattern: str) -> dict:
    """
    MP3Tag 风格 "文件名 -> 标签" 转换
    pattern 例: "%artist% - %title%" / "%tracknumber%. %title%"
    返回 {field: value}
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    keys = re.findall(r"%(\w+)%", pattern)
    # 用命名分组把 %key% 替换为非贪婪捕获
    regex = re.escape(pattern)
    for k in keys:
        regex = regex.replace(re.escape(f"%{k}%"), f"(?P<{k}>.+?)", 1)
    m = re.fullmatch(regex, stem)
    if not m:
        return {}
    return {k: v.strip() for k, v in m.groupdict().items()
            if k in FIELDS and v.strip()}

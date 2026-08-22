"""MP3 ID3 标签读写（基于 mutagen）。

支持字段: tracknumber(TRCK) / title(TIT2) / artist(TPE1) / album(TALB)。
空字符串表示从文件里删除该字段。
"""

from __future__ import annotations

from typing import Dict

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

FIELDS = ("track", "title", "artist", "album")
# 对外字段名 -> EasyID3 的字段名
EASY_KEYS = {
    "track": "tracknumber",
    "title": "title",
    "artist": "artist",
    "album": "album",
}


def read_tags(path: str) -> Dict[str, str]:
    """读取 mp3 的元信息，不存在的字段返回空字符串。"""
    try:
        tags = EasyID3(path)
    except ID3NoHeaderError:
        return {k: "" for k in FIELDS}
    except Exception as exc:  # 文件损坏等
        raise ValueError(f"读取标签失败: {exc}") from exc

    result = {}
    for key in FIELDS:
        try:
            value = str(tags[EASY_KEYS[key]][0]).strip()
        except (KeyError, IndexError, TypeError):
            value = ""
        result[key] = value
    return result


def write_tags(path: str, track: str, title: str, artist: str, album: str) -> None:
    """写入元信息；值为空字符串时删除对应字段。"""
    values = {"track": track, "title": title, "artist": artist, "album": album}

    try:
        tags = EasyID3(path)
    except ID3NoHeaderError:
        tags = EasyID3()  # 无标签时创建空标签
    except Exception as exc:
        raise ValueError(f"读取标签失败: {exc}") from exc

    for key, value in values.items():
        easy_key = EASY_KEYS[key]
        value = (value or "").strip()
        if value:
            tags[easy_key] = value
        else:
            try:
                del tags[easy_key]
            except KeyError:
                pass

    try:
        tags.save(path, v2_version=4)
    except Exception as exc:
        raise ValueError(f"保存标签失败: {exc}") from exc

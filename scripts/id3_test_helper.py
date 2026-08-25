#!/usr/bin/env python3
"""id3.js 对拍测试的 Python 助手：生成带标签的 MP3 样本 / 用 mutagen 校验。

子命令:
  make <path> <v2|v3|none>   生成样本（中文标签；v2=ID3v2.4, v3=ID3v2.3, none=无标签）
  verify <path>              打印 mutagen 读到的标签 JSON
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tag_editor as te  # noqa: E402
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1, TRCK  # noqa: E402

SAMPLE = {"track": "3/12", "title": "凡人修仙传 第2集 七玄门",
          "artist": "忘语", "album": "有声书合集"}
FAKE_AUDIO = b"\xff\xfb\x90\x00" + bytes(range(256)) * 8


def make(path: str, version: str) -> None:
    p = Path(path)
    p.write_bytes(FAKE_AUDIO)
    if version == "none":
        return
    enc = 3 if version == "v2" else 1  # v2.4 -> UTF-8; v2.3 -> UTF-16 w/BOM
    id3 = ID3()
    id3.add(TRCK(encoding=0, text=SAMPLE["track"]))
    id3.add(TIT2(encoding=enc, text=SAMPLE["title"]))
    id3.add(TPE1(encoding=enc, text=SAMPLE["artist"]))
    id3.add(TALB(encoding=enc, text=SAMPLE["album"]))
    id3.save(str(p), v1=0, v2_version=4 if version == "v2" else 3)


def verify(path: str) -> None:
    try:
        print(json.dumps(te.read_tags(path), ensure_ascii=False))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "make":
        make(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "v2")
    elif len(sys.argv) >= 3 and sys.argv[1] == "verify":
        verify(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)

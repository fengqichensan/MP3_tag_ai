"""tag_editor 读写测试：构造无内容的假 .mp3 文件即可（ID3 不校验音频帧）。"""

import tempfile
import unittest
from pathlib import Path

import tag_editor as te


def make_mp3(tmp: Path, name: str = "song.mp3") -> Path:
    path = tmp / name
    path.write_bytes(b"")
    return path


class TagEditorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_read_empty_when_no_tag(self):
        p = make_mp3(self.tmp)
        self.assertEqual(te.read_tags(str(p)), {"track": "", "title": "", "artist": "", "album": ""})

    def test_write_read_roundtrip(self):
        p = make_mp3(self.tmp)
        te.write_tags(str(p), "01", "Crazy Train", "Ozzy Osbourne", "Blizzard of Ozz")
        tags = te.read_tags(str(p))
        self.assertEqual(tags["track"], "01")
        self.assertEqual(tags["title"], "Crazy Train")
        self.assertEqual(tags["artist"], "Ozzy Osbourne")
        self.assertEqual(tags["album"], "Blizzard of Ozz")

    def test_write_read_chinese(self):
        p = make_mp3(self.tmp)
        te.write_tags(str(p), "1", "海阔天空", "Beyond", "乐与怒")
        tags = te.read_tags(str(p))
        self.assertEqual((tags["title"], tags["artist"], tags["album"]), ("海阔天空", "Beyond", "乐与怒"))

    def test_empty_value_removes_field(self):
        p = make_mp3(self.tmp)
        te.write_tags(str(p), "01", "Title", "Artist", "Album")
        te.write_tags(str(p), "01", "Title", "", "")
        tags = te.read_tags(str(p))
        self.assertEqual(tags["artist"], "")
        self.assertEqual(tags["album"], "")
        self.assertEqual(tags["title"], "Title")

    def test_update_idempotent(self):
        p = make_mp3(self.tmp)
        te.write_tags(str(p), "2", "A", "B", "C")
        te.write_tags(str(p), "3", "D", "E", "F")
        tags = te.read_tags(str(p))
        self.assertEqual((tags["track"], tags["title"], tags["artist"], tags["album"]),
                         ("3", "D", "E", "F"))


if __name__ == "__main__":
    unittest.main()

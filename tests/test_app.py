"""Flask 接口集成测试：上传 → AI(正则provider) → 保存 → 下载 / 本地目录扫描写入。"""

import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import app as app_mod
import tag_editor as te


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.uploads = cls.tmp / "uploads"
        cls.config_path = cls.tmp / "config.json"
        # 重定向数据目录，避免污染项目 data/
        app_mod.UPLOAD_DIR = cls.uploads
        app_mod.CONFIG_PATH = cls.config_path
        # 默认用本地正则 provider，测试不依赖网络
        app_mod.save_config({
            "provider": "none",
            "ollama": {"url": "http://127.0.0.1:1", "model": "x"},
            "deepseek": {"url": "http://127.0.0.1:1", "model": "x", "api_key": ""},
        })
        app_mod.app.config["TESTING"] = True
        cls.client = app_mod.app.test_client()

    def setUp(self):
        # 每个用例重置全局内存态与配置，避免互相污染
        with app_mod._lock:
            app_mod.ITEMS.clear()
            app_mod.JOBS.clear()
        for p in app_mod.UPLOAD_DIR.glob("*"):
            p.unlink(missing_ok=True)
        app_mod.save_config({
            "provider": "none",
            "ollama": {"url": "http://127.0.0.1:1", "model": "x"},
            "deepseek": {"url": "http://127.0.0.1:1", "model": "x", "api_key": ""},
        })

    def _upload(self, *names):
        data = {"files": [(io.BytesIO(b""), n) for n in names]}
        resp = self.client.post("/api/upload", data=data)
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def test_index_served(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("MP3", resp.get_data(as_text=True))

    def test_upload_and_save_and_download(self):
        data = self._upload("01 - Crazy Train.mp3", "02 - Iron Man.mp3")
        self.assertEqual(len(data["items"]), 2)
        first = data["items"][0]

        resp = self.client.post("/api/save", json={"items": [{
            "id": first["id"],
            "track": "01",
            "title": "Crazy Train",
            "artist": "Ozzy Osbourne",
            "album": "Blizzard of Ozz",
        }]})
        body = resp.get_json()
        self.assertEqual(body["ok_count"], 1)

        # 下载回来验证标签确实写入了
        dl = self.client.get(f"/api/download/{first['id']}")
        self.assertEqual(dl.status_code, 200)
        p = self.tmp / "back.mp3"
        p.write_bytes(dl.data)
        tags = te.read_tags(str(p))
        self.assertEqual(tags["title"], "Crazy Train")
        self.assertEqual(tags["artist"], "Ozzy Osbourne")

    def test_upload_rejects_non_mp3(self):
        data = self._upload("note.txt")
        self.assertEqual(len(data["items"]), 0)
        self.assertTrue(any("不是 .mp3" in e for e in data["errors"]))

    def test_ai_job_with_regex_provider(self):
        data = self._upload("07 - Seventh Son.mp3")
        item = data["items"][0]
        resp = self.client.post("/api/ai/extract", json={"ids": [item["id"]]})
        job_id = resp.get_json()["job_id"]

        for _ in range(50):
            job = self.client.get(f"/api/ai/job/{job_id}").get_json()
            if job["done"] >= job["total"]:
                break
            time.sleep(0.1)
        result = job["results"][item["id"]]
        self.assertEqual(result["track"], "07")
        self.assertEqual(result["title"], "Seventh Son")

    def test_scan_and_inplace_save(self):
        folder = self.tmp / "music"
        folder.mkdir(exist_ok=True)
        song = folder / "03 - Still Life.mp3"
        song.write_bytes(b"")
        resp = self.client.post("/api/scan", json={"dir": str(folder)})
        body = resp.get_json()
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["source"], "local")

        self.client.post("/api/save", json={"items": [{
            "id": item["id"], "track": "03", "title": "Still Life", "artist": "Iron Maiden", "album": "",
        }]})
        tags = te.read_tags(str(song))
        self.assertEqual(tags["title"], "Still Life")
        self.assertEqual(tags["artist"], "Iron Maiden")

    def test_scan_bad_dir(self):
        resp = self.client.post("/api/scan", json={"dir": "/no/such/dir"})
        self.assertEqual(resp.status_code, 400)

    def test_download_all_zip(self):
        self._upload("01 - A.mp3", "02 - B.mp3")
        resp = self.client.get("/api/download_all")
        self.assertEqual(resp.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(resp.data))
        self.assertEqual(len(zf.namelist()), 2)

    def test_config_roundtrip_and_mask(self):
        self.client.post("/api/config", json={
            "provider": "deepseek",
            "prompt": "按我的规则: {filename}",
            "deepseek": {"api_key": "sk-secret-key-1234", "model": "deepseek-chat"},
        })
        cfg = self.client.get("/api/config").get_json()
        self.assertEqual(cfg["provider"], "deepseek")
        self.assertEqual(cfg["prompt"].strip(), "按我的规则: {filename}")
        self.assertIn("prompt_default", cfg)
        self.assertNotIn("sk-secret-key-1234", cfg["deepseek"]["api_key"])
        self.assertIn("****", cfg["deepseek"]["api_key"])

    def test_ai_try_endpoint(self):
        self.client.post("/api/config", json={"provider": "none"})
        resp = self.client.post("/api/ai/try", json={
            "filename": "07 - Seventh Son.mp3",
            "prompt": "自定义 {filename}",
        })
        body = resp.get_json()
        self.assertEqual(body["track"], "07")
        self.assertEqual(body["title"], "Seventh Son")
        self.assertEqual(body["source"], "fallback")

    def test_config_zhipu_roundtrip_and_mask(self):
        self.client.post("/api/config", json={
            "provider": "zhipu",
            "zhipu": {"api_key": "zk-secret-abcdef1234", "model": "glm-4-plus"},
        })
        cfg = self.client.get("/api/config").get_json()
        self.assertEqual(cfg["provider"], "zhipu")
        self.assertEqual(cfg["zhipu"]["model"], "glm-4-plus")
        self.assertNotIn("zk-secret-abcdef1234", cfg["zhipu"]["api_key"])
        self.assertIn("****", cfg["zhipu"]["api_key"])

    def test_config_openrouter_roundtrip_and_mask(self):
        self.client.post("/api/config", json={
            "provider": "openrouter",
            "openrouter": {"api_key": "sk-or-v1-abcdef123456", "model": "openai/gpt-4o-mini"},
        })
        cfg = self.client.get("/api/config").get_json()
        self.assertEqual(cfg["provider"], "openrouter")
        self.assertEqual(cfg["openrouter"]["model"], "openai/gpt-4o-mini")
        self.assertNotIn("sk-or-v1-abcdef123456", cfg["openrouter"]["api_key"])
        self.assertIn("****", cfg["openrouter"]["api_key"])

    def test_ai_try_with_zhipu_provider_none_fallback(self):
        # provider 为 zhipu 且指向不可达地址时，/api/ai/try 应回退到本地正则而不是报错
        self.client.post("/api/config", json={
            "provider": "zhipu",
            "zhipu": {"url": "http://127.0.0.1:1"},
        })
        resp = self.client.post("/api/ai/try", json={
            "filename": "11 - Fallback Again.mp3",
        })
        body = resp.get_json()
        self.assertEqual(body["track"], "11")
        self.assertEqual(body["source"], "fallback")

    def test_ai_try_requires_filename(self):
        resp = self.client.post("/api/ai/try", json={"filename": ""})
        self.assertEqual(resp.status_code, 400)

    def test_test_ai_none_provider(self):
        resp = self.client.post("/api/test_ai", json={"provider": "none"})
        self.assertTrue(resp.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()

"""ai_client 测试：JSON 解析、正则推测、mock 的网络调用与回退。"""

import unittest
from unittest.mock import Mock, patch

import ai_client as aic


class FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class ParseTest(unittest.TestCase):
    def test_plain_json(self):
        r = aic.parse_ai_json('{"track": "01", "title": "Crazy Train"}')
        self.assertEqual(r, {"track": "01", "title": "Crazy Train"})

    def test_fenced_json(self):
        r = aic.parse_ai_json('好的，结果如下：\n```json\n{"track": "3", "title": "海阔天空"}\n```')
        self.assertEqual(r, {"track": "3", "title": "海阔天空"})

    def test_number_track(self):
        r = aic.parse_ai_json('{"track": 12, "title": "Song"}')
        self.assertEqual(r["track"], "12")

    def test_garbage(self):
        self.assertIsNone(aic.parse_ai_json("我不明白你在说什么"))
        self.assertIsNone(aic.parse_ai_json(""))
        self.assertIsNone(aic.parse_ai_json('{"foo": "bar"}'))


class RegexTest(unittest.TestCase):
    def test_dash_dash(self):
        self.assertEqual(aic.regex_guess("01 - Crazy Train.mp3"),
                         {"track": "01", "title": "Crazy Train"})

    def test_dot(self):
        self.assertEqual(aic.regex_guess("12. 海阔天空.mp3"),
                         {"track": "12", "title": "海阔天空"})

    def test_underscore(self):
        self.assertEqual(aic.regex_guess("3_Intro.mp3"),
                         {"track": "3", "title": "Intro"})

    def test_no_track_number(self):
        self.assertEqual(aic.regex_guess("Nothing Else Matters.mp3"),
                         {"track": "", "title": "Nothing Else Matters"})

    def test_chinese_no_sep(self):
        self.assertEqual(aic.regex_guess("稻香.mp3"),
                         {"track": "", "title": "稻香"})


class ExtractTest(unittest.TestCase):
    def test_local_regex_provider(self):
        r = aic.extract("02 - Song.mp3", {"provider": "none"})
        self.assertEqual((r.track, r.title, r.source), ("02", "Song", "fallback"))

    @patch("ai_client.requests.post")
    def test_ollama_success(self, mock_post):
        mock_post.return_value = FakeResp({
            "message": {"content": '{"track": "2", "title": "Song"}', "role": "assistant"}
        })
        r = aic.extract("should be overridden.mp3", {"provider": "ollama", "ollama": {"url": "http://x", "model": "m"}})
        self.assertEqual((r.track, r.title, r.source), ("2", "Song", "ai"))
        self.assertEqual(r.error, "")
        payload = mock_post.call_args.kwargs["json"]
        self.assertTrue(payload.get("format") == "json")  # 要求模型输出 JSON

    @patch("ai_client.requests.post")
    def test_deepseek_success(self, mock_post):
        mock_post.return_value = FakeResp({
            "choices": [{"message": {"content": '{"track": "1", "title": "甲壳虫"}'}}]
        })
        r = aic.extract("x.mp3", {"provider": "deepseek", "deepseek": {"url": "https://d", "model": "m", "api_key": "k"}})
        self.assertEqual((r.track, r.title, r.source), ("1", "甲壳虫", "ai"))

    @patch("ai_client.requests.post", side_effect=RuntimeError("connection refused"))
    def test_ai_failure_falls_back(self, mock_post):
        r = aic.extract("05 - Fallback Song.mp3", {"provider": "ollama", "ollama": {"url": "http://x", "model": "m"}})
        self.assertEqual((r.track, r.title, r.source), ("05", "Fallback Song", "fallback"))
        self.assertIn("AI 调用失败", r.error)

    @patch("ai_client.requests.post")
    def test_bad_json_falls_back(self, mock_post):
        mock_post.return_value = FakeResp({"message": {"content": "这是首歌"}})
        r = aic.extract("07 - Song.mp3", {"provider": "ollama", "ollama": {"url": "http://x", "model": "m"}})
        self.assertEqual((r.track, r.title, r.source), ("07", "Song", "fallback"))


class PromptTest(unittest.TestCase):
    def test_default_when_empty(self):
        p = aic.build_prompt("", "01 - Song.mp3")
        self.assertIn("01 - Song.mp3", p)
        self.assertIn("曲目号", p)

    def test_custom_with_placeholder(self):
        p = aic.build_prompt("请解析 {filename}", "02 - X.mp3")
        self.assertEqual(p, "请解析 02 - X.mp3")
        self.assertNotIn("{filename}", p)

    def test_custom_without_placeholder_appends_filename(self):
        p = aic.build_prompt("只提取标题", "03 - Y.mp3")
        self.assertIn('文件名: "03 - Y.mp3"', p)

    @patch("ai_client.requests.post")
    def test_custom_prompt_is_sent(self, mock_post):
        mock_post.return_value = FakeResp({"message": {"content": '{"track": "1", "title": "T"}'}})
        cfg = {
            "provider": "ollama",
            "prompt": "我的自定义规则 {filename} 结尾",
            "ollama": {"url": "http://x", "model": "m"},
        }
        r = aic.extract("zzz.mp3", cfg)
        self.assertEqual(r.source, "ai")
        sent = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertTrue(sent.startswith("我的自定义规则"))
        self.assertTrue(sent.endswith("zzz.mp3 结尾"))
        self.assertNotIn("{filename}", sent)


class ZhipuTest(unittest.TestCase):
    @patch("ai_client.requests.post")
    def test_zhipu_success(self, mock_post):
        mock_post.return_value = FakeResp({
            "choices": [{"message": {"content": '{"track": "4", "title": "加州旅馆"}'}}]
        })
        r = aic.extract("x.mp3", {
            "provider": "zhipu",
            "zhipu": {"url": "https://z", "model": "glm-4-flash", "api_key": "k"},
        })
        self.assertEqual((r.track, r.title, r.source), ("4", "加州旅馆", "ai"))

    @patch("ai_client.requests.post")
    def test_zhipu_400_retry_without_response_format(self, mock_post):
        first = FakeResp({}, status=400)
        second = FakeResp({"choices": [{"message": {"content": '{"track": "1", "title": "T"}'}}]})
        mock_post.side_effect = [first, second]
        r = aic.extract("x.mp3", {
            "provider": "zhipu",
            "zhipu": {"url": "https://z", "model": "g", "api_key": "k"},
        })
        self.assertEqual(r.source, "ai")
        self.assertEqual(mock_post.call_count, 2)
        second_payload = mock_post.call_args_list[1].kwargs["json"]
        self.assertNotIn("response_format", second_payload)

    @patch("ai_client.requests.post")
    def test_zhipu_connection(self, mock_post):
        mock_post.return_value = FakeResp({"choices": [{"message": {"content": "ok"}}]})
        r = aic.test_connection({
            "provider": "zhipu",
            "zhipu": {"url": "https://z", "model": "g", "api_key": "k"},
        })
        self.assertTrue(r["ok"])


class OpenRouterTest(unittest.TestCase):
    @patch("ai_client.requests.post")
    def test_openrouter_success(self, mock_post):
        mock_post.return_value = FakeResp({
            "choices": [{"message": {"content": '{"track": "9", "title": "夜曲"}'}}]
        })
        r = aic.extract("x.mp3", {
            "provider": "openrouter",
            "openrouter": {
                "url": "https://openrouter.ai/api/v1",
                "model": "openai/gpt-4o-mini",
                "api_key": "sk-or-v1-test",
            },
        })
        self.assertEqual((r.track, r.title, r.source), ("9", "夜曲", "ai"))
        # 走 OpenAI 兼容端点: URL、Bearer key、model 都要正确
        self.assertEqual(mock_post.call_args.args[0],
                         "https://openrouter.ai/api/v1/chat/completions")
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer sk-or-v1-test")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")

    @patch("ai_client.requests.post")
    def test_openrouter_connection(self, mock_post):
        mock_post.return_value = FakeResp({"choices": [{"message": {"content": "ok"}}]})
        r = aic.test_connection({
            "provider": "openrouter",
            "openrouter": {"url": "https://openrouter.ai/api/v1",
                           "model": "openai/gpt-4o-mini", "api_key": "k"},
        })
        self.assertTrue(r["ok"])
        self.assertIn("OpenRouter", r["message"])

    def test_openrouter_failure_falls_back(self):
        with patch("ai_client.requests.post", side_effect=RuntimeError("no network")):
            r = aic.extract("08 - Fallback.mp3", {
                "provider": "openrouter",
                "openrouter": {"url": "http://127.0.0.1:1", "model": "m", "api_key": "k"},
            })
        self.assertEqual((r.track, r.title, r.source), ("08", "Fallback", "fallback"))
        self.assertIn("AI 调用失败", r.error)


class ConnectionTest(unittest.TestCase):
    def test_none_provider(self):
        self.assertTrue(aic.test_connection({"provider": "none"})["ok"])

    @patch("ai_client.requests.get")
    def test_ollama_ok(self, mock_get):
        mock_get.return_value = FakeResp({"models": [{"name": "gemma4:12b-mlx"}]})
        r = aic.test_connection({"provider": "ollama", "ollama": {"url": "http://x", "model": "gemma4:12b-mlx"}})
        self.assertTrue(r["ok"])
        self.assertIn("存在", r["message"])


if __name__ == "__main__":
    unittest.main()

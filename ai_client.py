"""AI 从文件名提取 曲目号(Track) 和 标题(Title)。

支持五种来源:
  - ollama     : 通过 Ollama /api/chat 调用本地/远程模型
  - deepseek   : DeepSeek OpenAI 兼容接口 /chat/completions
  - zhipu      : 智谱 AI（GLM）OpenAI 兼容接口 /chat/completions
  - openrouter : OpenRouter（聚合各家模型）OpenAI 兼容接口 /chat/completions
  - none       : 纯本地正则推测（AI 不可用时兜底）

AI 调用失败或返回非 JSON 时，自动回退到本地正则推测。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

import requests

DEFAULT_CONFIG: Dict = {
    "provider": "ollama",  # ollama | deepseek | zhipu | openrouter | none
    "prompt": "",          # 用户自定义提取提示词，空 = 使用内置默认提示词
    "ollama": {
        "url": "http://192.168.2.166:11434",
        "model": "gemma4:12b-mlx",
    },
    "deepseek": {
        "url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "",
    },
    "zhipu": {
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "api_key": "",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "api_key": "",
    },
}

DEFAULT_PROMPT = (
    "你是一个音乐元数据助手。根据给定的 MP3 文件名，提取 曲目号(track) 和 标题(title)。\n"
    "规则:\n"
    "1. 文件名可能包含 曲目号前缀（如 \"01 - \"、\"12.\"、\"3_\"），把它放进 track 字段，"
    "没有就留空字符串。\n"
    "2. title 是歌曲标题本身，去掉曲目号、分隔符、扩展名等噪音；保持原标题语言（中文就保留中文）。\n"
    "3. 只输出 JSON，不要任何其他文字，格式: {\"track\": \"...\", \"title\": \"...\"}。\n"
    "文件名: \"{filename}\""
)


def build_prompt(user_prompt: str, filename: str) -> str:
    """构造发给模型的提示词；{filename} 会替换为当前文件名。

    用户提示词里没有 {filename} 占位符时，自动把文件名追加在末尾。
    """
    source = (user_prompt or "").strip()
    if not source:
        source = DEFAULT_PROMPT
    if "{filename}" in source:
        return source.replace("{filename}", filename)
    return f'{source}\n文件名: "{filename}"'


@dataclass
class Extracted:
    track: str = ""
    title: str = ""
    source: str = "fallback"  # ai | fallback
    error: str = ""


def parse_ai_json(text: str) -> Optional[Dict[str, str]]:
    """从模型返回文本中解析 {"track": ..., "title": ...}，支持代码块包裹。"""
    if not text:
        return None
    cleaned = text.strip()
    # 去掉 ```json ... ``` 代码块
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        data = json.loads(cleaned[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    result = {}
    for key in ("track", "title"):
        value = data.get(key)
        if value is None:
            result[key] = ""
        else:
            result[key] = str(value).strip()
        if key == "track" and result[key].isdigit():
            # 统一成去零前缀的字符串? 保留原样更保险，仅去掉多余空格/点号
            result[key] = result[key].strip(" .-")
    if not result["title"]:
        return None
    return result


def regex_guess(filename: str) -> Dict[str, str]:
    """离线正则推测: 从文件名提取 曲目号 和 标题。"""
    name = re.sub(r"\.mp3$", "", filename, flags=re.I).strip()
    m = re.match(r"\s*(\d{1,3})\s*[-._)\s]+(.+)", name)
    if m:
        return {"track": m.group(1), "title": m.group(2).strip()}
    return {"track": "", "title": name}


def _call_ollama(cfg: Dict, prompt: str) -> str:
    url = cfg["url"].rstrip("/") + "/api/chat"
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    resp = requests.post(
        url, json=payload, timeout=(cfg.get("connect_timeout", 8), cfg.get("timeout", 300))
    )
    resp.raise_for_status()
    data = resp.json()
    message = (data.get("message") or {}).get("content", "")
    if not message and data.get("response"):
        message = data["response"]
    return message or ""


def _call_openai_compatible(cfg: Dict, prompt: str) -> str:
    """OpenAI 兼容端点（DeepSeek / 智谱 GLM 等）的 chat/completions 调用。"""
    url = cfg["url"].rstrip("/") + "/chat/completions"
    api_key = cfg.get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    timeout = (cfg.get("connect_timeout", 8), cfg.get("timeout", 90))
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code == 400:
        # 部分兼容端点不支持 response_format，去掉重试一次
        payload.pop("response_format", None)
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def extract(filename: str, config: Optional[Dict] = None) -> Extracted:
    """主入口：根据配置用 AI 提取，失败自动回退正则。"""
    config = config or DEFAULT_CONFIG
    provider = (config.get("provider") or "none").lower()

    result = Extracted()
    if provider in ("ollama", "deepseek", "zhipu", "openrouter"):
        prompt = build_prompt(config.get("prompt", ""), filename)
        try:
            if provider == "ollama":
                raw = _call_ollama(config.get("ollama", {}), prompt)
            else:
                raw = _call_openai_compatible(config.get(provider, {}), prompt)
            parsed = parse_ai_json(raw)
            if parsed:
                result.track = parsed["track"]
                result.title = parsed["title"]
                result.source = "ai"
                return result
            result.error = "AI 返回内容无法解析为 JSON"
        except Exception as exc:
            result.error = f"AI 调用失败: {exc}"

    guess = regex_guess(filename)
    result.track = guess["track"]
    result.title = guess["title"]
    result.source = "fallback"
    return result


def _ping_openai_compatible(cfg: Dict, label: str) -> Dict:
    """用一次 max_tokens=1 的最小补全请求验证 OpenAI 兼容端点的地址/key/model。"""
    url = cfg["url"].rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        json={
            "model": cfg["model"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"},
        timeout=15,
    )
    resp.raise_for_status()
    return {"ok": True, "message": f"{label} API 连接成功"}


def test_connection(config: Optional[Dict] = None) -> Dict:
    """连接测试：返回 {ok, message}。"""
    config = config or DEFAULT_CONFIG
    provider = (config.get("provider") or "none").lower()

    if provider == "none":
        return {"ok": True, "message": "本地正则模式，无需连接"}

    try:
        if provider == "ollama":
            url = config["ollama"]["url"].rstrip("/") + "/api/tags"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            model = config["ollama"]["model"]
            found = any(model.split(":")[0] == m.split(":")[0] for m in models)
            return {
                "ok": True,
                "message": f"Ollama 已连接；模型 {model} {'存在' if found else '未找到'}"
                          + ("" if found else f"，可用: {', '.join(models[:8])}"),
            }
        if provider == "deepseek":
            url = config["deepseek"]["url"].rstrip("/") + "/models"
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {config['deepseek'].get('api_key', '')}"},
                timeout=15,
            )
            resp.raise_for_status()
            return {"ok": True, "message": "DeepSeek API 连接成功"}
        if provider == "zhipu":
            return _ping_openai_compatible(config["zhipu"], "智谱 AI")
        if provider == "openrouter":
            return _ping_openai_compatible(config["openrouter"], "OpenRouter")
    except Exception as exc:
        return {"ok": False, "message": f"连接失败: {exc}"}

    return {"ok": False, "message": "未知 provider"}

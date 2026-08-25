"""MP3 元数据批量编辑工具 - Flask 后端。

- 上传 MP3 或扫描服务器本地目录
- AI（Ollama / DeepSeek / 本地正则）从文件名提取 曲目号/标题
- 批量写入/清除 ID3 标签（title, artist, album, track）
- 下载修改后的文件（上传模式）
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import ai_client as aic
import tag_editor as te

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CONFIG_PATH = DATA_DIR / "config.json"

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1GB

# ---------------------------------------------------------------- config

def load_config() -> dict:
    cfg = copy.deepcopy(aic.DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for key, value in saved.items():
                if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                    cfg[key].update(value)
                else:
                    cfg[key] = value
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------- 内存态

ITEMS: dict[str, dict] = {}   # item_id -> {"id","filename","path","source"}
JOBS: dict[str, dict] = {}    # job_id  -> {"total","done","results"}
_lock = threading.Lock()


def _add_item(filename: str, path: Path, source: str) -> dict:
    item_id = uuid.uuid4().hex
    item = {"id": item_id, "filename": filename, "path": str(path), "source": source}
    try:
        item["existing"] = te.read_tags(str(path))
    except ValueError as exc:
        item["existing"] = {k: "" for k in te.FIELDS}
        item["existing_error"] = str(exc)
    with _lock:
        ITEMS[item_id] = item
    return item


# ---------------------------------------------------------------- 页面

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------- 添加文件

@app.post("/api/upload")
def upload():
    files = request.files.getlist("files")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    added = []
    errors = []
    for f in files:
        if not f.filename:
            continue
        if not f.filename.lower().endswith(".mp3"):
            errors.append(f"{f.filename}: 不是 .mp3 文件，已跳过")
            continue
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff()\[\] ]+", "_", f.filename)
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:12]}_{safe}"
        f.save(dest)
        added.append(_add_item(f.filename, dest, "upload"))
    return jsonify({"items": added, "errors": errors})


@app.post("/api/scan")
def scan():
    """扫描服务器本地目录下的 mp3 文件（修改会直接写入原文件）。"""
    data = request.get_json(silent=True) or {}
    directory = (data.get("dir") or "").strip()
    if not directory:
        return jsonify({"error": "请填写目录路径"}), 400
    folder = Path(directory).expanduser()
    if not folder.is_dir():
        return jsonify({"error": f"目录不存在: {folder}"}), 400
    added = []
    for p in sorted(folder.glob("*.mp3")):
        added.append(_add_item(p.name, p, "local"))
    if not added:
        return jsonify({"error": "该目录下没有 .mp3 文件"}), 404
    return jsonify({"items": added})


# ---------------------------------------------------------------- AI 提取

@app.post("/api/ai/extract")
def ai_extract():
    data = request.get_json(silent=True) or {}
    # 「直改本地文件」模式：文件在用户浏览器本地，服务器只知道文件名，
    # 由前端直接传 {id, filename} 列表过来，仅用于 AI 提取，不接触文件内容。
    client_items = data.get("items")
    if isinstance(client_items, list) and client_items:
        targets: list = []
        seen_ids: set = set()
        for row in client_items[:1000]:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("id") or uuid.uuid4().hex)
            fname = str(row.get("filename") or "").strip()
            if not fname or cid in seen_ids:
                continue
            seen_ids.add(cid)
            targets.append({"id": cid, "filename": fname})
    else:
        ids = data.get("ids") or [it["id"] for it in ITEMS.values()]
        targets = [ITEMS[i] for i in ids if i in ITEMS]
    if not targets:
        return jsonify({"error": "没有可处理的文件"}), 400

    config = load_config()
    job_id = uuid.uuid4().hex
    job = {"total": len(targets), "done": 0, "results": {}, "error": ""}
    with _lock:
        JOBS[job_id] = job

    def work(item: dict):
        result = aic.extract(item["filename"], config)
        return item["id"], {
            "track": result.track,
            "title": result.title,
            "source": result.source,
            "error": result.error,
        }

    def run():
        with ThreadPoolExecutor(max_workers=4) as pool:
            for item_id, result in pool.map(work, targets):
                with _lock:
                    job["results"][item_id] = result
                    job["done"] += 1

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/ai/job/<job_id>")
def ai_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)


# ---------------------------------------------------------------- 保存/下载

@app.post("/api/save")
def save():
    data = request.get_json(silent=True) or {}
    results = []
    saved_ok = 0
    for row in data.get("items", []):
        item = ITEMS.get(row.get("id"))
        if not item:
            results.append({"id": row.get("id"), "ok": False,
                            "error": "文件不存在，可能已被清理"})
            continue
        try:
            te.write_tags(
                item["path"],
                row.get("track", ""),
                row.get("title", ""),
                row.get("artist", ""),
                row.get("album", ""),
            )
            results.append({"id": item["id"], "ok": True})
            saved_ok += 1
        except ValueError as exc:
            results.append({"id": item["id"], "ok": False, "error": str(exc)})
    return jsonify({"results": results, "ok_count": saved_ok})


@app.get("/api/download/<item_id>")
def download(item_id: str):
    item = ITEMS.get(item_id)
    if not item or item["source"] != "upload":
        return jsonify({"error": "仅上传的文件支持下载"}), 404
    return send_file(item["path"], as_attachment=True, download_name=item["filename"])


@app.get("/api/download_all")
def download_all():
    upload_items = [it for it in ITEMS.values() if it["source"] == "upload"]
    if not upload_items:
        return jsonify({"error": "没有上传的文件可打包下载"}), 404
    buf = io.BytesIO()
    seen = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in upload_items:
            name = item["filename"]
            if name in seen:
                stem, ext = Path(name).stem, Path(name).suffix
                name = f"{stem}_{item['id'][:6]}{ext}"
            seen.add(name)
            zf.write(item["path"], arcname=name)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="mp3_edited.zip",
    )


# ---------------------------------------------------------------- 配置

PROVIDERS = ("ollama", "deepseek", "zhipu", "openrouter")


def _mask_key(key_text: str) -> str:
    if len(key_text) > 8:
        return key_text[:4] + "****" + key_text[-4:]
    return ""


@app.get("/api/config")
def get_config():
    cfg = load_config()
    for key in ("deepseek", "zhipu", "openrouter"):
        cfg[key]["api_key"] = _mask_key(cfg[key].get("api_key", ""))
    cfg["prompt_default"] = aic.DEFAULT_PROMPT
    return jsonify(cfg)


@app.post("/api/config")
def post_config():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    if data.get("provider") in (*PROVIDERS, "none"):
        cfg["provider"] = data["provider"]
    if isinstance(data.get("prompt"), str):
        cfg["prompt"] = data["prompt"].strip()
    for key in PROVIDERS:
        if not isinstance(data.get(key), dict):
            continue
        provider_cfg = data[key]
        for sub in ("url", "model"):
            if sub in provider_cfg:
                cfg[key][sub] = str(provider_cfg[sub]).strip()
        if "api_key" in provider_cfg and provider_cfg["api_key"]:
            new_key = str(provider_cfg["api_key"]).strip()
            if not new_key.startswith("****"):  # 前端回显的掩码直接忽略
                cfg[key]["api_key"] = new_key
    save_config(cfg)
    return jsonify({"ok": True})


@app.post("/api/ai/try")
def ai_try():
    """用给定提示词对单个文件名试提取，用于用户调优自己的 prompt。"""
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    if not filename:
        return jsonify({"error": "请填写文件名"}), 400
    cfg = load_config()
    prompt = data.get("prompt")
    if isinstance(prompt, str):
        cfg["prompt"] = prompt
    result = aic.extract(filename, cfg)
    return jsonify({
        "track": result.track,
        "title": result.title,
        "source": result.source,
        "error": result.error,
    })


@app.post("/api/test_ai")
def test_ai():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    for key in PROVIDERS:
        if isinstance(data.get(key), dict):
            for sub in ("url", "model", "api_key"):
                if sub in data[key] and data[key][sub]:
                    cfg[key][sub] = str(data[key][sub]).strip()
    if data.get("provider") in (*PROVIDERS, "none"):
        cfg["provider"] = data["provider"]
    return jsonify(aic.test_connection(cfg))


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    cert = os.environ.get("TLS_CERTFILE", "")
    key = os.environ.get("TLS_KEYFILE", "")
    ssl_context = None
    if cert and key and os.path.isfile(cert) and os.path.isfile(key):
        ssl_context = (cert, key)
        print(f"MP3 标签批量编辑器: https://{host}:{port} (自签名证书)")
    else:
        print(f"MP3 标签批量编辑器: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True,
            ssl_context=ssl_context)


if __name__ == "__main__":
    main()

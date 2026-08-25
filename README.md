# MP3 标签批量编辑器

一个带 Web UI 的 Python 工具，批量读取 / 编辑 MP3 的 ID3 元信息：

- **曲目号 (Track / TRCK)**、**标题 (Title / TIT2)**：调用 AI 从文件名自动提取
  - 支持 **Ollama**（本地/局域网模型）、**DeepSeek**、**智谱 GLM** 和 **OpenRouter**（均为 OpenAI 兼容接口）
  - AI 不可用时自动回退到本地正则推测（如 `01 - Song.mp3` → track=`01`, title=`Song`）
- **艺术家 (Artist / TPE1)**、**专辑 (Album / TALB)**：手动输入后一键应用到全部行，也可逐格编辑
- 批量处理：上传多个 MP3 处理完后打包下载；或直接指定服务器目录扫描、原地改写

技术栈：Flask（后端）+ 原生 JS（前端）+ [mutagen](https://mutagen.readthedocs.io/)（ID3 读写）。

## 安装

需要 Python 3.9+：

```bash
cd MP3_tag_ai
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 启动

```bash
.venv/bin/python app.py
```

浏览器打开 <http://127.0.0.1:5000>。（默认只监听本机；如需局域网访问：`HOST=0.0.0.0 PORT=5000 .venv/bin/python app.py`，注意无鉴权，请自行控制网络。）

可选的生产级启动（Flask 自带服务器仅供开发）：

```bash
.venv/bin/pip install waitress
.venv/bin/waitress-serve --host=127.0.0.1 --port=5000 app:app
```

## 使用流程

1. **添加文件**：拖拽 / 点击上传 `.mp3`（处理的是服务器副本，改完下载）；
   或点 **扫描服务器目录** 输入工具所在机器上的目录，改动会**直接写回原文件**。
2. **AI 提取**：点「🤖 AI 提取曲目/标题」，后端并发调用 AI，进度实时刷新到表格
   （AI 失败的行自动采用本地正则推测并提示原因）。
3. **艺术家 / 专辑**：在顶部输入框填写后点「➡ 应用到全部行」；也可以直接在表格中双击任意单元格单独修改。
4. **保存**：点「💾 保存到文件」写入 ID3 标签；上传模式可单个下载或「📦 打包下载」。

## AI 设置（右上角 ⚙）

| 来源 | 说明 |
|---|---|
| Ollama | 填服务地址（默认 `http://192.168.2.166:11434`）和模型名（默认 `gemma4:12b-mlx`）。**远程访问**需在 Ollama 机器上以 `OLLAMA_HOST=0.0.0.0` 启动。模型冷启动可能较慢（1~3 分钟），热调用约 20~30 秒。 |
| DeepSeek | 填 API Key（[platform.deepseek.com](https://platform.deepseek.com) 获取），模型默认 `deepseek-chat`。 |
| 智谱 GLM | 填 API Key（[open.bigmodel.cn](https://open.bigmodel.cn) 获取），接口默认 `https://open.bigmodel.cn/api/paas/v4`，模型默认 `glm-4-flash`（免费），也可用 `glm-4-plus` 等。 |
| OpenRouter | 一个 Key 聚合各家模型。填 API Key（[openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) 获取），接口默认 `https://openrouter.ai/api/v1`，模型名格式「厂商/模型」，如 `openai/gpt-4o-mini`、`anthropic/claude-3.5-haiku`、`google/gemini-2.0-flash-001`、`deepseek/deepseek-chat`。 |
| 本地正则 | 离线模式，无 AI，仅用文件名规则推测，永不出错。 |

**提取提示词可以完全自定义**：设置弹窗里「提取提示词（AI Prompt）」文本框，把 AI 的判断规则换成任何你想要的写法：

- 用 `{filename}` 占位当前文件名（不写占位符时工具会自动把文件名追加到末尾）；
- 模型必须返回包含 `track` 和 `title` 两个键的 JSON；
- 「↩ 恢复默认提示词」随时载回内置版本；「🧪 试提取」输入一个示例文件名，立即验证你的提示词效果（真实调用 AI，慢时请耐心等待）；
- 留空则使用内置默认提示词；定制内容保存在 `data/config.json` 的 `prompt` 字段。

「🔌 测试连接」可立刻验证 Ollama 网络与模型名是否可用。

> AI 提取时会把 `track` 和 `title` 两项填入「待保存」状态，**保存前请人工核对**。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests
```

覆盖：标签读写往返（含中文）、空值删除字段、AI 返回 JSON 解析、正则推测、
mock 网络调用与失败回退、全部 HTTP 接口（上传/扫描/AI 任务/保存/下载/配置）。

`scripts/timed_ollama_test.py` 可对真实 Ollama 做一次计时调用。

## 目录结构

```
app.py               Flask 后端（接口 + AI 任务调度）
ai_client.py         Ollama / DeepSeek / 智谱 / OpenRouter / 本地正则 + 解析与回退
tag_editor.py        mutagen 读写 ID3（track/title/artist/album）
static/              前端页面（表单、表格、拖拽上传、设置弹窗）
tests/               unittest 测试
data/config.json     运行时生成的配置
data/uploads/        上传文件的临时副本
```

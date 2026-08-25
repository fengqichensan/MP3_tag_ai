# MP3 标签批量编辑器

一个带 Web UI 的 Python 工具，批量读取 / 编辑 MP3 的 ID3 元信息：

- **曲目号 (Track / TRCK)**、**标题 (Title / TIT2)**：调用 AI 从文件名自动提取
  - 支持 **Ollama**（本地/局域网模型）、**DeepSeek**、**智谱 GLM**、**OpenRouter**
    和 **New API**（自建 LLM 网关，均为 OpenAI 兼容接口）
  - AI 不可用时自动回退到本地正则推测（如 `01 - Song.mp3` → track=`01`, title=`Song`）
- **艺术家 (Artist / TPE1)**、**专辑 (Album / TALB)**：手动输入后一键应用到全部行，也可逐格编辑
- 批量处理：上传多个 MP3 处理完后打包下载；或直接指定服务器目录扫描、原地改写；
  或用 **「📂 直改本地文件」**（Chrome/Edge）在浏览器里直接读写本机 MP3，文件不上传

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

可选的 HTTPS 启动（「直改本地文件」功能在非 localhost 的 HTTP 下会被浏览器禁用，
局域网部署建议走 HTTPS，见下方 Docker 部署）：

```bash
TLS_CERTFILE=/path/cert.pem TLS_KEYFILE=/path/key.pem HOST=0.0.0.0 .venv/bin/python app.py
```

可选的生产级启动（Flask 自带服务器仅供开发）：

```bash
.venv/bin/pip install waitress
.venv/bin/waitress-serve --host=127.0.0.1 --port=5000 app:app
```

## Docker 部署（NAS）

仓库自带 `Dockerfile` + `docker-compose.yml`，目标机器上克隆后一条命令启动：

```bash
git clone git@github.com:fengqichensan/MP3_tag_ai.git && cd MP3_tag_ai
docker compose up -d --build
```

当前部署在 NAS：**<https://192.168.2.155:5000>**（路径 `/vol1/1000/docker/mp3-tag-ai`）。

| 要点 | 说明 |
|---|---|
| HTTPS | 容器首次启动自动生成自签名证书（SAN 含 NAS IP），持久化在宿主机 `./certs/`，重启不重签。首次访问需点「高级 → 继续前往」通过证书警告 |
| 数据持久化 | `./data:/app/data`（AI 配置与上传副本）、`./certs:/app/certs`（证书） |
| 环境变量 | `ENABLE_HTTPS=1/0` 退回纯 HTTP；`CERT_SAN` NAS IP 变更后修改并删除 `certs/` 重新生成；`HOST_PORT` 宿主机端口 |
| 可选挂载 | 取消 compose 中 `/music` 注释并改为实际媒体目录，即可用「扫描服务器目录」原地改写 NAS 上的 MP3 |
| 更新方式 | 本机 `git push` 后，NAS 上执行 `git pull && docker compose up -d --build` |

> 该工具无登录鉴权，请仅在可信局域网内使用。

## 使用流程

1. **添加文件**：拖拽 / 点击上传 `.mp3`（处理的是服务器副本，改完下载）；
   或点 **📂 直改本地文件** 选择本机 MP3——读取、编辑、保存全部发生在浏览器本地
   （File System Access API + 内置 `static/id3.js`），改动**直接写回原文件**，
   文件内容不经过服务器；AI 提取仅把文件名发给后端。
   ⚠️ 该模式需要**桌面版 Chrome / Edge**，且页面必须通过 HTTPS 或 localhost 访问
   （浏览器把文件读写 API 限制在安全上下文内）；首次保存会弹「允许保存更改」确认框；
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
| New API | 自建的 [New API](https://github.com/QuantumNous/new-api) LLM 网关（One API 分支），多渠道统一转发。接口地址填网关的 OpenAI 兼容根路径（默认部署为 `http://网关IP:3000/v1`）；API Key 用「令牌」页生成的 `sk-…`；模型名填渠道里配置的任意模型。 |
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
node scripts/test_id3_js.mjs   # id3.js 与 mutagen 的对拍测试（需 Node 18+）
```

覆盖：标签读写往返（含中文）、空值删除字段、AI 返回 JSON 解析、正则推测、
mock 网络调用与失败回退、全部 HTTP 接口（上传/扫描/AI 任务/保存/下载/配置）、
浏览器端 ID3 读写器与 mutagen 的双向兼容（v2.2/2.3/2.4/v1、音频字节完整性）。

`scripts/timed_ollama_test.py` 可对真实 Ollama 做一次计时调用。

## 目录结构

```
app.py               Flask 后端（接口 + AI 任务调度 + TLS 启动）
ai_client.py         Ollama / DeepSeek / 智谱 / OpenRouter / New API / 本地正则 + 解析与回退
tag_editor.py        mutagen 读写 ID3（track/title/artist/album）
static/              前端页面（表单、表格、拖拽上传、设置弹窗、id3.js 浏览器端标签读写）
tests/               unittest 测试
scripts/             id3.js 对拍测试（test_id3_js.mjs + helper）、Ollama 计时脚本
Dockerfile           镜像构建（含 openssl，用于自签名证书）
docker-compose.yml   NAS 部署编排（端口 / 挂载 / HTTPS 环境变量）
entrypoint.sh        容器入口：按需生成自签名证书后启动应用
data/config.json     运行时生成的配置
data/uploads/        上传文件的临时副本
certs/               （NAS 上）自动生成的自签名证书，不入库
```

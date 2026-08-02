# Mini Video Agent

用**自然语言**对本地视频做切片、删中间、拼接、加文字、静音/变速、重命名，并能截帧预览、页内/系统播放器查看成片的迷你 Agent。

> 你说：「去掉前 5 秒」→「和另一段拼起来，命名为拼接」→「加标题」→「截第 1 秒看看」  
> 模型选工具 → FFmpeg 导出 → 网页预览 / 系统播放器。

本项目是学习向的 **v0.5**：CLI Agent + 本地 Web 体验站（确认按钮、成片点选/改名、多会话对话记录）。设计思路参考 [OpenChatCut](https://github.com/0xsline/OpenChatCut)，但刻意做成学生可维护的迷你工具，而不是完整剪辑器。

## 文档导航

| 文档 | 给谁看 |
|------|--------|
| **[USAGE.md](./USAGE.md)** | **使用者**：安装、开网页、说法、FAQ |
| **[PROBLEMS.md](./PROBLEMS.md)** | 排障：项目过程中踩过的坑与解法 |
| **[HANDOFF.md](./HANDOFF.md)** | **下一个 Agent / 开发者**：架构、约定、v1.0 方向 |
| [CHANGELOG.md](./CHANGELOG.md) | 版本能力与变更（建议与 Tag 同步） |
| [LEARNING.md](./LEARNING.md) | 学习者：Agent / Tool Calling 精读 |

仓库：https://github.com/guorunquan/video-editing-agent  

---

## 功能一览（当前已实现）

### 剪辑能力（CLI + Web 共用）

| 能力 | 工具 | 示例说法 |
|------|------|----------|
| 探测信息 | `probe_video` | 这个视频多长？ |
| 切片保留 | `trim_keep` | 去掉前 5 秒 / 只保留 2～8 秒 |
| 删中间 | `cut_out` | 删掉中间 2～4 秒 |
| 拼接 | `concat_videos` | 把这两段拼起来 |
| 静音 / 变速 | `mute_audio` / `change_speed` | 静音 / 两倍速 |
| 文字贴纸 | `add_text_overlay` | 加标题：决赛高光 |
| 截帧 | `export_preview_frame` | 截第 1 秒看看 |
| 打开 / 列表 / 删除 | `open_output` 等 | 打开刚导出的 / 列出成片 |
| 重命名 | `rename_output` | 命名为拼接 / 改名叫 1.5倍速视频 |

写磁盘操作：**先计划（待确认）→ 用户确认 → 再执行**。

### Web 体验站（v0.4 / v0.5）

- 入口：`python web_app.py` → http://127.0.0.1:7860  
- 上传视频、对话剪辑、页内播放器  
- 确认执行 / 取消按钮；成片列表点选播放、改名、打开文件位置  
- 对话记录：按日期分组的多会话目录  
- 截帧预览下方标注「第 N 秒」  
- 本机单用户 demo（无账号、无公网部署）

默认样本：`samples/demo.mp4`（也可改 `.env` 的 `DEFAULT_VIDEO`）。

---

## 技术栈

| 部分 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 大模型 | Google Gemini（Function Calling） |
| SDK | `google-genai` |
| 视频 | FFmpeg（PATH 或 `imageio-ffmpeg`） |
| Web | FastAPI + `static/` |
| 配置 | `.env` + `python-dotenv` |

---

## 架构（很短）

```text
CLI (main.py) 或 Web (web_app.py + static/)
    │
    ▼
agent.py          Gemini 多轮 Tool Calling
    │
    ▼
tools.py          剪辑工具白名单
    │
    ▼
FFmpeg；CLI 用系统播放器 / Web 用页内预览
```

| 文件 | 职责 |
|------|------|
| `main.py` | 命令行聊天入口 |
| `web_app.py` | 本地 Web API + 静态页 |
| `static/` | 上传 / 聊天 / 播放器前端 |
| `agent.py` | 模型循环、系统提示、错误提示 |
| `tools.py` | 工具实现 + 工具说明书 |
| `ffmpeg_bin.py` | 定位 ffmpeg |

**要点：** 模型只负责选工具和填参数；真正读写文件的是 Python——典型 Tool Calling Agent。

---

## 快速开始

完整说明见 **[USAGE.md](./USAGE.md)**。最短路径：

```bash
git clone https://github.com/guorunquan/video-editing-agent.git
cd video-editing-agent

python -m venv .venv
# Windows: .\.venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # macOS / Linux: cp .env.example .env
```

编辑 `.env`：填入 `GEMINI_API_KEY`。国内通常需 VPN；建议设置 `HTTPS_PROXY`（详见 [PROBLEMS.md](./PROBLEMS.md)）。  
申请 Key：https://aistudio.google.com/apikey

```bash
python web_app.py
# 浏览器打开 http://127.0.0.1:7860 （请 Ctrl+F5）
```

CLI：`python main.py`。

---

## 已知限制

- Web 为本地单用户：无账号、无多租户会话目录隔离、无实时进度推送  
- 无图形时间线 / 多轨 / 配乐库 / 复杂字幕  
- 文字目前为**单行**  
- 依赖 Gemini 在线 API（可能 429/503）  
- 快速切片可能差半秒；可说「切得更准」  
- 变速 0.5x～2.0x；拼接与叠字需重编码  
- Windows 拖进度条可能刷无害的 `ConnectionResetError`（见 PROBLEMS）

---

## 路线图

详见 [CHANGELOG.md](./CHANGELOG.md) 与 [HANDOFF.md](./HANDOFF.md) §8。

- [x] v0.1 探测 + 切片 + 导出管理 + 确认  
- [x] v0.2 打开成片 + 文字贴纸  
- [x] v0.3 删中间 / 拼接 / 静音/变速 / 截帧 / 工作视频记忆  
- [x] v0.4 本地 Web：上传 + 对话 + 页内预览  
- [x] v0.5 确认按钮 + 成片点选 + 对话记录 + 更清晰报错  
- [x] v0.5+ 多会话目录 / 成片改名与打开位置 / 对话重命名 / 截帧标秒  
- [ ] v1.0 体验站打磨（示例引导、进度与确认体验、文档与 tag）  
- [ ] v1.5 可选：配乐/转场、文字计划记忆、本地模型等  

欢迎 Issue / PR。

---

## 和 OpenChatCut 的关系

| OpenChatCut | 本项目 |
|-------------|--------|
| 完整多轨编辑器 + Remotion + MCP | CLI + 本地 Web 迷你 Agent |
| 时间线状态机 | 直接 FFmpeg 导出文件 |
| 草稿会话 / 人工批准 | `confirmed=false/true` |
| 适合生产向剪辑 | 适合学习 Agent 与简历作品 |

---

## 安全与隐私

- **不要**提交 `.env`、API Key、个人视频  
- 删除 / 重命名仅限 `output/`  
- 不要让模型生成任意 shell 命令并 `shell=True` 执行  

---

## License

MIT —— 见 [LICENSE](./LICENSE)

---

## 致谢

- [OpenChatCut](https://github.com/0xsline/OpenChatCut) — Agent-native 视频编辑思路参考  
- Google Gemini API — Function Calling  
- FFmpeg / imageio-ffmpeg — 视频处理  

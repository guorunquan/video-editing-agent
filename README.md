# Mini Video Agent

用**自然语言**对本地视频做切片、删中间、拼接、加文字、静音/变速，并能预览截图、打开成片的迷你 Agent。

> 你说：「去掉前 5 秒」→「删掉中间 2～4 秒」→「加标题」→「截第 1 秒看看」  
> 模型选工具 → FFmpeg 导出 → 网页预览 / 系统播放器。

本项目是学习向的 **v0.4**：在 v0.3 剪辑工具链之上，加上**本地 Web 体验壳**（上传 + 对话 + 页内预览）。设计思路参考开源项目 [OpenChatCut](https://github.com/0xsline/OpenChatCut)（对话驱动剪辑 / 草稿确认后再落地），但刻意做成学生可维护的迷你 Agent，而不是完整剪辑器。

| 文档 | 给谁看 |
|------|--------|
| **[USAGE.md](./USAGE.md)** | **使用者**：怎么安装、开网页、下指令、排障 |
| [CHANGELOG.md](./CHANGELOG.md) | 版本能力与变更（建议与 Tag 同步） |
| [LEARNING.md](./LEARNING.md) | 学习者：Agent / Tool Calling 精读 |

---

---

## 功能一览（当前已实现）

### 1. 探测视频信息

- 工具：`probe_video`
- 能力：读取本地视频的**时长、分辨率、文件大小、路径**
- 示例：
  - 「这个视频多长？」
  - 「看看 `D:\video\demo.mp4` 的信息」

### 2. 切片 / 删减（核心）

- 工具：`trim_keep`
- 能力：只保留 `[start_sec, end_sec)`，其余丢弃，导出到 `output/`
- 支持场景：
  | 你的说法 | 实际含义 |
  |----------|----------|
  | 去掉前 N 秒 | 保留 `N ~ 总时长` |
  | 只保留 10 秒到 30 秒 | 保留 `[10, 30)` |
  | 用某某路径，去掉前 1 秒 | 对指定文件切片 |
  | 切得更准一点 | `precise=true` 强制重编码 |

- 输出：`output/trim_{start}_{end}_{时间戳}.mp4`
- 实现：优先 FFmpeg stream copy（快）；失败或 `precise` 则 H.264/AAC 重编码

### 3. 删除中间段（v0.3）

- 工具：`cut_out`
- 能力：删掉 `[start, end)`，把前后拼回一条成片
- 示例：「删掉中间 10 秒到 20 秒」「去掉 2～4 秒那段」
- 输出：`output/cutout_{start}_{end}_{时间戳}.mp4`

### 4. 多段拼接（v0.3）

- 工具：`concat_videos`
- 能力：按顺序把多段视频拼成一条（可用 `output/` 文件名）
- 示例：「把 trim_1_7_xxx.mp4 和 trim_1_9_xxx.mp4 拼起来」

### 5. 静音 / 变速（v0.3）

- `mute_audio`：去掉声音，只留画面
- `change_speed`：0.5x～2.0x（如「两倍速」「慢放一半」）

### 6. 预览截图（v0.3）

- 工具：`export_preview_frame`
- 能力：截某一秒 PNG 到 `output/previews/`，默认自动打开看图（**无需确认**）
- 示例：「截第 1 秒看看」「看看字幕位置」

### 7. 文字贴纸 / 标题字幕（v0.2）

- 工具：`add_text_overlay`
- 能力：用 FFmpeg `drawtext` 叠一行文字，自动找中文字体（Windows 优先微软雅黑）
- 样式预设（少填参数就能用）：
  | style | 默认效果 |
  |-------|----------|
  | `title` | 大标题，画面居中 |
  | `subtitle` | 底部字幕 |
  | `sticker` | 右上角角标贴纸 |
- 还可指定：`position`（top/center/bottom/top_left/top_right）、字号、颜色、出现时段
- 默认加工**最新成片**；也可 `path` 指定源视频
- 输出：`output/text_{style}_{时间戳}.mp4`

### 8. 打开成片播放（v0.2）

- 工具：`open_output`
- 能力：用系统默认程序打开 `output/` 成片或预览图
- 「打开」「播放」「看看效果」→ 默认打开**最新**一条

### 9. 工作视频记忆（v0.3）

- `probe_video` / 成功导出后会写入 `data/session.json`
- 之后多数操作可省略路径，自动用当前工作视频或最新成片
- 也可对话里带绝对路径，或改 `.env` 的 `DEFAULT_VIDEO`

### 10. 管理已导出成片

- `list_outputs`：列出 `output/` 下已导出的 mp4 等（最新会标出来）
- `delete_output`：删除其中某个成片（**只能删 output，不能删原片**）

### 11. 「先计划，再确认」安全机制

对会改磁盘的操作（切片、删中间、拼接、加字、静音、变速、删除）：

1. 第一次：`confirmed=false` → 只打印计划，不改文件  
2. 你回复「确认」  
3. 第二次：`confirmed=true` → 真正执行  

截帧预览、探测、打开、列表**不需要**确认。

### 12. 人性化体验

- 待确认先用人话摘要，再附计划详情
- 成功后附带「接下来可以试试」
- 样式预设 + 工作视频记忆，少说参数也能做完

### 13. 本地 Web 体验站（v0.4）

- 入口：`python web_app.py` → 浏览器打开 `http://127.0.0.1:7860`
- 上传短视频 → 聊天下指令 → 右侧播放器预览成片 / 截帧条
- 剪辑工具与确认机制与 CLI 相同；`WEB_MODE` 下不再弹系统播放器
- 仍是本机单用户 demo（无账号、无公网部署）

---

## 技术栈

| 部分 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 大模型 | Google Gemini（Function Calling） |
| SDK | `google-genai` |
| 视频处理 | FFmpeg（优先系统 PATH；否则用 `imageio-ffmpeg` 自带二进制） |
| Web（v0.4） | FastAPI + 静态前端（`static/`） |
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
tools.py          probe / trim / cut / concat / mute / speed / text / preview / …
    │
    ▼
FFmpeg；CLI 用系统播放器 / Web 用页内预览
```

| 文件 | 职责 |
|------|------|
| `main.py` | 命令行聊天入口 |
| `web_app.py` | 本地 Web API + 静态页入口 |
| `static/` | 上传 / 聊天 / 播放器前端 |
| `agent.py` | 模型循环、系统提示、错误提示（429/503/代理） |
| `tools.py` | 工具实现 + 给模型看的工具说明书 |
| `ffmpeg_bin.py` | 定位 ffmpeg 可执行文件 |

**要点：** 模型只负责选工具和填参数；真正读写文件的是你的 Python 代码——这就是 Agent 开发里最常见的 Tool Calling 模式。

---

## 快速开始

完整操作说明（界面、说法、FAQ）见 **[USAGE.md](./USAGE.md)**。这里只给最短路径：

```bash
git clone https://github.com/guorunquan/video-editing-agent.git
cd video-editing-agent

python -m venv .venv
# Windows: .\.venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # macOS / Linux: cp .env.example .env
```

编辑 `.env`：填入 `GEMINI_API_KEY`（国内通常需 VPN；可设 `HTTPS_PROXY`）。  
申请 Key：https://aistudio.google.com/apikey

```bash
python web_app.py
# 浏览器打开 http://127.0.0.1:7860
# 上传 →「去掉前 3 秒」→「确认」→ 看右侧预览
```

命令行入口：`python main.py`（默认 `samples/demo.mp4`，也可改 `.env` 的 `DEFAULT_VIDEO`）。

---

## 已知限制（v0.4）

- Web 为本地单用户体验壳：无账号、无多会话隔离、无进度条推送
- 无图形时间线 / 拖拽贴纸
- 文字目前是**单行**；复杂多行字幕、动画贴纸未做
- 无多轨、无工程文件格式、无配乐 / 转场
- 依赖 Gemini 在线 API（免费额度有限，可能 429/503）
- 默认快速切片受关键帧影响，可能差半秒；可说「切得更准」走 `precise`
- 变速仅支持 0.5x～2.0x；拼接与文字叠加需重编码，稍慢
- Windows 终端偶发 `ConnectionResetError`（拖视频进度条时）：可忽略，详见 USAGE

---

## 路线图

详细条目与历史版本说明见 [CHANGELOG.md](./CHANGELOG.md)。

- [x] v0.1 探测 + 切片 + 导出管理 + 确认机制  
- [x] v0.2 打开成片 + 文字贴纸（标题/字幕/角标）+ 更顺手的提示  
- [x] v0.3 删中间 + 拼接 + 静音/变速 + 预览截图 + 工作视频记忆  
- [x] v0.4 本地 Web：上传 + 对话 + 页内预览  
- [ ] v0.5 确认 UI / 成片列表 / 会话目录 / 更清晰的失败反馈  
- [ ] 更远：v1.0 体验打磨、配乐、转场、可选本地模型  

欢迎 Issue / PR。

---

## 和 OpenChatCut 的关系

| OpenChatCut | 本项目 |
|-------------|--------|
| 完整多轨编辑器 + Remotion + MCP | CLI + 本地 Web 迷你 Agent |
| 时间线状态机 | 直接 FFmpeg 导出文件 |
| 草稿会话 / 人工批准 | `confirmed=false/true` |
| 适合生产向剪辑 | 适合学习 Agent 与简历作品 |

如果你在学 Agent 开发：建议先跑通本仓库，再去阅读 OpenChatCut 的工具层与编辑会话设计。

---

## 安全与隐私

- **不要**把 `.env`、API Key、个人视频提交到 Git（已在 `.gitignore`）
- `delete_output` 仅允许删除 `output/` 内文件
- 计算器类项目若扩展任意命令执行，请继续保持白名单，不要 `shell=True` 跑用户字符串

---

## License

MIT —— 见 [LICENSE](./LICENSE)

---

## 致谢

- [OpenChatCut](https://github.com/0xsline/OpenChatCut) — Agent-native 视频编辑思路参考  
- Google Gemini API — Function Calling  
- FFmpeg / imageio-ffmpeg — 视频处理  

# Mini Video Agent

用**自然语言**对本地视频做切片的迷你 Agent。

> 你说：「去掉前 5 秒」→ 模型选择工具 → FFmpeg 导出新文件。

本项目是学习向的 **v0.1**：先把「Agent + Tool Calling + 真实改视频」跑通，再逐步加字幕、配乐、时间线等能力。设计思路参考开源项目 [OpenChatCut](https://github.com/0xsline/OpenChatCut)（对话驱动剪辑 / 草稿确认后再落地），但刻意做成学生可维护的命令行小工具，而不是完整剪辑器。

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

- 输出：`output/trim_{start}_{end}_{时间戳}.mp4`
- 实现：优先 FFmpeg stream copy（快）；失败则回退 H.264/AAC 重编码

### 3. 切换工作视频

- **不是单独菜单**，而是通过路径参数切换：
  - 对话里带上绝对路径，例如：  
    `用 "D:\video\dy\xxx.mp4"，去掉前 1 秒`
  - 或改 `.env` 里的 `DEFAULT_VIDEO=...` 后重启
- 默认样本路径：`samples/`（需自行放入视频；大文件不要提交到 Git）

### 4. 管理已导出成片

- `list_outputs`：列出 `output/` 下已导出的 mp4 等
- `delete_output`：删除其中某个成片（**只能删 output，不能删原片**）

### 5. 「先计划，再确认」安全机制

对会改磁盘的操作（切片、删除）：

1. 第一次：`confirmed=false` → 只打印计划，不改文件  
2. 你回复「确认」  
3. 第二次：`confirmed=true` → 真正执行  

这对应 OpenChatCut 里「草稿 / 审阅 / 应用」的缩小版，避免模型一句话直接毁掉素材。

---

## 技术栈

| 部分 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 大模型 | Google Gemini（Function Calling） |
| SDK | `google-genai` |
| 视频处理 | FFmpeg（优先系统 PATH；否则用 `imageio-ffmpeg` 自带二进制） |
| 配置 | `.env` + `python-dotenv` |

---

## 架构（很短）

```text
用户中文指令
    │
    ▼
agent.py          Gemini 多轮 Tool Calling
    │
    ▼
tools.py          probe / trim / list / delete
    │
    ▼
FFmpeg            写出 output/*.mp4
```

| 文件 | 职责 |
|------|------|
| `main.py` | 命令行聊天入口 |
| `agent.py` | 模型循环、系统提示、错误提示（429/503/代理） |
| `tools.py` | 工具实现 + 给模型看的工具说明书 |
| `ffmpeg_bin.py` | 定位 ffmpeg 可执行文件 |

**要点：** 模型只负责选工具和填参数；真正读写文件的是你的 Python 代码——这就是 Agent 开发里最常见的 Tool Calling 模式。

---

## 快速开始

### 1. 克隆与环境

```bash
git clone <你的仓库地址>.git
cd mini-video-agent

python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

编辑 `.env`：

```env
GEMINI_API_KEY=你的密钥
GEMINI_MODEL=gemini-flash-lite-latest
DEFAULT_VIDEO=samples/your.mp4
```

- 申请 Key：https://aistudio.google.com/apikey  
- 国内访问 Google 通常需要 **VPN / 代理**；可设置 `HTTPS_PROXY=http://127.0.0.1:7890`  
- 若遇 `429` 额度用尽或 `503` 繁忙，可换模型，例如：  
  `gemini-2.5-flash-lite` / `gemini-flash-lite-latest`

### 3. 放入测试视频

把任意 mp4 放到 `samples/`，或对话时直接给绝对路径。

### 4. 运行

```bash
python main.py
```

建议试跑：

```text
你: 这个视频多长？
你: 去掉前 5 秒
你: 确认
你: 列出已导出的视频
```

用播放器打开 `output/` 里的新文件查看效果。

---

## 使用示例

**对默认视频切片**

```text
去掉前 5 秒
→ 确认
```

**对任意本地视频切片**

```text
用 "D:\video\demo.mp4"，只保留 2 秒到 8 秒
→ 确认
```

**清理导出结果**

```text
列出已导出的视频
删除 trim_5_15_xxxxxxxx.mp4
→ 确认
```

---

## 已知限制（v0.1）

- 无图形时间线 / 预览窗（命令行 + 本地播放器）
- 无叠加字幕、标题、BGM、转场（规划中）
- 无多轨、无工程文件格式
- 依赖 Gemini 在线 API（免费额度有限，可能 429/503）
- 精密切片在 `-c copy` 模式下受关键帧影响，极端情况可能差半秒；需要更准时可改为强制重编码

---

## 路线图（打算慢慢完善）

- [x] v0.1 探测 + 切片 + 导出管理 + 确认机制  
- [ ] v0.2 叠加标题 / 底部字幕（FFmpeg `drawtext`）  
- [ ] v0.3 删掉中间某一段（前后拼接）  
- [ ] v0.4 简单「打开成片」或生成预览截图  
- [ ] v0.5 可选本地/国产模型，减轻 Gemini 额度问题  
- [ ] 更远：多片段拼接、配乐、简易 Web UI …

欢迎 Issue / PR。

---

## 和 OpenChatCut 的关系

| OpenChatCut | 本项目 |
|-------------|--------|
| 完整多轨编辑器 + Remotion + MCP | 命令行迷你 Agent |
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

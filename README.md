# Mini Video Agent

用**自然语言**对本地视频做切片、加文字贴纸，并能一键打开成片的迷你 Agent。

> 你说：「去掉前 5 秒」→「加标题：决赛高光」→「打开看看」  
> 模型选工具 → FFmpeg 导出 → 系统播放器打开。

本项目是学习向的 **v0.2**：在 v0.1「Agent + Tool Calling + 真实改视频」之上，补上成片播放与文字叠加，并加了一点「下一步提示」让对话更顺手。设计思路参考开源项目 [OpenChatCut](https://github.com/0xsline/OpenChatCut)（对话驱动剪辑 / 草稿确认后再落地），但刻意做成学生可维护的命令行小工具，而不是完整剪辑器。

各版本功能与变更见 **[CHANGELOG.md](./CHANGELOG.md)**（建议与 Git Tag 同步维护）。

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

### 3. 文字贴纸 / 标题字幕（v0.2）

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
- 输出：`output/text_{style}_{文字}_{时间戳}.mp4`

### 4. 打开成片播放（v0.2）

- 工具：`open_output`
- 能力：用系统默认播放器打开 `output/` 里的视频
- 「打开」「播放」「看看效果」→ 默认打开**最新**一条

### 5. 切换工作视频

- **不是单独菜单**，而是通过路径参数切换：
  - 对话里带上绝对路径，例如：  
    `用 "D:\video\dy\xxx.mp4"，去掉前 1 秒`
  - 或改 `.env` 里的 `DEFAULT_VIDEO=...` 后重启
- 默认样本路径：`samples/`（需自行放入视频；大文件不要提交到 Git）

### 6. 管理已导出成片

- `list_outputs`：列出 `output/` 下已导出的 mp4 等（最新会标出来）
- `delete_output`：删除其中某个成片（**只能删 output，不能删原片**）

### 7. 「先计划，再确认」安全机制

对会改磁盘的操作（切片、加字、删除）：

1. 第一次：`confirmed=false` → 只打印计划，不改文件  
2. 你回复「确认」  
3. 第二次：`confirmed=true` → 真正执行  

这对应 OpenChatCut 里「草稿 / 审阅 / 应用」的缩小版，避免模型一句话直接毁掉素材。

### 8. 一点点「人性化」（v0.2）

- 成功后附带「接下来可以试试」提示（打开 / 加标题 / 调字号）
- 样式预设 + 默认最新成片，少说参数也能做完
- 助手语气更像同学帮忙，会主动提自然下一步

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
tools.py          probe / trim / text / open / list / delete
    │
    ▼
FFmpeg / 系统播放器
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
git clone https://github.com/guorunquan/video-editing-agent.git
cd video-editing-agent

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
# 可选：中文字体（一般不用，Windows 会自动找微软雅黑）
# VIDEO_FONT=C:\Windows\Fonts\msyh.ttc
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
你: 加标题：决赛高光
你: 确认
你: 打开刚导出的视频
```

---

## 使用示例

**对默认视频切片并预览**

```text
去掉前 5 秒
→ 确认
→ 打开刚导出的视频
```

**加标题 / 字幕 / 角标**

```text
加标题：今日高光
→ 确认

底部加字幕：感谢观看
→ 确认

右上角贴纸：HIT
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

## 已知限制（v0.2）

- 无图形时间线 / 拖拽贴纸（命令行 + 系统播放器）
- 文字目前是**单行**；复杂多行字幕、动画贴纸未做
- 无多轨、无工程文件格式、无配乐 / 转场
- 依赖 Gemini 在线 API（免费额度有限，可能 429/503）
- 精密切片在 `-c copy` 模式下受关键帧影响，极端情况可能差半秒；需要更准时可改为强制重编码
- 文字叠加必须重编码，比纯 copy 切片稍慢

---

## 路线图

详细条目与历史版本说明见 [CHANGELOG.md](./CHANGELOG.md)。

- [x] v0.1 探测 + 切片 + 导出管理 + 确认机制  
- [x] v0.2 打开成片 + 文字贴纸（标题/字幕/角标）+ 更顺手的提示  
- [ ] v0.3 删掉中间某一段（前后拼接）  
- [ ] v0.4 预览截图 / 字号位置迭代更方便  
- [ ] v0.5 可选本地/国产模型，减轻 Gemini 额度问题  
- [ ] 更远：多片段拼接、配乐、简易 Web UI（本地 demo，非 SaaS）  

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

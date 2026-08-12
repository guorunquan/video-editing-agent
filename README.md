# 灵剪 EditMate

用**自然语言**分析和剪辑本地视频，并在 v2.0 支持“多方案 → 配乐/特效 → 视频预览 → 用户确认 → 高清导出”的迷你 Agent。

> 你说：「去掉前 5 秒」→「和另一段拼起来，命名为拼接」→「加标题」→「截第 1 秒看看」  
> 模型生成结构化方案 → 确定性草稿与 FFmpeg 预览 → 用户确认 → 高清导出。

## v2.0 重点能力

- 选择方案后先生成保留源分辨率的视频预览；没有预览不能确认最终导出。
- 本地配乐上传与音乐库，内置 150 BPM 免版权高燃循环，支持自动选曲、音量、循环、淡入淡出、原声混音和响度规范化。
- 轻量节拍分析与安全卡点：只在 0.18 秒范围内吸附切点，不牺牲关键内容。
- 结构化特效：淡入淡出、交叉渐变、慢放、快速放大、闪白和轻微震动。
- 游戏视频方案支持高燃卡点、操作还原和解说展示三种包装方向。
- `EditDraft` 保存素材、片段、配乐、特效、预览、版本与确认状态；预览和成片共用渲染器。

已延期到后续版本：逐帧击杀 OCR、自动目标跟踪、电影级光流、在线音乐抓取、完整多轨剪辑器。

灵剪 EditMate 是一个自然语言驱动的视频创作助手：用户可以描述想要的视频效果，也可以让系统自行分析素材，完成素材整理、粗剪、字幕、简单包装，并逐步扩展配乐能力，让新手轻松成片，也帮助熟练剪辑者快速完成重复工作。

本项目当前为学习向的 **v2.0**：CLI Agent + 本地 Web 体验站，在 v1.x 基础剪辑、字幕、水印和精确定位之上，加入了结构化多方案、`EditDraft`、原清视频预览、本地配乐/卡点和首批高光特效。设计思路参考 [OpenChatCut](https://github.com/0xsline/OpenChatCut)，但刻意做成学生可维护的迷你工具，而不是完整剪辑器。

## 文档导航

| 文档 | 给谁看 |
|------|--------|
| **[总体目标](./docs/PRODUCT_GOALS.md)** | **产品方向**：项目定位、目标用户、成功标准与能力边界 |
| **[需求分析](./docs/REQUIREMENTS_ANALYSIS.md)** | **产品迭代**：需求优先级、验收标准、版本路线与风险 |
| **[USAGE.md](./USAGE.md)** | **使用者**：安装、开网页、说法、FAQ |
| **[PROBLEMS.md](./PROBLEMS.md)** | 排障：项目过程中踩过的坑与解法 |
| **[HANDOFF.md](./HANDOFF.md)** | **下一个 Agent / 开发者**：架构、约定、v2.0 现状与后续方向 |
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

### Web 体验站（v2.0）

- 入口：`python web_app.py` → http://127.0.0.1:7860  
- 上传视频、对话剪辑、页内播放器  
- 时间码、拖动定位、逐帧前进/后退、入点/出点和当前帧截取
- 确认执行 / 取消按钮；成片列表点选播放、改名、打开文件位置  
- 对话记录：按日期分组的多会话目录  
- 截帧预览下方标注「第 N 秒」
- 成片列表与截帧预览支持独立管理
- 首页三步引导与常用任务快捷按钮
- 结构化确认计划、处理状态与成片下载
- 视频分析入口：可询问「这个视频怎么剪」，获取带时间点和证据的建议（分析阶段不自动改文件）
- 回复「方案一」可直接生成真实视频预览并替换播放器；不满意可返回原视频
- 方案卡可调整本地配乐、音量和效果，预览成功后才允许确认高清导出
- 「给整个原视频配高燃音乐」会保留原声并直接生成全片混音预览
- 成片列表可直接设为当前工作视频；截帧预览可单独删除
- 首页使用指南与「AI 教你怎么剪」首位快捷入口
- 自动字幕：本地 faster-whisper 转录并由 FFmpeg 烧录
- 字幕批改：按原文或批量替换 SRT，支持跨分屏字幕整句替换并重新烧录
- 固定位置水印：支持模糊或遮盖
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
    ├── video_analysis.py  多模态分析与结构化方案
    ├── editor_v2.py       EditDraft / 配乐 / 特效 / 预览渲染
    ▼
tools.py          v1.x 基础剪辑工具白名单
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
| `video_analysis.py` | 视频理解、结构化方案、校验和缓存 |
| `editor_v2.py` | v2 草稿、音乐分析、特效和确定性 FFmpeg 渲染 |
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
- 无可拖拽图形时间线、完整多轨、撤销/重做和复杂字幕编辑
- 内置配乐仅为程序生成的基础高燃循环；不支持在线音乐搜索/下载，更丰富的 BGM 需用户上传本地音频
- 原清预览不降分辨率，因此渲染时间和文件大小会高于低清代理预览
- 文字目前为**单行**  
- 依赖 Gemini 在线 API（可能 429/503）  
- 视频分析默认会把视频发送给 Gemini；本地 Whisper 转录为可选能力
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
- [x] v1.0 体验站打磨（示例引导、结构化确认、任务状态、下载、测试）
- [x] v1.5 视频理解 MVP + 成片/截帧管理体验
- [x] v1.7 简体自动字幕、批量字幕替换、分屏字幕整句合并、截帧预览完整展示
- [x] v1.8 精确时间定位、时间码、逐帧控制、入出点、当前帧截取与媒体管理
- [x] v1.9 多方案剪辑 Agent、结构化分析和策略模板库
- [x] v2.0 方案视频预览、配乐卡点、首批高光特效和预览后确认

欢迎 Issue / PR。

---

## 和 OpenChatCut 的关系

| OpenChatCut | 本项目 |
|-------------|--------|
| 完整多轨编辑器 + Remotion + MCP | CLI + 本地 Web 迷你 Agent |
| 时间线状态机 | 轻量 `EditDraft` + FFmpeg 预览/导出 |
| 草稿会话 / 人工批准 | v1 工具两阶段确认 + v2 预览门禁 |
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

# Agent / 开发者交接文档

面向下一个接手仓库的 AI Agent 或人类开发者。当前基线为 **v2.0**；版本事实以 [CHANGELOG.md](./CHANGELOG.md) 为准。

仓库：https://github.com/guorunquan/video-editing-agent

## 1. 项目定位

**灵剪 EditMate** 是中文对话驱动的本地视频创作助手。Gemini 负责视频理解和工具选择，Python/FFmpeg 负责确定性执行，FastAPI Web 提供方案、预览、确认和媒体管理界面。

这是本地体验站和学习型作品，不是 SaaS，也不是 Premiere 级多轨编辑器。

## 2. v2.0 已实现事实

- 视频分析输出 2～3 个有实际改动的结构化方案；完整保留原片的空方案会被过滤。
- 用户回复「方案一」「看看方案一」即可创建 `EditDraft`、渲染真实视频预览，并让左侧播放器切换到预览。
- 预览保持源视频分辨率，H.264 CRF 20；确认前不会覆盖工作视频或写入正式成片列表。
- 不满意可返回原视频，调整配乐/音量/特效后可重新预览；确认后才高清导出。
- 本地配乐库支持上传、自动匹配、循环、淡入淡出、保留原声混音和基础节拍吸附。
- 首次访问音乐库会生成免版权的 `内置高燃电子_150bpm.wav`，无需额外下载素材。
- 「配上高燃音乐」「给整个原视频直接配一段高燃音乐」会直接创建整段配乐草案，不会先静音。
- 首批效果：淡入淡出、交叉渐变、慢放、快速放大、闪白、轻微震动。
- v1.x 的切片、拼接、文字、字幕、水印、媒体管理和确认机制继续保留。
- 当前自动化回归：`tests/test_v1.py` + `tests/test_v2.py`，共 **31 项**。

## 3. 架构心智模型

```text
用户（CLI / Web）
    → agent.py
        ├─ 确定性意图路由：方案选择 / 配乐 / 返回原视频
        ├─ Gemini Function Calling：传统工具选择
        └─ video_analysis.py：视频上传、结果校验、方案缓存
    → editor_v2.py
        ├─ EditDraft 持久化
        ├─ 本地音乐分析与自动匹配
        └─ FFmpeg 预览 / 最终导出
    → tools.py：v1 工具白名单与 confirmed 两阶段执行
    → web_app.py：API、会话、草案状态、媒体安全边界
    → static/：播放器、方案卡、音乐上传、确认交互
```

核心状态分三层：

1. **原/工作视频**：用户当前继续编辑的正式输入。
2. **草案与预览**：`data/drafts/` 和 `output/plan_previews/`，可反复替换，不进入成片列表。
3. **正式成片**：确认后写入 `output/v2_*.mp4`，并成为新的工作视频。

## 4. 硬约定

1. 模型不能生成任意 shell；只能走白名单或结构化草案。
2. v1 写盘工具仍执行 `confirmed=false → 用户确认 → confirmed=true`。
3. v2 方案必须先成功生成视频预览，`confirm_draft()` 才允许最终导出。
4. 预览可以写受控临时文件，但不得改变工作视频；取消/返回原视频要清除当前草案显示。
5. Web 层不自行拼 FFmpeg；v1 在 `tools.py`，v2 在 `editor_v2.py`。
6. 删除与重命名只能操作允许目录；不得触碰用户原片。
7. `uploads/`、`output/`、`data/` 都是运行数据；只提交目录占位文件，不提交用户素材或会话。

## 5. 关键文件

| 路径 | 职责 | 修改注意 |
|------|------|----------|
| `agent.py` | 会话循环、提示词、确定性 v2 意图路由 | 方案/配乐意图应先于 Gemini 通用回复 |
| `video_analysis.py` | VLM 上传、JSON 提取、校验、空方案过滤 | 所有外部结构先校验再创建草案 |
| `editor_v2.py` | EditDraft、音乐、效果、预览/导出 | 预览与正式输出语义不能混淆 |
| `tools.py` | v1 工具及声明/分发 | 新 v1 工具保持 confirmed 协议 |
| `web_app.py` | FastAPI、state、草案 API、路径安全 | 媒体 URL 只能来自允许目录 |
| `static/*` | 播放器和方案卡 | 修改后同步更新静态资源 `?v=` 防缓存 |
| `tests/test_v2.py` | v2 草案、音乐、路由和 API 回归 | 新意图必须补确定性测试 |
| `uploads/music/` | 本地音乐库 | 自定义音乐默认忽略；内置 WAV 由代码生成 |

## 6. 本地运行与验收

```powershell
cd D:\agent-project\mini-video-agent
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python web_app.py
```

浏览器打开 http://127.0.0.1:7860 并按 `Ctrl+F5`。最短 v2 验收：

1. 上传一段视频，输入「分析一下这个视频，告诉我怎么剪比较好」。
2. 回复「方案一」；应出现方案卡，左侧变为源分辨率的预览，卡片显示配乐名称和效果。
3. 回复「不满意，返回原视频」；播放器应恢复原工作视频。
4. 输入「给整个原视频直接配一段高燃音乐」；应生成整段预览并保留原声。
5. 点击确认；正式文件进入成片列表，并成为新工作视频。
6. 运行测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`。

若出现 WinError 10048，说明旧服务仍占用 7860；结束旧进程或设置 `$env:WEB_PORT=7861`。完整排障见 [PROBLEMS.md](./PROBLEMS.md)。

## 7. v2.0 雷区

- **不要让模型决定有没有配乐工具。** 配乐和方案选择是稳定产品意图，必须由代码路由。
- **不要只返回剪辑文案。** 用户选方案后必须渲染视频；左侧播放器 URL 以当前草案预览优先。
- **不要把静音当作加配乐的前置步骤。** FFmpeg 混音链会自动降低原声并叠加 BGM。
- **不要降低预览分辨率。** 当前只用更快 preset 控制等待时间，保持 CRF 20 和原始尺寸。
- **不要保留“0～全长”空方案。** 分析校验会过滤没有剪切、效果或其他实际变化的候选。
- **不要恢复已废弃的通用 `render_edit_plan` 模型工具。** 草案创建、预览和确认应经过受控 API/路由。
- **注意旧进程和浏览器缓存。** 后端代码更新必须重启，前端资源更新还要 Ctrl+F5。

## 8. 明确延期范围

本次已同意延期以下五项：

1. 基于击杀播报/OCR 的逐帧高光定位。
2. 目标检测与自动跟踪式放大。
3. 光流补帧级电影慢动作。
4. 在线音乐检索、版权授权和自动下载。
5. 完整多轨时间线编辑器。

拖拽式图形时间线、逐操作启停和完整 undo/redo 也尚未实现。下一版优先考虑草案编辑能力和效果质量，而不是扩成云端产品。

## 9. 文档维护约定

| 变更类型 | 更新文档 |
|----------|----------|
| 用户能力/交互变化 | `README.md`、`USAGE.md`、`CHANGELOG.md` |
| 新坑或修复 | `PROBLEMS.md` |
| 架构/测试/延期范围 | `HANDOFF.md`、`docs/REQUIREMENTS_ANALYSIS.md` |
| 产品方向 | `docs/PRODUCT_GOALS.md` |
| 可复用工程经验 | `LEARNING.md`、`DAILY_LEARNING.md` |

发布前检查：测试通过、`git status` 不含 `.env`/用户媒体/运行数据、文档版本一致。只有正式发布才创建 tag。

## 10. 给新 Agent 的开工提示词

```text
你在接手 guorunquan/video-editing-agent，当前基线是 v2.0。
先读 HANDOFF.md、CHANGELOG.md、PROBLEMS.md、USAGE.md 和 docs/REQUIREMENTS_ANALYSIS.md。
核心约定：v2 方案必须先生成真实预览再确认；预览不改变工作视频；
确定性的方案选择/配乐/返回原视频意图先于 Gemini 路由；
v1 工具仍用 confirmed 两阶段协议；静态资源变化要 bump ?v=。
不要提交 .env、用户视频、音乐、data 或 output 运行文件。
```

## 11. 安全

- 不提交 `.env`、API Key、用户视频、音乐和会话内容。
- 所有媒体路径必须通过允许目录校验。
- 禁止 `shell=True` 执行模型生成的命令字符串。
- 本地服务没有账号隔离，不应直接暴露到公网。

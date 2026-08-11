# Changelog

本项目的版本迭代记录。每个版本只写**用户能感知的能力**，方便对照 Tags / Releases。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号尽量遵循语义化思路（学习项目里以功能里程碑为主）。

查看历史代码：

```bash
git checkout v0.1.0
git checkout v0.2.0
git checkout v0.3.0
git checkout v0.4.0
git checkout v0.5.0
git checkout main
```

Tags：https://github.com/guorunquan/video-editing-agent/tags

---

## [1.9.0] - 2026-08-11

### Added
- 视频分析现在保存为结构化、带稳定 ID 的剪辑方案；每个方案包含策略、目标、平台、保留片段、证据、预计时长和置信度。
- 引入三种差异化剪辑策略：高完播率短版、信息完整版本、轻松故事节奏版；不足两套有效方案时会进行一次定向重试，而不是把单一建议伪装成选择。
- 网页会以方案卡片展示可执行计划，支持跳到首段时间点并一键采用方案。
- 新增 `render_edit_plan`：确认前仅展示草案，确认后使用 FFmpeg 精确裁切并拼接多个保留片段。

### Safety
- 后端拒绝时间越界、重叠、无效或乱序的方案片段；预计时长由后端根据保留片段重新计算。
- 上传、切换成片或新建会话会清除旧分析，避免将旧素材方案应用到新视频。

### Changed
- Web/API 与静态资源版本更新为 `1.9.0`。

---

## [1.8.0] - 2026-08-10

### Added
- Web 播放器显示当前时间和总时长，支持拖动进度条和时间输入跳转。
- 支持前进/后退 1 秒、逐帧前进/后退、设置入点和出点。
- 支持从当前播放位置截取 PNG 帧，并保存到 `output/previews`。
- 成片列表和截帧预览支持独立打开和管理。

### Changed
- Web 播放器、时间定位和媒体管理形成 v1.8 的精确剪辑工作台。
- 健康检查、Web 页面和静态资源版本统一为 `1.8.0`。

### Documentation
- README、USAGE、HANDOFF、总体目标和需求分析同步到 v1.8。

---

## [1.7.0] - 2026-08-05

### Fixed
- 自动字幕统一转换为简体中文，并增加 OpenCC 依赖。
- 新增 `edit_subtitles`，支持单条或批量替换 SRT 字幕；修改已有字幕时从原视频重新烧录，避免重复叠加。
- 分屏字幕支持跨连续 SRT 片段整句匹配，避免只替换第一块字幕。
- Agent 工具编排轮次从 6 轮提高到 12 轮，复杂批量请求不再过早停止。
- 截帧预览不再限制显示前 6 张，改为多行滚动展示全部图片。
- 更新 Web 启动提示与静态资源版本号。

### Documentation
- README、USAGE、HANDOFF 与 PROBLEMS 同步到 v1.7，补充字幕问题的原因和解决方式。

---

## [1.0.0] - 2026-08-04

### Added（v1.0）

- Web 首页增加三步引导和常用示例任务
- 待确认计划增加机器可读结构，前端展示具体操作摘要
- 增加处理任务状态接口 `/api/jobs/{job_id}`
- 成片列表增加下载入口
- 健康检查版本更新为 v1.0.0
- 增加文件名、确认机制、时间参数的最小回归测试

### Added（v0.5 之后、尚未单独打 tag）

- 对话记录：按日期分组的**多会话目录**；约 3 小时无消息自动开新会话；「新对话」保留旧会话
- 成片列表：网页 **改名**、**打开文件位置**、打开 `output/` 文件夹
- 截帧预览：图片下方标注「第 N 秒」
- Agent 工具 `rename_output`：对话「命名为拼接」等（`safe_output_stem` 支持 `1.5倍速`）
- 文档：
  - [PROBLEMS.md](./PROBLEMS.md) — 全程踩坑与排障
  - [HANDOFF.md](./HANDOFF.md) — 下一任 Agent / 开发者交接（含 v1.5 / v1.6 建议）
  - README / USAGE / LEARNING 交叉链接已同步

### Fixed

- 重命名「1.5倍速…」被 `Path.stem` 截成 `1.mp4`
- 待确认按钮依赖模型口语导致不出现（改为看工具结果 `last_needs_confirm`）
- 上传后仍播旧成片；前端超时与 VPN 提示不清晰等问题（见 PROBLEMS）

## [1.5.0] - 2026-08-04

**主题：** AI 视频理解 MVP · 成片与截帧管理体验

### Added

- 「AI 教你怎么剪」快捷入口置于首位
- 视频理解：Gemini 分析画面、音频和时间点，输出带证据的剪辑建议
- 可选 `faster-whisper` 本地时间戳转录与分析缓存
- 成片列表增加「操作此视频」，可直接将成片设为当前工作视频
- 截帧预览增加单张删除按钮
- 首页改为实用使用指南，说明 AI 分析、选择方案和确认导出流程

### Changed

- Web/API 版本更新为 `1.5.0`
- 文档、环境变量说明和路线图同步到 v1.5

### 下一步

- v1.7：文本驱动剪辑、竖屏导出、移动水印跟踪

## [1.6.0] - 2026-08-05

**主题：** 自动字幕 · 固定位置水印处理

### Added

- `add_auto_subtitles`：本地 faster-whisper 识别语音，生成 SRT 并烧录到视频
- `remove_watermark`：固定区域水印模糊或遮盖
- 页面增加「自动字幕」「去水印」快捷入口
- 自动字幕和水印处理均遵守确认后写盘
- 增加 SRT 时间戳和水印区域计算测试

### Notes

- `faster-whisper` 为可选依赖，需要单独安装
- 水印处理第一版只支持固定区域，不保证移动水印无痕恢复

### Product

- 产品名称统一为「灵剪 EditMate」：自然语言描述效果或让系统分析素材，辅助完成整理、粗剪、字幕和简单包装

---

## [0.5.0] — 2026-08-02

**主题：** Web 确认按钮 · 成片点选 · 对话记录 · 更清晰报错  

Tag：`v0.5.0`（发布时打）

### Added

- 待确认回复下方出现 **确认执行 / 取消** 按钮（仍可打字「确认」）
- 播放器下方 **成片列表**：点击即可切换预览
- **对话记录**面板：查看本机保存的聊天历史（`data/chat_log.json`）
- `/api/history`：返回对话记录；清空对话时一并重置记录
- 网络 / VPN / 429 / 503 等错误的更口语提示
- 截帧条增加说明：某一秒的静止预览图

### Changed

- Web 版本号与文案升至 v0.5；剪辑工具能力仍与 v0.3/0.4 相同
- 系统提示支持用户「取消」待确认计划

### Notes

- 对话记录仅本机单用户；「清空对话」会清空记录，不删成片
- 会话目录隔离仍未做（留给更远版本）

---

## [0.4.0] — 2026-08-01

**主题：** 本地 Web 体验壳——上传 + 对话 + 页内预览  

Tag：`v0.4.0`（发布时打）

### Added

- `web_app.py`：FastAPI 本地站（默认 `http://127.0.0.1:7860`）
  - 上传视频到 `uploads/` 并设为工作视频
  - `/api/chat` 复用现有 Gemini Agent 与全部剪辑工具
  - `/api/state` 返回工作视频 / 最新成片 / 预览图
  - `/media/...` 安全提供 `uploads/`、`output/`、`samples/` 内文件
- `static/`：单页前端（上传、聊天、播放器、截帧条、快捷指令）
- `WEB_MODE=1` 时 `open_output` 不再弹系统播放器，改为提示网页预览
- `get_media_state` / `set_working_video`：给 Web 层读状态、设片源
- 使用说明：[USAGE.md](./USAGE.md)（安装、网页操作、常用说法、FAQ）

### Changed

- 剪辑能力仍与 v0.3 相同；CLI（`python main.py`）保留
- README / 路线图：Web UI 前移为 v0.4；预览优先较新的工作视频，避免上传后仍播旧成片

### Notes

- 本机单用户 demo，无账号、无多会话隔离
- 上传默认上限 100MB（可用 `WEB_MAX_UPLOAD_MB` 调整）
- 仍依赖本机 FFmpeg + Gemini API / VPN
- Windows 拖视频进度条时终端可能刷 `ConnectionResetError`，一般可忽略（见 USAGE）

---

## [0.3.0] — 2026-08-01

**主题：** 删中间段 + 拼接 / 静音 / 变速 / 预览截图，剪辑链路更完整  

Tag：`v0.3.0`（发布时打）

### Added

- `cut_out`：删除中间一段，前后拼回成片
- `concat_videos`：按顺序拼接多段视频（文件名或路径列表）
- `mute_audio`：去掉音轨，只保留画面
- `change_speed`：0.5x～2.0x 变速导出
- `export_preview_frame`：截取某一秒 PNG 预览图（默认自动打开，无需确认）
- 会话工作视频记忆（`data/session.json`）：probe / 导出后会记住当前片源
- 待确认文案更口语（先人话摘要，再附计划详情）
- `trim_keep` 支持 `precise=true` 强制重编码精密切片

### Changed

- 系统提示覆盖删中间 / 拼接 / 静音 / 变速 / 截帧等说法
- 启动欢迎语更新为 v0.3 示例
- README / 路线图同步到 v0.3

### Notes

- 变速倍率受 FFmpeg `atempo` 限制（0.5～2.0）
- 拼接对不同来源统一重编码，更稳但稍慢
- 仍无图形时间线、多轨、配乐

---

## [0.2.0] — 2026-07-30

**主题：** 打开成片 + 文字贴纸，对话更顺手  

Tag：`v0.2.0`

### Added

- `open_output`：用系统默认播放器打开 `output/` 成片（默认最新）
- `add_text_overlay`：FFmpeg `drawtext` 叠加一行文字
  - 样式预设：`title`（居中大标题）/ `subtitle`（底部字幕）/ `sticker`（右上角标）
  - 可指定位置、字号、颜色、出现时段
  - 默认加工最新成片；自动探测中文字体（Windows 优先微软雅黑）
- 成功后的「接下来可以试试」提示；列表标出最新成片
- `.env` 可选 `VIDEO_FONT` 手动指定字体

### Changed

- 助手系统提示更口语，会主动提自然下一步
- 启动欢迎语更新为 v0.2 示例对话
- README / LEARNING 同步到 v0.2 能力

### Notes

- 文字目前为单行；叠加需重编码，比纯 copy 切片稍慢
- 仍无图形时间线、多轨、配乐

---

## [0.1.0] — 2026-07-28

**主题：** 跑通「自然语言 → Tool Calling → FFmpeg 切片」  

Tag：`v0.1.0`（对应提交 `79f2087`）

### Added

- `probe_video`：探测时长、分辨率、大小
- `trim_keep`：只保留 `[start, end)` 并导出到 `output/`
- `list_outputs` / `delete_output`：管理已导出成片（删除仅限 `output/`）
- 写磁盘前确认机制：`confirmed=false` 预览 → 用户确认 → `confirmed=true` 执行
- Gemini Function Calling Agent（`agent.py` + `tools.py`）
- FFmpeg 定位（系统 PATH 或 `imageio-ffmpeg`）
- README、学习指南 `LEARNING.md`

### Notes

- 命令行交互；无预览窗、无字幕/贴纸
- 依赖 Gemini 在线 API

---

## 版本对照速查

| 版本 | 一句话 | Tag |
|------|--------|-----|
| 0.1.0 | 探测 + 切片 + 导出管理 + 确认 | `v0.1.0` |
| 0.2.0 | + 打开播放 + 文字贴纸 + 更顺手提示 | `v0.2.0` |
| 0.3.0 | + 删中间 / 拼接 / 静音 / 变速 / 截帧预览 | `v0.3.0` |
| 0.4.0 | + 本地 Web：上传 / 对话 / 页内预览 | `v0.4.0` |
| 0.5.0 | + 确认按钮 / 成片点选 / 对话记录 | `v0.5.0` |
| main（未 tag） | + 多会话目录 / 对话改名 / 截帧标秒 / PROBLEMS+HANDOFF | （见 Unreleased） |

发布新版本时建议同步：

1. 更新本文件（把条目从 Unreleased 挪到正式版本节）
2. 更新 README / USAGE / HANDOFF（若有架构变化）
3. `git tag -a vX.Y.Z` 并 push tag

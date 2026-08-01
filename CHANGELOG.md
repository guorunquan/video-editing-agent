# Changelog

本项目的版本迭代记录。每个版本只写**用户能感知的能力**，方便对照 Tags / Releases。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号尽量遵循语义化思路（学习项目里以功能里程碑为主）。

查看历史代码：

```bash
git checkout v0.1.0
git checkout v0.2.0
git checkout v0.3.0
git checkout v0.4.0
git checkout main
```

Tags：https://github.com/guorunquan/video-editing-agent/tags

---

## [Unreleased]

计划中（尚未发布，仅作备忘）：

- v0.5 确认 UI 卡片化 / 成片列表点选 / 会话目录隔离 / 失败日志更可读
- 更远：v1.0 体验站打磨、配乐、转场、可选本地模型

文档（不单独发版也可合进下一次 tag）：

- 新增面向使用者的 [USAGE.md](./USAGE.md)；README / LEARNING 交叉链接已同步

体验小修：

- Web 聊天：约 20 秒等待提示、约 60 秒超时停止并提示重试；增加「重试上一条」
- 默认样本改为仓库内 `samples/demo.mp4`（并允许该文件进入 Git）

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

发布新版本时建议同步：

1. 更新本文件（把条目从 Unreleased 挪到正式版本节）
2. 更新 README 功能一览 / 路线图勾选
3. `git tag -a vX.Y.Z` 并 push tag

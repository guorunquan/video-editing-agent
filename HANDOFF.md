# Agent / 开发者交接文档

面向：**下一个接手本仓库的 AI Agent 或人类开发者**（当前为 v1.0，准备做 v1.5）。
读完应能在不翻完整聊天记录的情况下，安全地改代码、发版本、排障。

| 先读 | 用途 |
|------|------|
| 本文 | 架构、约定、下一步、雷区 |
| [README.md](./README.md) | 项目定位与功能总览 |
| [USAGE.md](./USAGE.md) | 用户怎么用 |
| [CHANGELOG.md](./CHANGELOG.md) | 版本事实来源 |
| [PROBLEMS.md](./PROBLEMS.md) | 已踩坑与解法 |
| [LEARNING.md](./LEARNING.md) | Tool Calling 学习向说明 |

仓库：https://github.com/guorunquan/video-editing-agent  

---

## 1. 项目是什么（一句话）

**中文对话驱动的本地视频剪辑迷你 Agent**：Gemini Function Calling 选工具 → Python/`tools.py` 调 FFmpeg 写 `output/` → CLI 或本地 Web 预览。  
学习 / 作品集向，**不是** SaaS、不是多轨时间线剪辑器。

参考灵感：[OpenChatCut](https://github.com/0xsline/OpenChatCut)，但刻意保持可维护的小体量。

---

## 2. 当前版本事实（接手时请先核对 CHANGELOG）

截至当前，主线能力已完成 **v1.0 体验闭环**（以 `CHANGELOG.md` 的最新节为准）：

**已有剪辑工具（`tools.py`）**

| 工具 | 作用 |
|------|------|
| `probe_video` | 时长 / 分辨率等 |
| `trim_keep` | 保留区间 |
| `cut_out` | 删中间 |
| `concat_videos` | 多段拼接 |
| `mute_audio` / `change_speed` | 静音 / 变速（0.5～2.0） |
| `add_text_overlay` | 单行文字（title/subtitle/sticker） |
| `export_preview_frame` | 截帧 PNG |
| `open_output` / `list_outputs` / `delete_output` | 打开 / 列表 / 删成片 |
| `rename_output` | 重命名成片（对话可「命名为拼接」） |

**Web（`web_app.py` + `static/`）**

- 上传、聊天、页内播放、确认按钮、成片列表（播放 / 改名 / 打开位置）  
- 多会话对话记录（按日期目录，`data/chat_sessions.json`）  
- 截帧条标注「第 N 秒」  
- `WEB_MODE=1` 时不弹系统播放器  
- 首页三步引导与快捷示例任务
- 结构化待确认计划、任务状态接口 `/api/jobs/{job_id}`、成片下载
- `tests/test_v1.py` 覆盖文件名、确认机制、路径与时间参数基础回归

**入口**

- Web：`python web_app.py` → http://127.0.0.1:7860  
- CLI：`python main.py`  
- 默认样本：`samples/demo.mp4`（`DEFAULT_VIDEO`）

---

## 3. 架构（改代码时的心智模型）

```text
用户（CLI / Web）
    → agent.py          Gemini + SYSTEM_PROMPT + tools 声明
        → run_tool()    tools.py 分发
            → FFmpeg    真正读写文件
    → web_app.py        仅壳：上传 / state / history / 静态页
        → static/       前端体验（确认卡片、列表、会话目录）
```

**硬约定**

1. **模型不直接拼 shell**；只选白名单工具。  
2. **写盘要确认**：`confirmed=false` 出计划 → 用户确认 → `confirmed=true`。  
   （`probe` / `open` / `list` / `export_preview_frame` 除外。）  
3. **Web 不复制剪辑逻辑**；剪辑只活在 `tools.py`。  
4. **删除只能动 `output/`**，不能删用户原片。  

---

## 4. 关键文件地图

| 路径 | 职责 | 改它时注意 |
|------|------|------------|
| `agent.py` | 循环、`SYSTEM_PROMPT`、`last_needs_confirm` | 新工具要教模型何时调用 |
| `tools.py` | 工具实现 + `TOOL_DECLARATIONS` + `run_tool` | 新工具四件套：函数 / 声明 / 分发 / 提示词 |
| `web_app.py` | FastAPI、会话存储、成片 rename/reveal API | 安全路径只允许 uploads/output/samples |
| `static/*` | UI | **改完务必 bump `?v=`**（防缓存） |
| `main.py` | CLI | 保持与 Web 共用 Agent |
| `ffmpeg_bin.py` | 找 ffmpeg | 少动 |
| `.env` / `.env.example` | 密钥与代理 | **永不提交 `.env`** |
| `data/` | session / chat_sessions（gitignore） | 勿当源码 |
| `samples/demo.mp4` | 默认可提交样本 | 其它大视频勿提交 |

---

## 5. 本地运行（接手验收）

```powershell
cd D:\agent-project\mini-video-agent
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # 填 GEMINI_API_KEY；国内建议 HTTPS_PROXY
python web_app.py
```

最短验收：

1. 打开页面，Ctrl+F5  
2. 「这个视频多长？」应出现 `[tool] probe_video`  
3. 「去掉前 1 秒」→ 确认按钮 → 成片列表出现新文件  
4. 「命名为测试名」→ 确认后文件名变化  

若卡在 Gemini：先读 [PROBLEMS.md](./PROBLEMS.md) §3。

---

## 6. 扩展检查清单（加工具）

1. 在 `tools.py` 实现函数（失败返回可读中文；写盘走 `_pending`）  
2. 写入 `TOOL_DECLARATIONS`  
3. `run_tool` 分发  
4. 更新 `SYSTEM_PROMPT`  
5. 若 Web 要展示：扩展 `/api/state` 或专用 API + `static/`，并 bump `?v=`  
6. 更新 `CHANGELOG.md` + `USAGE.md`（用户能感知的）  
7. 踩坑记入 `PROBLEMS.md`  

---

## 7. 已知雷区（必读）

1. **代理**：Python 需要 TUN 或 `HTTPS_PROXY`，不能假设「用户浏览器已开 VPN」。  
2. **待确认 UI**：以工具结果 / `last_needs_confirm` 为准，勿只信模型口语。  
3. **文件名**：禁止对用户昵称用裸 `Path.stem`（`1.5倍速` → `1`）；用 `safe_output_stem()`。  
4. **静态缓存**：用户强依赖 Ctrl+F5；你方必须改 query 版本号。  
5. **Windows 视频 206**：Range 中断的 10054 日志可忽略。  
6. **单进程聊天锁**：`/api/chat` 有简单锁，避免连点堆请求。  
7. **不要**把本项目做成公网多租户，除非产品目标明确改变（当前是本地 demo）。

---

## 8. 建议的后续版本方向

以下为产品讨论过的方向，**不是承诺**；接手后按优先级裁剪。

### v1.0（体验站闭环，已完成）

目标一句话：

> 打开网页 → 上传/用样本 → 对话完成一轮有意义的剪辑 → 预览与下载清楚 → 别人 5 分钟能玩懂。

候选：

- 欢迎页示例片 + 3 条示例指令一键填入  
- 导出进度 / 忙碌状态更明显（避免误以为卡死）  
- 确认卡片展示人话摘要（弱化 JSON）  
- 文档已与 v1.0 能力对齐；发布时创建 tag `v1.0.0`
- （可选）按上传会话隔离工作目录 `sessions/{id}/`

### v1.5（能力加深，仍保持迷你）

候选（任选，避免一次做完）：

- 配乐 / 简单转场  
- 文字计划记忆（「字号改成 40」少重复确认）  
- 可选本地 / 国产模型，减轻 Gemini 额度  
- 更稳的多段工程状态（仍不必上完整时间线）

**明确可以继续不做的**（除非改定位）：账号计费、云端转码集群、Premiere 级多轨。

---

## 9. 文档维护约定

| 变更类型 | 更新哪些 |
|----------|----------|
| 用户能感知的能力 | `CHANGELOG.md` + `USAGE.md` + 必要时 `README.md` |
| 新坑 / 修坑 | `PROBLEMS.md` |
| 架构或交接事实变化 | 本文 `HANDOFF.md` |
| 学习路径 | `LEARNING.md` |

发布版本时：`CHANGELOG` 正式节 → README 路线图勾选 → `git tag -a vX.Y.Z`。

---

## 10. 给新 Agent 的开工提示词（可复制）

把下面整段作为新对话的第一轮上下文即可：

```text
你在接手 GitHub 仓库 guorunquan/video-editing-agent（本地路径以用户为准）。
这是学习向的「自然语言视频剪辑 Agent」：Gemini Tool Calling + tools.py/FFmpeg + FastAPI Web。
请先阅读：HANDOFF.md、CHANGELOG.md、PROBLEMS.md、USAGE.md，再改代码。
硬约定：剪辑逻辑只放 tools.py；写盘需 confirmed；Web 只做壳；静态资源改完 bump ?v=；
文件名用 safe_output_stem，不要用裸 Path.stem；不要做公网多租户 unless 用户明确要求。
当前版本目标已完成。v1.5 已开始加入证据化视频分析；后续继续完善本地转写、文本驱动剪辑、自动字幕、竖屏导出。每次改动同步更新 CHANGELOG / USAGE / PROBLEMS。
```

---

## 11. 安全

- 不提交 `.env`、API Key、用户私有视频  
- `delete_output` / `rename_output` / media 路径必须限制在允许目录  
- 禁止 `shell=True` 执行模型生成的任意命令字符串  

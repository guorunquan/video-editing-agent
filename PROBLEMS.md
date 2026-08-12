# 问题与排障记录

记录本项目从 CLI 迷你 Agent 做到 Web v2.0 过程中**真实踩过的坑**、原因与解决办法。
给使用者排障，也给后续接手的 Agent / 开发者避雷。

使用者快速用法见 [USAGE.md](./USAGE.md)；版本能力见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 使用前先分清两件事

| 现象 | 多半是 |
|------|--------|
| 终端停在 `... requesting Gemini`，没有 `[tool]` | **连不上 Google**（VPN / 代理） |
| 有 `[tool]` 但结果不对 | **工具参数 / 提示词 / 业务逻辑** |
| 网页按钮没反应、列表空白 | **浏览器缓存了旧 HTML/JS** → Ctrl+F5 |
| `No module named 'fastapi'` | **没用项目 `.venv`** |

---

## 1. 端口被占用（WinError 10048）

**现象**

```text
error while attempting to bind on address ('127.0.0.1', 7860)
[WinError 10048] 通常每个套接字地址只允许使用一次
```

**原因**  
已有一个 `python web_app.py`（或其它程序）占着 7860。

**解决**

1. 关掉旧进程，或在 PowerShell 查杀占用端口的进程  
2. 或换端口：`$env:WEB_PORT=7861; python web_app.py`

---

## 2. `No module named 'fastapi'`

**现象**  
`(base)` 下直接 `python web_app.py` 报缺少 fastapi。

**原因**  
依赖装在项目 `.venv` 里，当前却是 Anaconda `base`。

**解决**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python web_app.py
```

提示符应出现 `(.venv)`。

---

## 3. 开了 VPN，网页仍超时 / ConnectTimeout 10060

**现象**

- 页面：「超过 N 秒仍无响应」或「重试上一条」  
- 终端：多次 `... requesting Gemini`，没有 `[tool]`  
- `data/chat_sessions.json`（或旧 `chat_log`）里可见：  
  `ConnectTimeout: [WinError 10060] ...`

**原因**  
**浏览器走了代理 ≠ Python 走了代理。**  
许多 VPN 只代理浏览器；本机脚本仍直连 Google，于是连接超时。  
另外：前端若过早 abort，用户可能只看到「超时请重试」，看不到服务端真实的 `ConnectTimeout`。

**解决**

1. VPN 开 **系统代理 / TUN 模式**  
2. 或在 `.env` 配置（端口改成你的 Clash/V2Ray）：

```env
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
```

3. **重启** `web_app.py`；启动日志若出现 `(proxy: ...)` 说明代理已生效  
4. 前端等待已放宽；服务端失败时会给出更明确的中文提示

---

## 4. Windows 拖视频进度条刷 `ConnectionResetError` 10054

**现象**

```text
Exception in callback _ProactorBasePipeTransport._call_connection_lost
ConnectionResetError: [WinError 10054]
```

同时请求仍是 `206 Partial Content`（正常 Range 播放）。

**原因**  
浏览器拖进度条会中断 Range 请求；Windows 默认 asyncio Proactor 容易在 shutdown 时打噪音日志。

**解决**  
一般**可忽略**，不影响剪辑。  
`web_app.py` 已尝试设置 `WindowsSelectorEventLoopPolicy` 减轻噪音。

---

## 5. 上传后仍播放旧成片

**现象**  
刚上传新视频，播放器却还在播以前的 `concat_...` / `trim_...`。

**原因**  
早期 `play_path` 逻辑优先「最新 output」，上传的 `uploads/` 工作视频更「新」却被盖住。

**解决**  
按 mtime 比较 working 与 latest_output；上传后前端强制切到新片源 URL。  
若仍异常：点「刷新预览」或 Ctrl+F5。

---

## 6. 有【待确认】文案，但没有「确认执行」按钮

**现象**  
助手说了要确认，聊天区却没有绿色确认卡片。

**原因**  
工具结果里有 `【待确认】`，但 Gemini **口语改写**后最终回复可能不含这四个字；前端若只匹配最终字符串会漏检。  
也可能是旧前端缓存。

**解决**

- 后端用 `VideoAgent.last_needs_confirm`（看工具结果是否含待确认）  
- 前端再补「请确认 / 确认后」等关键词  
- Ctrl+F5；静态资源带 `?v=` 防缓存

---

## 7. 成片列表空白 / 「对话记录」点了没反应

**现象**  
剪辑已成功、播放器有画面，但列表仍「暂无导出成片」；或点对话记录无弹窗。

**原因**  
多为 **浏览器 304 缓存了旧 `index.html` / `app.js`**，新 DOM 节点（`#output-list`、`#btn-history`）不存在，脚本中途报错。

**解决**

1. Ctrl+F5 强刷  
2. 确认 URL 带新版本参数（如 `app.js?v=0.5.2`）  
3. 点一次「刷新预览」  
4. 重启 `web_app.py`

后端自检：`output/` 有文件时 `/api/state` 的 `outputs` 不应为空。

---

## 8. 改名「1.5倍速视频」变成 `1.mp4`

**现象**  
明明输入带小数点的名字，结果只剩 `1.mp4`。

**原因**  
`pathlib.Path("1.5倍速视频").stem == "1"`，`.5倍速视频` 被当成「扩展名」。

**解决**  
使用 `safe_output_stem()`：只剥末尾真实视频后缀（`.mp4` 等），**保留名字中间的点**。  
对话工具 `rename_output` 与网页「改名」共用此逻辑。

---

## 9. 对话里说「命名为拼接」不生效

**现象**  
拼接成功，但仍是 `concat_2_时间戳.mp4`，没有按要求改名。

**原因**  
早期只有网页改名 API，**Agent 没有 `rename_output` 工具**，模型无法调用。

**解决**  
已增加 `rename_output`；系统提示说明：拼接并命名时，确认后先 `concat` 再 `rename_output`。  
重启服务后再用完整说法试一次。

---

## 10. favicon 404

**现象**  
日志里 `GET /favicon.ico 404`。

**原因**  
未提供站点图标。

**解决**  
`web_app.py` 已提供简易 SVG favicon，避免刷屏。

---

## 11. 免费额度 429 / 模型繁忙 503

**现象**  
回复里出现额度用尽或 UNAVAILABLE。

**解决**  
改 `.env`：

```env
GEMINI_MODEL=gemini-flash-lite-latest
```

保存后重启；503 可等 1～2 分钟再试。

---

## 12. 视频分析与隐私

输入「这个视频怎么剪」时，视频会通过 Gemini 做画面和音频分析；这不是纯本地处理。分析结果会缓存在 `data/video_analysis/`，该目录已被 git 忽略。

如需本地带时间戳转录：

```powershell
pip install faster-whisper
```

然后在 `.env` 设置 `LOCAL_TRANSCRIBE=1`。本地转录失败或未安装时，Gemini 仍会尝试同时理解视频的画面和音频。

## 14. 自动字幕繁体、修改字幕变成叠加文字、分屏字幕只替换半句

**现象**

- Whisper 生成的中文字幕可能是繁体字。
- 用户要求修改已有字幕时，模型误调用 `add_text_overlay`，导致新文字叠加在旧字幕上。
- 一句字幕被拆成多个 SRT 片段时，只替换了第一段，例如把“怎么做回甲乙”改掉，却留下“丙丁”。
- 批量修改时 Agent 可能因工具轮次过少提前停止。

**原因**

- 原流程直接把 Whisper 文本写入 SRT，没有做简繁转换。
- 原工具只有新增文字能力，缺少“读取 SRT、替换文本、重新烧录”的真实执行工具。
- 字幕替换按单个 SRT 块的子字符串匹配，没有考虑一句话跨多个时间片段。
- Agent 工具编排上限为 6 轮，复杂请求容易触顶。

**解决**

- 增加 OpenCC `t2s` 转换，自动字幕和人工修改后的字幕统一输出简体中文。
- 增加 `edit_subtitles`：读取已有 SRT，按原文或批量替换列表修改，然后从无字幕原视频重新烧录；只有生成真实输出文件后才返回成功。
- 对相邻字幕片段做整句归并匹配。匹配成功后把目标文本写入第一段、延长时间范围并删除后续片段，避免半句替换和文字重叠。
- 将工具轮次提高到 12 轮，并在 Agent 规则中明确：修改已有字幕不得调用 `add_text_overlay`。

**使用建议**

重启 Web 服务后，新建聊天会话，再说“把 A 改成 B；把 C 改成 D”。系统会先给出批量修改计划，确认后才重新导出。

---

## 15. 截帧预览部分图片不显示

**现象**

截帧预览区域只能看到前几张图片，后面的图片没有显示。

**原因**

前端使用 `previews.slice(0, 6)`，主动限制最多渲染 6 张；同时预览条是单行横向布局，容易让用户误以为后面的图片被隐藏。

**解决**

移除前端 6 张限制，改为渲染全部截帧；CSS 改成多行自动换行，并在高度超出时提供滚动区域。静态资源版本号同步更新，重启服务或刷新页面即可生效。

---

## 13. 中文字幕方框 / 乱码

**现象**  
叠字后中文显示为方框。

**原因**  
环境找不到中文字体。

**解决**  
`.env` 指定字体，例如：

```env
VIDEO_FONT=C:\Windows\Fonts\msyh.ttc
```

---

## 16. 视频分析报 `too many values to unpack` 或 `Invalid format specifier`

**现象**

分析视频连续失败，终端或对话中出现：

```text
ValueError: too many values to unpack (expected 2)
ValueError: Invalid format specifier ... for object of type 'str'
```

**原因**

- Gemini 文件状态兼容逻辑错误地假定 SDK 对象始终是固定二元结构。
- JSON 示例直接写进 Python f-string，花括号未转义，被当成格式化说明符。

**解决**

- 文件状态统一通过兼容函数读取字符串/枚举值，不解包 SDK 对象。
- Prompt 中的 JSON 花括号写成 `{{` / `}}`，并在 `_extract_json()` 与 `validate_analysis()` 中做二次校验。

## 17. 选了方案但左侧仍播放原视频

**现象**

对话已经显示剪辑时间段，左侧仍是原视频时长；有时回复「方案一」只得到“请确认”，没有真实预览。

**原因**

- 旧流程只保存文字计划，没有创建和渲染结构化草案。
- 前端播放器优先级没有使用当前草案预览。
- 裸数字/「方案一」没有经过确定性意图路由，模型回复不稳定。
- 后端旧进程或浏览器旧资源仍在运行。

**解决**

- 方案选择创建 `EditDraft` 并调用 `render_draft(preview=True)`。
- `/api/state` 暴露 `active_draft.preview.url`，前端优先切换到该 URL。
- 「方案 N」「看看方案 N」在 `agent.py` 中确定性处理。
- 更新后必须重启 `web_app.py` 并按 Ctrl+F5。

## 18. 预览画质模糊

**现象**

剪辑预览能播放，但游戏画面文字、技能和小地图明显看不清。

**原因**

旧预览为了速度缩放到较低分辨率并使用较高 CRF。

**解决**

v2.0 预览不再缩放，保持源视频尺寸，使用 H.264 CRF 20；只用 `veryfast` preset 区分预览与最终导出。代价是预览文件更大、渲染更慢，这是有意取舍。

## 19. 要求配乐却被静音，或 Agent 说没有配乐工具

**现象**

用户说「配上高燃音乐」后，Agent 先生成静音视频，随后又说只能去剪映/PR 加音乐。

**原因**

配乐意图完全交给通用模型选择，而旧 Tool Schema 只有 `mute_audio`，模型会错误降级或把静音当成前置步骤。

**解决**

- 「配上高燃音乐」「给整个原视频配乐」由代码直接创建全片 `EditDraft`。
- `editor_v2.py` 首次使用时生成内置 150 BPM 高燃循环，也可读取 `uploads/music/` 中的用户音乐。
- FFmpeg 直接降低原声后与 BGM 混音，不要求先静音。
- 方案卡应显示音乐名和音量；若仍出现旧回复，重启服务并 Ctrl+F5。

## 20. 方案只是完整保留原片

**现象**

方案写“保留 0～18 秒完整操作”，没有剪切、配乐或效果，实际等同不剪辑。

**原因**

模型为了“信息完整”可能输出全时长片段，而旧校验只检查时间合法性，没有检查是否产生实际变化。

**解决**

`validate_analysis()` 会过滤仅覆盖全片且没有效果/包装差异的候选。有效方案数量允许为 2～3 个，不为了凑数展示空方案。

## 21. 预览不满意后无法返回原视频

**现象**

预览方案后，播放器一直停留在临时预览，用户无法回到原工作视频继续调整。

**解决**

v2.0 增加「返回原视频」意图与界面动作：清除当前草案显示，播放器恢复正式工作视频。临时预览文件可以保留用于缓存，但不会进入成片列表，也不会改写原片。

---

## 排障清单（建议顺序）

1. 是否在 `.venv` 里运行？  
2. `.env` 是否有有效 `GEMINI_API_KEY`？  
3. VPN / `HTTPS_PROXY` 是否让 **Python** 出得去？  
4. 浏览器是否 Ctrl+F5？  
5. 终端是卡在 Gemini，还是已经出现 `[tool]`？  
6. 看 `data/chat_sessions.json` 里助手是否已写明 `ConnectTimeout` / `429`  
7. 仍不行：重启 `web_app.py`，再试最短指令「这个视频多长？」

---

## 给后续维护者的备注

- 修 Web 体验时，**静态资源务必改 `?v=`**，否则用户会以为「没修好」。  
- 凡涉及「模型最终回复文案」的 UI 状态（如待确认），尽量以 **工具结果** 为准，不要只信自然语言。  
- 文件名处理不要用裸 `Path.stem`，除非已确认没有「1.5」这类小数点名字。  
- 写磁盘操作继续走 `confirmed=false/true`，不要让模型直接改盘。
- v2.0 方案预览是受控临时写盘；最终成片仍必须在预览成功后明确确认。

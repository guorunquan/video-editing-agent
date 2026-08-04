# 问题与排障记录

记录本项目从 CLI 迷你 Agent 做到 Web v1.5 过程中**真实踩过的坑**、原因与解决办法。
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

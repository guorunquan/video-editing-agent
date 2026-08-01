# 学习指南：从这个项目学会 Agent 开发

面向：准大四、Python 基础一般、想投 **Agent 开发实习** 的同学。  
仓库：[video-editing-agent](https://github.com/guorunquan/video-editing-agent)

**先会用再精读：** 产品怎么开、怎么说指令 → [USAGE.md](./USAGE.md)；仓库总览与安装 → [README.md](./README.md)。

目标不是背完整 FFmpeg，而是能讲清、能改、能扩展下面这条链路：

```text
用户说话 → 大模型选工具 → 你的 Python 执行 → 结果回给模型 → 回答用户
```

---

## 一、项目技术栈全景

| 层级 | 用了什么 | 在本项目里干什么 |
|------|----------|------------------|
| 语言 | Python 3 | 全部业务逻辑 |
| LLM | Google Gemini | 「脑子」：理解中文、决定调哪个工具 |
| SDK | `google-genai` | 调用 Gemini、声明 tools、收发多轮对话 |
| Web（v0.4） | FastAPI + `static/` | 上传 / 对话 / 页内预览，复用同一套 Agent |
| 配置 | `.env` + `python-dotenv` | 存放 API Key / 模型名（不写进代码） |
| 视频 | FFmpeg（或 `imageio-ffmpeg` 自带） | 「手」：真正剪视频、读时长 |
| 进程 | `subprocess` | 在 Python 里启动 FFmpeg 命令 |
| 工程 | Git / GitHub | 版本管理与作品展示 |

一句话：

> **Gemini = 调度员；`tools.py` = 工人；FFmpeg = 机器。**

---

## 二、文件该怎么读（推荐顺序）

按这个顺序读，每次只搞懂一个问题：

| 顺序 | 文件 | 你要搞懂的问题 |
|------|------|----------------|
| 1 | `main.py` | 程序从哪开始？用户输入怎么进 Agent？ |
| 2 | `tools.py` 前半 | `probe_video` / `trim_keep` / `cut_out` / `add_text_overlay` 自己怎么干活？ |
| 3 | `tools.py` 后半 | `TOOL_DECLARATIONS` 和 `run_tool` 是什么关系？ |
| 4 | `agent.py` 的 `chat()` | 模型如何「想调工具 → 你执行 → 再问模型」？ |
| 5 | `ffmpeg_bin.py` | 为什么找不到系统 FFmpeg 也能跑？ |
| 6 | `web_app.py` + `static/` | Web 如何复用同一个 Agent？（上传 → chat → 预览 URL） |
| 7 | `.env.example` | 哪些配置影响线上行为？ |

---

## 三、Agent 开发相关知识（本项目实际用到的）

### 1. 什么是 Agent（面试版）

- **Chatbot**：只回文字  
- **Agent**：可以调用外部能力（查文件、剪视频、调 API）再基于结果回答  

本项目 Agent 的能力边界由你注册的 **tools** 决定。

### 2. Tool Calling / Function Calling（核心中的核心）

流程：

1. 你把工具说明书（名字、描述、参数 JSON Schema）交给模型  
2. 用户说「去掉前 5 秒」  
3. 模型不直接剪视频，而是返回：`trim_keep(start=5, end=83.7, confirmed=false)`  
4. **你的代码**执行这个函数  
5. 把结果再喂回模型  
6. 模型组织中文答复  

对应代码：

- 说明书：`tools.py` → `TOOL_DECLARATIONS`  
- 执行器：`tools.py` → `run_tool()`  
- 循环：`agent.py` → `VideoAgent.chat()`

### 3. System Prompt（系统提示词）

`agent.py` 里的 `SYSTEM_PROMPT` 告诉模型：

- 你是谁（视频切片助手）  
- 工具该怎么组合（先 probe 再 trim）  
- 安全规则（先 confirmed=false）  

改提示词会显著改变 Agent 行为——这是 Agent 工程的基本功。

### 4. 多轮对话 / 历史（History）

`self.history` 保存：

- 用户消息  
- 模型回复（可能含 function_call）  
- 工具结果（function_response）  

没有历史，模型就不知道「刚才已经 probe 过时长了」。

### 5. 人机确认（Human-in-the-loop）

写磁盘前先预览：

- `confirmed=False` → 只返回计划  
- 用户说确认 → `confirmed=True` → 真执行  

工业项目里对应：审批流、草稿会话（如 OpenChatCut 的 edit session）。

### 6. 错误与配额（工程现实）

你已经遇到过：

| 现象 | 含义 |
|------|------|
| 连接被拒绝 / 卡住 | 网络到不了 Google（要 VPN/代理） |
| 429 | 免费额度用尽，换模型或等刷新 |
| 503 | 服务端繁忙，稍后重试 |

Agent 开发不只写 happy path，还要会提示用户怎么恢复。

### 7. 与 OpenChatCut 的知识映射

| 本项目 | OpenChatCut（工业版） |
|--------|----------------------|
| `trim_keep` | 时间线 `split` / `srcInFrame` 等命令 |
| `TOOL_DECLARATIONS` | Agent / MCP 工具集 |
| `confirmed` | 草稿 → 审阅 → 应用 |
| `output/*.mp4` | 工程状态 + 导出 |
| 命令行 | 完整 GUI + Remotion 预览 |

先掌握左边，再学右边会轻松很多。

---

## 四、你需要学会的 Python（按优先级）

### P0：必须会（否则读不懂本项目）

1. **基础语法**  
   变量、`if/for/while`、函数 `def`、`return`、字符串 f-string  

2. **类型标注（能看懂即可）**  
   ```python
   def trim_keep(start_sec: float, confirmed: bool = False) -> str:
   ```  
   表示参数/返回值类型，方便读代码和 IDE 提示。  

3. **字典 `dict` 与 JSON**  
   - `info = {"path": ..., "duration_sec": ...}`  
   - `json.dumps` / `json.loads`  
   Agent 传参、存计划几乎全是 JSON。  

4. **列表 `list` 与推导式**  
   ```python
   decls = [types.FunctionDeclaration(...) for item in TOOL_DECLARATIONS]
   ```  

5. **`Path`（路径）** — `pathlib.Path`  
   拼接路径、判断存在、列目录、删文件。本项目大量使用。  

6. **异常处理**  
   ```python
   try:
       ...
   except Exception as e:
       return f"失败: {e}"
   ```  
   工具函数里通常「返回错误字符串」而不是直接把程序打崩（方便模型继续对话）。  

7. **模块与导入**  
   `from tools import run_tool`、`if __name__ == "__main__"`  

8. **虚拟环境与 pip**  
   `python -m venv .venv`、`pip install -r requirements.txt`  

### P1：本项目重度使用（第二周吃透）

9. **`os.getenv` + dotenv**  
   从环境变量读密钥，避免硬编码。  

10. **`subprocess.run`**  
    调用外部程序（FFmpeg）。注意参数用列表，不要把用户输入直接拼进 shell。  

11. **正则 `re.search`**  
    从 FFmpeg 输出文本里抠出 `Duration: 00:01:23.70`。  

12. **类 `class`**  
    `VideoAgent`：把 client、history、tools 封装在一起。  
    要会：`__init__`、实例属性 `self.xxx`、实例方法。  

13. **类型联合与 Optional**  
    `path: str | None = None` 表示「可以不传」。  

14. **装饰器入门（能认即可）**  
    `@lru_cache`：缓存 `get_ffmpeg()` 结果，避免重复查找。  

### P2：扩展功能时再学

15. argparse / Typer（做更好的命令行）  
16. FastAPI（做成网页/API Agent）  
17. asyncio（并发、流式输出）  
18. 单元测试 `pytest`（给 `trim_keep` 写测试）  
19. 日志 `logging`（代替到处 `print`）  

---

## 五、对照源码的「精读作业」

### 作业 A（1 天）：跑通并口述

打开终端跑一遍「去掉前 5 秒 → 确认」，然后用自己的话讲：

1. 哪一次请求后出现了 `[tool] probe_video` 或 `trim_keep`？  
2. 为什么第一次 `confirmed` 是 false？  
3. 文件最终出现在哪个目录？  

### 作业 B（2 天）：改提示词

只改 `SYSTEM_PROMPT`：要求模型回答时必须带上「预计导出秒数」。  
观察行为变化——体会提示词工程。  

### 作业 C（3 天）：加一个小工具

例如给成片加淡入淡出、或「记住上一份文字计划方便改字号」。  

（v0.3 已内置 `cut_out` / `concat_videos` / `export_preview_frame` / `mute_audio` / `change_speed`，可对照源码看「加工具」怎么落地。）

步骤固定：

1. 在 `tools.py` 写 Python 函数  
2. 写入 `TOOL_DECLARATIONS`  
3. 在 `run_tool` 里分发  
4. 必要时改 `SYSTEM_PROMPT` 教模型何时调用  

**扩展 Agent = 加工具**，这是实习里最常见的活。  

### 作业 D（选做）：默写 Agent 循环伪代码

不看代码，写出：

```text
history.append(用户)
loop:
  response = 调用模型(history, tools)
  history.append(response)
  if 没有 function_call:
    return 文字
  执行每个 tool
  history.append(tool结果)
```

能默写，面试基本过关。  

---

## 六、建议学习日程（两周）

| 天数 | 学什么 | 产出 |
|------|--------|------|
| D1 | Python 函数/字典/Path + 读 `main.py` | 能解释程序入口 |
| D2 | 读懂 `probe_video` + 自己在 Python 里 `print(probe_video())` | 不经过模型也能测工具 |
| D3 | 读懂 `trim_keep` + FFmpeg 命令在干什么 | 知道 `-ss` `-t` `-c copy` |
| D4–D5 | 精读 `VideoAgent.chat` | 画出工具调用时序图 |
| D6 | System Prompt / confirmed 机制 | 能讲 Human-in-the-loop |
| D7 | 429/503/代理 | 能讲线上排障 |
| D8–D10 | 自己加 1 个新工具并提交 GitHub | 简历可写「独立扩展」 |
| D11–D14 | 看 OpenChatCut 的 tools 列表，对比差异 | 为面试准备「进阶认知」 |

---

## 七、面试可以怎么说（基于本项目）

> 我做了一个自然语言视频剪辑 Agent（CLI + 本地 Web）。使用 Gemini Function Calling：模型根据工具描述选择 `probe_video` / `trim_keep` 等，实际剪辑由 Python 调用 FFmpeg 完成。对写操作实现了确认机制，避免模型直接改文件。v0.4 用 FastAPI 做了上传与页内预览，工具层仍复用同一套。项目开源在 GitHub。

准备好被追问：

1. 为什么不让模型直接生成 FFmpeg 命令字符串执行？（安全：注入/乱删文件）  
2. `confirmed` 解决什么问题？  
3. 如何新增一个工具？  

---

## 八、推荐课外资料（少而精）

1. Google AI：Gemini Function Calling 官方文档（对照 `google-genai`）  
2. FFmpeg 官方文档：`-ss`、`-t`、`-c copy` 三节即可  
3. Python 官方教程：`pathlib`、`subprocess` 两章  
4. （进阶）OpenChatCut README：Agent-native 编辑思路  

---

## 九、你现在的掌握标准（Checklist）

- [ ] 能不看文档说出 Agent 与 Chatbot 的区别  
- [ ] 能指着 `chat()` 讲清一轮工具调用  
- [ ] 能独立改 `SYSTEM_PROMPT` 并验证效果  
- [ ] 能新增一个 tool 并跑通  
- [ ] 能解释 429/503 与 VPN 问题  
- [ ] 能用 30 秒介绍 GitHub 仓库  

全部勾完，你就具备投 Agent 实习的**最小完整项目经验**；之后再学框架（LangChain / 自研 runtime）会快很多。

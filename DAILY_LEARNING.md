# Agent 开发每日学习

> 目标：每天掌握一个能从本项目源码中验证、能用于实习面试的 Agent 开发知识点。
> 详细原理和完整项目分析见 [`LEARNING.md`](./LEARNING.md)。

---

## 2026-08-08｜Day 1：Agent 最小执行闭环

### 今日目标

今天只学懂一件事：**用户的一句话，怎样变成一次安全、可验证的工具执行。**

### 1. Agent 不只是大模型

普通 Chatbot 主要生成文字；Agent 还会根据目标调用外部工具，观察执行结果，再决定下一步。

本项目的最小闭环是：

```text
用户中文指令
→ Gemini 选择工具并填写参数
→ Python 执行白名单工具
→ FFmpeg 处理视频
→ 工具结果返回 Gemini
→ Gemini 向用户解释结果
```

一句话记忆：

> **Gemini 负责决策，Python 负责控制，FFmpeg 负责执行。**

### 2. 对应源码

| 位置 | 作用 |
|---|---|
| [`agent.py`](./agent.py) 的 `VideoAgent.chat()` | 保存对话、请求模型、读取 Function Call、回传工具结果 |
| [`tools.py`](./tools.py) 的 `TOOL_DECLARATIONS` | 告诉模型有哪些工具、参数及使用语义 |
| [`tools.py`](./tools.py) 的 `run_tool()` | 只允许执行已注册的白名单函数 |
| [`tools.py`](./tools.py) 的具体工具函数 | 校验参数并调用 FFmpeg |
| [`web_app.py`](./web_app.py) 的 `api_chat()` | 把网页请求接入同一套 Agent |

以“只保留 5～20 秒”为例，模型不会直接剪视频，而是生成类似调用：

```json
{
  "name": "trim_keep",
  "args": {
    "start_sec": 5,
    "end_sec": 20,
    "confirmed": false
  }
}
```

Python 收到后，才通过 `run_tool()` 调用真实的 `trim_keep()`。

### 3. 今天最重要的工程设计：人工确认

剪视频、改字幕、删除文件都有副作用，因此项目采用两阶段执行：

```text
confirmed=false → 只生成计划，不改文件
用户确认
confirmed=true  → 执行 FFmpeg 或文件操作
```

这叫 **Human-in-the-loop（人在回路）**。它可以迁移到邮件发送、数据库修改、代码部署等 Agent 场景。

面试表达：

> 我把有副作用的工具设计成 plan/apply 两阶段：首次调用返回结构化计划，用户确认后才执行，从而把大模型的建议权与最终执行权分开。

### 4. 为什么不能执行模型生成的任意命令

如果让模型直接生成一整段 shell/FFmpeg 命令并执行，可能出现：

- 命令注入；
- 访问或删除非目标文件；
- 参数错误导致覆盖原片；
- 模型误判后直接产生副作用。

本项目的处理方式：

- 模型只能调用注册好的工具；
- 后端重新校验时间、路径和文件类型；
- 文件操作限制在允许目录；
- `subprocess` 使用参数列表，不执行任意 shell 字符串；
- 写操作必须确认。

通用原则：

> **Prompt 负责软规则，代码负责硬约束；永远不要把模型输出当成可信输入。**

### 5. v1.8 要准确描述

v1.8 增加了网页时间定位、前后跳转、入点/出点标记和当前帧截取。

但入点/出点目前只保存在浏览器变量中，还没有连接 `trim_keep` 和确认流程。因此可以说“实现时间轴预览与范围标记”，不能说“已经实现完整图形时间线剪辑”。

这种主动说明能力边界的习惯，对简历和面试很重要。

### 6. 今日 20 分钟练习

先直接调用工具，不经过大模型：

```python
from tools import trim_keep

result = trim_keep(
    0,
    3,
    path="samples/demo.mp4",
    confirmed=False,
)
print(result)
```

观察两个结果：

1. 返回内容中存在待确认计划；
2. `output/` 没有因为这次调用新增视频。

完成后，用自己的话回答：

- 模型返回 Function Call，是否等于工具已经执行？
- `TOOL_DECLARATIONS` 与 `run_tool()` 分别解决什么问题？
- 为什么 `confirmed` 不能只写在 System Prompt 里？

### 今日面试自测

- [ ] 能在 30 秒内解释 Agent 与 Chatbot 的区别。
- [ ] 能口述“模型选工具 → Python 执行 → 结果回传”的链路。
- [ ] 能解释 Tool Schema、工具实现和分发器的区别。
- [ ] 能解释 Human-in-the-loop 解决了什么风险。
- [ ] 能准确说明 v1.8 时间轴尚未完成的部分。

### 今日简历素材

> 基于 Gemini Function Calling 自研视频剪辑 Agent 工具调用循环，通过 Tool Schema 与白名单分发器连接 FFmpeg 工具，并采用 plan/apply 两阶段人工确认控制文件写入副作用。

---

## 2026-08-12｜Day 2：结构化草案与预览门禁

### 今日目标

理解为什么“AI 写一段剪辑建议”不等于“AI 剪辑产品已经可用”。

### 核心链路

```text
分析结果 → 校验方案 → EditDraft → 真实视频预览
→ 调整或返回原视频 → 确认 → 正式导出
```

重点阅读：

1. `video_analysis.py` 的 `validate_analysis()`：如何限制时间、补默认值并过滤空方案。
2. `agent.py` 的方案/配乐意图路由：哪些动作不该完全依赖 LLM。
3. `editor_v2.py` 的 `create_draft()`、`render_draft()`、`confirm_draft()`：状态如何保护正式视频。
4. `tests/test_v2.py`：每个回归测试对应哪次真实失败。

### 今日面试自测

- [ ] 能解释预览文件和正式成片的状态边界。
- [ ] 能解释为什么「方案一」「配上高燃音乐」使用确定性路由。
- [ ] 能说明加 BGM 为什么不应先静音，而应做原声 ducking + 混音。
- [ ] 能说明源分辨率预览与渲染速度之间的取舍。
- [ ] 能准确列出延期的多轨时间线、自动跟踪、光流慢动作和在线音乐能力。

### 今日简历素材

> 将多模态剪辑建议落为结构化 EditDraft，设计“真实预览成功后才能确认导出”的审核门禁，并以确定性意图路由、本地音乐自动匹配和 FFmpeg 受控渲染提升核心流程可靠性。

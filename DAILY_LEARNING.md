# 灵剪 EditMate v2.0｜每日学习入口

完整、从零解释的项目学习指南在 [`LEARNING.md`](./LEARNING.md)。不要试图一天看完；每天只完成一个小主题和一个小练习。

## 每天的固定学习方法

```text
读一个概念（10 分钟）
→ 在项目中找到对应代码（10 分钟）
→ 运行或修改一个很小的例子（20 分钟）
→ 用自己的话解释它（5 分钟）
```

每天来对话时，可以直接说：

- “今天学 Python 函数”；
- “今天讲 FFmpeg”；
- “我看不懂 `validate_analysis()`”；
- “带我写第一个测试”；
- “今天继续学习 Agent”。

我会只教当天这一小步：先解释概念，再对照项目代码，最后给一个能完成的练习；不会一次性丢给你全部知识。

---

## 总路线

| 阶段 | 先学什么 | 项目对应位置 | 完成标志 |
|---|---|---|---|
| 1. Python 与环境 | 函数、字典、类、异常、文件、venv、Git、终端 | `main.py`、`tools.py`、`tests/` | 能运行项目和读懂小函数 |
| 2. 后端与 API | HTTP、JSON、FastAPI、Pydantic、`.env` | `web_app.py` | 能写并测试一个小 API |
| 3. LLM 与 Tool Calling | Prompt、history、Schema、工具结果、安全 | `agent.py`、`tools.py` | 能新增一个受控工具 |
| 4. 可靠 Agent | 结构化输出、校验、状态机、预览、测试/Eval | `video_analysis.py`、`editor_v2.py` | 能完成一项小迭代并补测试 |
| 5. 进阶 | RAG、LangGraph、MCP、Linux 部署、模型部署 | 由后续真实需求决定 | 能解释它们解决的具体问题 |

> 不要先学 RAG、LangChain 或模型部署来“凑技术栈”。先通过本项目掌握 Tool Calling、状态、验证和测试；这些才是 Agent 工程的地基。

---

## 第一次从哪里开始

如果你还不熟 Python，请从 [`LEARNING.md` 第 6 节](./LEARNING.md#6-关键概念词典遇到术语先查这里) 和第 16 节的“阶段 A”开始。

如果你已能读懂 Python 基础，但觉得只看概念没有收获，请从 [`LEARNING.md` 第 15 节](./LEARNING.md#15-测试与-agent-eval怎样证明不是手动试了一次) 开始：学习怎样把“Agent 做得对不对”写成自动化测试。

如果你想理解 v2.0 最有价值的设计，请读 [`LEARNING.md` 第 10 节](./LEARNING.md#10-editdraftv20-为什么要有草稿)：结构化草稿、预览和确认导出。

---

## 今天的第一步（30 分钟）

目标：不要背 Agent 定义，只弄懂“模型建议”和“真实执行”是两件事。

1. 阅读 [`LEARNING.md` 第 2、3、8 节](./LEARNING.md)。
2. 打开 `agent.py`，找到 `VideoAgent.chat()`；打开 `tools.py`，找到 `run_tool()`。
3. 用自己的话回答：

   - Gemini 返回一个 Function Call，是否已经剪完视频？
   - Python 在哪个位置决定工具能不能真的运行？
   - 为什么 AI 方案在 v2.0 中要先生成预览？

不需要把答案写得专业。下次直接把你的理解发给我，我会根据你的回答继续，而不是机械地跳到下一课。

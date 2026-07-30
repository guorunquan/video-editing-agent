"""
视频切片 Agent：Gemini Tool Calling + FFmpeg。
"""

from __future__ import annotations

import json
import os
from typing import Any

from google import genai
from google.genai import types

from tools import TOOL_DECLARATIONS, run_tool

SYSTEM_PROMPT = """
你是一个亲切、务实的「迷你视频剪辑」助手，只会通过工具处理本地视频。

语气：
- 用简洁中文，像靠谱的同学帮忙，不要官腔。
- 成功后主动提 1～2 个自然下一步（打开看看 / 加标题 / 换字号），不要一次列一大堆。
- 待确认时：清楚说明会改什么，并请用户回复「确认」。

规则：
1. 用户给出新视频路径时：先 probe_video(path=该路径)，再按要求操作。
2. 「去掉前 N 秒」= trim_keep(start_sec=N, end_sec=总时长, path=源视频)。
3. 「只保留 A 到 B 秒」= trim_keep(start_sec=A, end_sec=B, path=源视频)。
4. 文字贴纸 / 标题 / 字幕：
   - 「加标题 xxx」→ add_text_overlay(text=xxx, style=title)
   - 「底部字幕 / 加一句 xxx」→ style=subtitle
   - 「右上角贴纸 / 角标」→ style=sticker
   - 用户说字号、颜色、位置、出现时段时，填入对应参数。
   - 未指定源文件时：优先对最新成片加工（path 可省略）。
5. 「打开 / 播放 / 看看效果」→ open_output（可省略文件名=最新）。
6. 看已导出列表 → list_outputs；删导出成片 → delete_output（只能删 output/）。
7. trim_keep / add_text_overlay / delete_output 必须先 confirmed=false；用户确认后再 confirmed=true。
8. 导出或删除成功后给出完整路径；打开播放成功后简单告知即可。
""".strip()


def _build_tools() -> list[types.Tool]:
    decls = [
        types.FunctionDeclaration(
            name=item["name"],
            description=item["description"],
            parameters=item.get("parameters"),
        )
        for item in TOOL_DECLARATIONS
    ]
    return [types.Tool(function_declarations=decls)]


def _fn_args_to_dict(args: Any) -> dict:
    if args is None:
        return {}
    if isinstance(args, dict):
        return args
    try:
        return dict(args)
    except Exception:  # noqa: BLE001
        return json.loads(json.dumps(args, default=str))


def _make_client(api_key: str) -> genai.Client:
    timeout_ms = int(os.getenv("GEMINI_TIMEOUT_MS") or "45000")
    proxy = (
        (os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip()
        or (os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or "").strip()
        or (os.getenv("ALL_PROXY") or os.getenv("all_proxy") or "").strip()
    )
    client_args: dict[str, Any] = {}
    if proxy:
        client_args["proxy"] = proxy
        print(f"(proxy: {proxy})")

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            client_args=client_args or None,
        ),
    )


class VideoAgent:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = _make_client(api_key)
        self.model = model
        self.tools = _build_tools()
        self.history: list[types.Content] = []

    def chat(self, user_text: str) -> str:
        self.history.append(
            types.Content(role="user", parts=[types.Part(text=user_text)])
        )

        for round_i in range(6):
            print("  ... requesting Gemini")
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=self.history,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=self.tools,
                    ),
                )
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                hint = (
                    "\n请确认 VPN 已开。"
                    if "10061" in msg or "ConnectError" in type(e).__name__
                    else ""
                )
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    hint = (
                        "\n免费额度用尽。请改 .env 的 GEMINI_MODEL，例如：\n"
                        "  GEMINI_MODEL=gemini-flash-lite-latest\n"
                        "或 gemini-2.5-flash-lite，保存后重新运行。"
                    )
                elif "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg:
                    hint = (
                        "\n这是 Google 模型暂时繁忙（503），不是功能缺失。"
                        "请等 1～2 分钟再试，或换模型后重启：\n"
                        "  GEMINI_MODEL=gemini-flash-lite-latest"
                    )
                return f"请求 Gemini 失败。\n{type(e).__name__}: {msg[:500]}{hint}"

            if not response.candidates:
                return "模型没有返回结果。"
            content = response.candidates[0].content
            if content is None:
                return "模型返回为空。"
            self.history.append(content)

            fn_calls = [
                p.function_call
                for p in (content.parts or [])
                if getattr(p, "function_call", None) and p.function_call.name
            ]
            if not fn_calls:
                texts = [p.text for p in (content.parts or []) if getattr(p, "text", None)]
                return "\n".join(texts).strip() or "(无文字回复)"

            result_parts: list[types.Part] = []
            for call in fn_calls:
                name = call.name
                args = _fn_args_to_dict(call.args)
                print(f"  [tool] {name}({args})")
                result = run_tool(name, args)
                # 控制台别刷太长
                preview = result if len(result) < 500 else result[:500] + "..."
                print(f"  [result] {preview}")
                result_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": result},
                    )
                )
            self.history.append(types.Content(role="user", parts=result_parts))
            print(f"  ... tool round {round_i + 1} done")

        return "工具轮次过多，已停止。"


def load_settings() -> tuple[str, str]:
    from dotenv import load_dotenv

    load_dotenv()
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    if not api_key or api_key.startswith("你的"):
        raise SystemExit("请在 .env 填入 GEMINI_API_KEY")
    return api_key, model

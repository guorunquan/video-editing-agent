"""
视频剪辑 Agent：Gemini Tool Calling + FFmpeg。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from google import genai
from google.genai import types

from tools import TOOL_DECLARATIONS, run_tool

SYSTEM_PROMPT = """
你是一个亲切、务实的「迷你视频剪辑」助手，只会通过工具处理本地视频。

语气：
- 用简洁中文，像靠谱的同学帮忙，不要官腔。
- 成功后主动提 1～2 个自然下一步，不要一次列一大堆。
- 待确认时：用人话说明会改什么，并请用户回复「确认」（网页也会出确认按钮）。
- 用户说「取消 / 不要执行 / 先别改」时：不要调用 confirmed=true，简短确认已取消即可。

规则：
1. 用户给出新视频路径时：先 probe_video(path=该路径)，再按要求操作。
   未指定路径时：优先用当前工作视频 / 最新成片（多数工具可省略 path）。
2. 「去掉前 N 秒」= trim_keep(start_sec=N, end_sec=总时长)。
3. 「只保留 A 到 B 秒」= trim_keep(start_sec=A, end_sec=B)。
4. 「删掉中间 / 去掉 A 到 B 秒（不要两端）」= cut_out(start_sec=A, end_sec=B)。
   注意：cut_out 与 trim_keep 相反，不要搞混。
5. 「把这几段拼起来 / 拼接」= concat_videos(clips=...)。
   若同时要求「命名为 xxx / 改名叫拼接」：先完成拼接，再 rename_output(new_name=xxx)。
6. 「静音 / 去掉声音」= mute_audio。
7. 「两倍速 / 慢放 0.5 倍」= change_speed(factor=...)。
8. 「截一帧 / 预览第 N 秒 / 看看字幕位置」= export_preview_frame（无需确认）。
9. 文字贴纸：
   - 「加标题 xxx」→ add_text_overlay(text=xxx, style=title)
   - 「底部字幕」→ style=subtitle；「角标/贴纸」→ style=sticker
   - 未指定源文件时优先最新成片。
10. 「打开 / 播放 / 看看效果」→ open_output（可省略=最新）。
    在网页模式中，open_output 不会弹系统播放器，页面右侧会刷新预览。
11. 列表 → list_outputs；删导出成片 → delete_output；改名 → rename_output（只能动 output/）。
12. 会改文件的操作必须先 confirmed=false；用户确认后再 confirmed=true。
    export_preview_frame / probe_video / open_output / list_outputs 不需要确认。
    用户已确认「拼接并命名」时：concat confirmed=true 成功后，接着 rename_output(..., confirmed=true)。
13. 用户要求「切得更准」时给 trim_keep 加 precise=true。
14. 用户取消待确认计划时，不要执行写操作。
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
        # 最近一次 chat 是否进入「待确认」状态（工具结果含【待确认】）
        self.last_needs_confirm = False
        self.last_confirmation: dict[str, Any] | None = None

    def chat(self, user_text: str) -> str:
        self.last_needs_confirm = False
        self.last_confirmation = None
        self.history.append(
            types.Content(role="user", parts=[types.Part(text=user_text)])
        )

        for round_i in range(6):
            print("  ... requesting Gemini")
            t0 = time.time()
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=self.history,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=self.tools,
                    ),
                )
                print(f"  ... Gemini ok in {time.time() - t0:.1f}s")
            except Exception as e:  # noqa: BLE001
                print(f"  ... Gemini fail in {time.time() - t0:.1f}s: {type(e).__name__}")
                msg = str(e)
                hint = (
                    "\n请确认 VPN 为系统代理/TUN，或在 .env 设置 HTTPS_PROXY。"
                    if (
                        "10060" in msg
                        or "10061" in msg
                        or "ConnectTimeout" in type(e).__name__
                        or "ConnectError" in type(e).__name__
                    )
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
                if "【待确认】" in (result or ""):
                    self.last_needs_confirm = True
                    marker = re.search(r"__VIDEO_AGENT_PENDING__(\{[^\n]*\})", result or "")
                    if marker:
                        try:
                            self.last_confirmation = json.loads(marker.group(1))
                        except json.JSONDecodeError:
                            self.last_confirmation = None
                # 真正执行成功后，不再视为待确认
                if '"status": "ok"' in (result or "") or '"status":"ok"' in (result or ""):
                    self.last_needs_confirm = False
                    self.last_confirmation = None
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

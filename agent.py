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

from tools import TOOL_DECLARATIONS, _resolve_source, render_edit_plan, run_tool
from video_analysis import analyze_video

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
10. 「自动加字幕 / 生成字幕 / 给视频配字幕」→ add_auto_subtitles。
    该工具使用本地 faster-whisper，先 confirmed=false；若未安装要明确提示，不要假装完成。
11. 「去水印」→ remove_watermark。
    默认 position=bottom_right、mode=blur；如果用户没有说明位置，先询问或展示默认右下角计划。
    这是固定区域模糊/遮盖，不要承诺移动水印无痕恢复。
12. 「打开 / 播放 / 看看效果」→ open_output（可省略=最新）。
    在网页模式中，open_output 不会弹系统播放器，页面右侧会刷新预览。
13. 列表 → list_outputs；删导出成片 → delete_output；改名 → rename_output（只能动 output/）。
14. 会改文件的操作必须先 confirmed=false；用户确认后再 confirmed=true。
    export_preview_frame / probe_video / open_output / list_outputs 不需要确认。
    用户已确认「拼接并命名」时：concat confirmed=true 成功后，接着 rename_output(..., confirmed=true)。
15. 用户要求「切得更准」时给 trim_keep 加 precise=true。
16. 用户取消待确认计划时，不要执行写操作。
17. 用户问「怎么剪 / 如何剪 / 给剪辑建议」时，先完成视频分析，再根据带时间点的证据给建议；分析阶段不得自动修改文件。
18. 用户说「采用方案 N」时，使用上一次分析结果中的时间段生成剪辑计划，仍须 confirmed=false 等待确认。
""".strip()


SYSTEM_PROMPT += """

字幕规则补充：
- 自动字幕默认输出简体中文；工具返回 status=ok 且明确给出 output 路径后，才能说已完成。
- 用户要求修改已有字幕内容时，必须调用 edit_subtitles。先 confirmed=false 展示修改计划，用户确认后再 confirmed=true。
- 用户一次要求修改多句字幕时，必须把每组原文和新文放进 edit_subtitles.replacements 数组；不要只修改最后一句。
- 修改已有字幕绝对不能调用 add_text_overlay；add_text_overlay 只用于新增标题、贴纸或全新的单行字幕，否则会造成文字重叠。
- edit_subtitles 会实际读取 SRT、修改匹配的字幕并从原视频重新烧录；如果工具返回错误或没有 output，绝不能声称已经生成或烧录。
"""


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
        # v1.9: plans stay structured until the user explicitly chooses one.
        self.last_analysis: dict[str, Any] | None = None
        self.last_analysis_source: str | None = None
        self.last_analysis_for_response: dict[str, Any] | None = None
        self.pending_selected_plan: dict[str, Any] | None = None

    def clear_context(self) -> None:
        self.history.clear()
        self.last_analysis = None
        self.last_analysis_source = None
        self.last_analysis_for_response = None
        self.pending_selected_plan = None

    def chat(self, user_text: str) -> str:
        self.last_needs_confirm = False
        self.last_confirmation = None
        self.last_analysis_for_response = None
        self.history.append(
            types.Content(role="user", parts=[types.Part(text=user_text)])
        )

        if self.pending_selected_plan:
            if self._is_cancel_request(user_text):
                self.pending_selected_plan = None
                return "已取消 AI 剪辑草案，原视频和已有成片都没有被修改。"
            if self._is_confirm_request(user_text):
                pending = self.pending_selected_plan
                self.pending_selected_plan = None
                result = render_edit_plan(**pending, confirmed=True)
                self.history.append(types.Content(role="model", parts=[types.Part(text=result)]))
                return result

        if self._looks_like_analysis_request(user_text):
            force = any(key in user_text for key in ("重新分析", "再分析", "刷新分析"))
            try:
                video = _resolve_source(None, prefer_latest_output=False)
                result, analysis = analyze_video(
                    self.client, self.model, video, force=force, include_data=True
                )
                self.last_analysis = analysis
                self.last_analysis_source = str(video)
                # The API returns this separately so the web UI does not have to
                # scrape model prose to render plan cards.
                self.last_analysis_for_response = analysis
            except Exception as exc:  # noqa: BLE001
                result = f"视频分析失败：{type(exc).__name__}: {str(exc)[:500]}"
            self.history.append(types.Content(role="model", parts=[types.Part(text=result)]))
            return result

        selected = self._selected_plan_number(user_text)
        if selected is not None:
            return self._prepare_selected_plan(selected)

        # 复杂的批量字幕/剪辑请求可能包含多个工具调用，给模型足够的编排轮次。
        for round_i in range(12):
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

    @staticmethod
    def _looks_like_analysis_request(text: str) -> bool:
        raw = (text or "").strip()
        if any(key in raw for key in ("重新分析", "再分析", "刷新分析")):
            return True
        return any(
            key in raw
            for key in ("怎么剪", "如何剪", "剪辑建议", "剪辑方案", "怎么编辑", "适合怎么剪")
        )

    @staticmethod
    def _selected_plan_number(text: str) -> int | None:
        match = re.search(
            r"(?:采用|采纳|选择|选用|使用)\s*(?:(?:第\s*)?([1-3])\s*(?:个\s*)?方案|方案\s*(?:第\s*)?([1-3]))",
            (text or "").strip(),
        )
        return int(match.group(1) or match.group(2)) if match else None

    def _prepare_selected_plan(self, number: int) -> str:
        if not self.last_analysis or not self.last_analysis_source:
            return "还没有可采用的剪辑方案。请先说「分析一下这个视频，给我剪辑建议」。"
        recommendations = self.last_analysis.get("recommendations") or []
        if number < 1 or number > len(recommendations):
            return f"方案 {number} 不存在。请在当前分析结果的有效方案中选择。"
        plan = recommendations[number - 1]
        pending = {
            "segments": plan.get("segments") or [],
            "path": self.last_analysis_source,
            "plan_id": str(plan.get("id") or f"plan-{number}"),
            "title": str(plan.get("title") or f"方案 {number}"),
        }
        result = render_edit_plan(
            **pending,
            confirmed=False,
        )
        marker = re.search(r"__VIDEO_AGENT_PENDING__(\{[^\n]*\})", result)
        if marker:
            try:
                self.last_confirmation = json.loads(marker.group(1))
                self.last_needs_confirm = True
                self.pending_selected_plan = pending
            except json.JSONDecodeError:
                pass
        self.history.append(types.Content(role="model", parts=[types.Part(text=result)]))
        return result

    @staticmethod
    def _is_confirm_request(text: str) -> bool:
        return (text or "").strip().lower() in {"确认", "确认执行", "同意", "执行", "confirm", "yes"}

    @staticmethod
    def _is_cancel_request(text: str) -> bool:
        raw = (text or "").strip().lower()
        return raw in {"取消", "不要执行", "先别改", "cancel", "no"}


def load_settings() -> tuple[str, str]:
    from dotenv import load_dotenv

    load_dotenv()
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    if not api_key or api_key.startswith("你的"):
        raise SystemExit("请在 .env 填入 GEMINI_API_KEY")
    return api_key, model

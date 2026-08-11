"""Evidence-based video analysis for editing suggestions.

The module deliberately separates observation from editing. It never writes a
video; it returns timestamped evidence and suggestions that the normal Agent
can later turn into confirmed editing operations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from google.genai import types

from tools import ROOT, _video_meta

ANALYSIS_DIR = ROOT / "data" / "video_analysis"
CACHE_FILE = ANALYSIS_DIR / "cache.json"


def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_key(video: Path) -> str:
    stat = video.stat()
    return f"{video.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"


def _prepare_ascii_upload(video: Path) -> tuple[Path, Path | None]:
    """Create an ASCII-named staging copy when Windows upload encoding needs it."""
    try:
        str(video).encode("ascii")
        return video, None
    except UnicodeEncodeError:
        digest = hashlib.sha256(_cache_key(video).encode("utf-8")).hexdigest()[:12]
        suffix = video.suffix.lower() or ".mp4"
        staged = ANALYSIS_DIR / f"gemini_upload_{digest}{suffix}"
        ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video, staged)
        return staged, staged


def _cleanup_staged_upload(staged: Path | None) -> None:
    if staged is None:
        return
    try:
        staged.unlink(missing_ok=True)
    except OSError:
        pass


def _file_state(file_obj: Any) -> str:
    state = getattr(file_obj, "state", None)
    name = getattr(state, "name", state)
    return str(name or "").upper()


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {"raw": raw}
            except json.JSONDecodeError:
                pass
        return {"raw": raw}


STRATEGY_ORDER = ("retention_short", "information_complete", "story_paced")
STRATEGY_LABELS = {
    "retention_short": "高完播率短版",
    "information_complete": "信息完整版本",
    "story_paced": "轻松故事节奏版",
}


def _number(value: Any) -> float | None:
    """Return a finite timestamp, or None for invalid model output."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 and parsed < float("inf") else None


def _normalise_range_list(items: Any, duration: float | None) -> list[dict[str, Any]]:
    """Validate timestamp ranges before exposing them to a draft or renderer."""
    if not isinstance(items, list):
        return []
    ranges: list[dict[str, Any]] = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        start = _number(item.get("start_sec"))
        end = _number(item.get("end_sec"))
        if start is None or end is None or end <= start:
            continue
        if duration is not None and (start >= duration or end > duration + 0.05):
            continue
        evidence = str(item.get("evidence") or item.get("reason") or "未提供证据")[:300]
        normalised = {
            "start_sec": round(start, 3),
            "end_sec": round(min(end, duration) if duration is not None else end, 3),
            "reason": str(item.get("reason") or evidence)[:300],
            "evidence": evidence,
        }
        if item.get("kind"):
            normalised["kind"] = str(item["kind"])[:80]
        confidence = _number(item.get("confidence"))
        if confidence is not None:
            normalised["confidence"] = min(1.0, max(0.0, confidence))
        ranges.append(normalised)
    return ranges


def validate_analysis(result: dict[str, Any], duration: float | None, cache_key: str) -> dict[str, Any]:
    """Make the VLM response safe and stable enough to become an editable draft.

    The model may still describe a useful observation in prose, but malformed,
    overlapping, or out-of-range edits never reach the execution layer.
    """
    if "raw" in result:
        return result
    observations = _normalise_range_list(result.get("observations"), duration)
    recommendations: list[dict[str, Any]] = []
    seen_strategies: set[str] = set()
    for index, rec in enumerate((result.get("recommendations") or [])[:3]):
        if not isinstance(rec, dict):
            continue
        segments = _normalise_range_list(rec.get("segments"), duration)
        if not segments:
            continue
        segments.sort(key=lambda item: (item["start_sec"], item["end_sec"]))
        if any(current["start_sec"] < previous["end_sec"] for previous, current in zip(segments, segments[1:])):
            continue
        strategy = str(rec.get("strategy") or "").strip().lower()
        if strategy not in STRATEGY_ORDER or strategy in seen_strategies:
            strategy = next((item for item in STRATEGY_ORDER if item not in seen_strategies), None)
        if strategy is None:
            continue
        seen_strategies.add(strategy)
        calculated_duration = round(sum(item["end_sec"] - item["start_sec"] for item in segments), 3)
        plan_seed = f"{cache_key}:{strategy}:{index}:{segments}"
        recommendations.append(
            {
                "id": "plan-" + hashlib.sha256(plan_seed.encode("utf-8")).hexdigest()[:12],
                "strategy": strategy,
                "title": str(rec.get("title") or STRATEGY_LABELS[strategy])[:80],
                "goal": str(rec.get("goal") or STRATEGY_LABELS[strategy])[:200],
                "platform": str(rec.get("platform") or "短视频平台")[:80],
                "segments": segments,
                "remove": _normalise_range_list(rec.get("remove"), duration),
                "estimated_duration_sec": calculated_duration,
                "confidence": min(1.0, max(0.0, _number(rec.get("confidence")) or 0.0)),
            }
        )

    limitations = [str(item)[:240] for item in (result.get("limitations") or []) if str(item).strip()][:8]
    if len(recommendations) < 2:
        limitations.append("模型未能生成足够的有效差异化方案；请重新分析，不要直接采用不完整结果。")
    return {
        "summary": str(result.get("summary") or "模型未能生成内容摘要")[:500],
        "content_type": str(result.get("content_type") or "other")[:40],
        "observations": observations,
        "recommendations": recommendations,
        "limitations": limitations,
    }


def _repair_prompt(meta: dict[str, Any], prior: dict[str, Any]) -> str:
    """A targeted retry when the first response did not contain two valid plans."""
    return (
        "Return corrected strict JSON only. The previous analysis did not contain two valid, "
        "meaningfully different editing plans. Create exactly 3 plans using the strategies "
        "retention_short, information_complete, story_paced. Every plan needs non-overlapping "
        "segments with start_sec/end_sec inside this video duration, a concrete reason tied to "
        "observed audio or visuals, and a different goal. Do not invent timestamps. "
        f"Video metadata: {json.dumps(meta, ensure_ascii=False)}. "
        f"Previous JSON: {json.dumps(prior, ensure_ascii=False)}"
    )


def _local_transcript(video: Path) -> dict[str, Any]:
    """Use faster-whisper when explicitly installed/enabled; otherwise explain why."""
    if os.getenv("LOCAL_TRANSCRIBE", "0").strip().lower() not in {"1", "true", "yes"}:
        return {"status": "disabled", "segments": []}
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {
            "status": "unavailable",
            "segments": [],
            "message": "未安装 faster-whisper；本次由 Gemini 同时理解音频和画面。",
        }

    model_name = (os.getenv("WHISPER_MODEL") or "small").strip()
    device = (os.getenv("WHISPER_DEVICE") or "cpu").strip()
    compute = (os.getenv("WHISPER_COMPUTE_TYPE") or "int8").strip()
    model = WhisperModel(model_name, device=device, compute_type=compute)
    segments, info = model.transcribe(str(video), vad_filter=True)
    rows = []
    for segment in segments:
        rows.append(
            {
                "start_sec": round(float(segment.start), 3),
                "end_sec": round(float(segment.end), 3),
                "text": segment.text.strip(),
            }
        )
    return {
        "status": "ok",
        "language": getattr(info, "language", None),
        "segments": rows,
    }


def _prompt(meta: dict[str, Any], transcript: dict[str, Any]) -> str:
    transcript_hint = json.dumps(transcript, ensure_ascii=False)
    return f"""
你是一个严谨的视频剪辑分析师。请真正检查视频的画面和音频，不要套用泛泛的夸奖。

视频元数据：{json.dumps(meta, ensure_ascii=False)}
本地转录证据（可能为空）：{transcript_hint}

请输出严格 JSON，不要 Markdown，格式如下：
{{
  "summary": "视频内容的一句话事实摘要",
  "content_type": "talking_head|tutorial|product_demo|vlog|gameplay|other",
  "observations": [
    {{"start_sec": 0, "end_sec": 5, "kind": "opening|key_point|silence|repetition|visual_change|ending", "evidence": "具体说明画面或语音看到了什么", "confidence": 0.0}}
  ],
  "recommendations": [
    {{
      "title": "方案名称",
      "strategy": "retention_short|information_complete|story_paced",
      "goal": "适合什么用途",
      "platform": "适合的平台或场景",
      "segments": [{{"start_sec": 0, "end_sec": 5, "reason": "必须引用具体语音或画面证据"}}],
      "remove": [{{"start_sec": 5, "end_sec": 7, "reason": "必须说明删除依据"}}],
      "estimated_duration_sec": 5,
      "confidence": 0.0
    }}
  ],
  "limitations": ["无法确定的内容或可能漏检的细节"]
}}

硬性要求：
1. 每个时间段都必须有事实依据；无法确认就放入 limitations。
2. 不要只写“精彩、节奏好、适合传播”等空话。
3. 快速动作、画面小字、低音量语音可能漏检，要诚实说明。
4. 必须给出恰好 3 个实质不同的方案，strategy 依次使用 retention_short、information_complete、story_paced；优先生成能映射到保留片段/删除片段的建议。
""".strip()


def _format_result(result: dict[str, Any], source: Path, transcript: dict[str, Any]) -> str:
    if "raw" in result:
        return "视频分析返回格式异常，原始结果如下：\n" + str(result["raw"])

    lines = [
        "视频分析完成（仅分析，没有修改文件）。",
        f"源文件：{source.name}",
        f"内容摘要：{result.get('summary') or '模型未能确定'}",
        f"内容类型：{result.get('content_type') or '未确定'}",
    ]
    if transcript.get("status") == "ok":
        lines.append(f"本地 Whisper 转录：已获得 {len(transcript.get('segments') or [])} 段带时间戳文本")
    elif transcript.get("message"):
        lines.append(f"转录说明：{transcript['message']}")

    observations = result.get("observations") or []
    if observations:
        lines.append("\n观察证据：")
        for item in observations[:8]:
            lines.append(
                f"  - {item.get('start_sec', 0)}s~{item.get('end_sec', 0)}s："
                f"{item.get('evidence') or item.get('kind') or '未说明'} "
                f"（置信度 {item.get('confidence', '未提供')}）"
            )

    recommendations = result.get("recommendations") or []
    lines.append("\n推荐剪辑方案：")
    for index, rec in enumerate(recommendations[:3], 1):
        lines.append(
            f"\n方案 {index}：{rec.get('title') or '未命名'}"
            f"（{rec.get('goal') or '未说明用途'}，置信度 {rec.get('confidence', '未提供')}）"
        )
        for seg in rec.get("segments") or []:
            lines.append(
                f"  保留 {seg.get('start_sec', 0)}s~{seg.get('end_sec', 0)}s："
                f"{seg.get('reason') or '未提供理由'}"
            )
        for cut in rec.get("remove") or []:
            lines.append(
                f"  删除 {cut.get('start_sec', 0)}s~{cut.get('end_sec', 0)}s："
                f"{cut.get('reason') or '未提供理由'}"
            )
        if rec.get("estimated_duration_sec") is not None:
            lines.append(f"  预计时长：{rec['estimated_duration_sec']} 秒")

    limitations = result.get("limitations") or []
    if limitations:
        lines.append("\n分析限制：")
        lines.extend(f"  - {item}" for item in limitations[:6])
    lines.append("\n你可以说「采用方案 1」，我会把它转换为可确认的剪辑计划。")
    return "\n".join(lines)


def analyze_video(
    client: Any,
    model: str,
    video: Path,
    *,
    force: bool = False,
    include_data: bool = False,
) -> str | tuple[str, dict[str, Any]]:
    """Analyze one local video and return evidence-backed editing suggestions."""
    video = video.resolve()
    if not video.exists() or not video.is_file():
        return f"找不到视频：{video}"

    key = _cache_key(video)
    cache = _load_cache()
    if not force and key in cache:
        cached = cache[key]
        analysis = validate_analysis(
            cached.get("analysis") or {},
            _number(_video_meta(video).get("duration_sec")),
            key,
        )
        if analysis != cached.get("analysis"):
            cached["analysis"] = analysis
            _save_cache(cache)
        formatted = _format_result(analysis, video, cached.get("transcript") or {})
        return (formatted, analysis) if include_data else formatted

    meta = _video_meta(video)
    upload_video, staged_upload = _prepare_ascii_upload(video)
    try:
        transcript = _local_transcript(upload_video)
        uploaded = client.files.upload(file=str(upload_video))
        deadline = time.time() + float(os.getenv("VIDEO_ANALYSIS_TIMEOUT_SEC") or "180")
        while _file_state(uploaded) in {"PROCESSING", "STATE_UNSPECIFIED", ""}:
            if time.time() >= deadline:
                return "视频上传到 Gemini 后处理超时，请稍后重试。"
            time.sleep(2)
            uploaded = client.files.get(name=uploaded.name)
        if _file_state(uploaded) == "FAILED":
            return "Gemini 无法处理这个视频文件。"

        response = client.models.generate_content(
            model=model,
            contents=[uploaded, _prompt(meta, transcript)],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        result = validate_analysis(
            _extract_json(getattr(response, "text", "") or ""),
            _number(meta.get("duration_sec")),
            key,
        )
        # A second, narrow request is much more reliable than quietly presenting
        # one generic recommendation as if it were a choice.
        if "raw" not in result and len(result.get("recommendations") or []) < 2:
            retry = client.models.generate_content(
                model=model,
                contents=[uploaded, _repair_prompt(meta, result)],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            result = validate_analysis(
                _extract_json(getattr(retry, "text", "") or ""),
                _number(meta.get("duration_sec")),
                key,
            )
    except Exception as exc:  # noqa: BLE001
        return f"视频分析失败：{type(exc).__name__}: {str(exc)[:500]}"

    finally:
        _cleanup_staged_upload(staged_upload)

    cache[key] = {"video": str(video), "analysis": result, "transcript": transcript, "created_at": time.time()}
    _save_cache(cache)
    formatted = _format_result(result, video, transcript)
    return (formatted, result) if include_data else formatted

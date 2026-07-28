"""
视频切片工具：探测时长 + 保留某一段（删减片头/片尾/截取中间）。

对应 OpenChatCut 里「裁剪时间线」的缩小版：这里直接用 FFmpeg 出新文件。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from ffmpeg_bin import get_ffmpeg

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
JOB_FILE = ROOT / "data" / "last_job.json"


def _default_video() -> Path:
    rel = (os.getenv("DEFAULT_VIDEO") or "samples/pubg.mp4").strip()
    path = Path(rel)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _ensure_video(path: str | None = None) -> Path:
    video = Path(path).expanduser().resolve() if path else _default_video()
    if not video.exists():
        raise FileNotFoundError(f"找不到视频文件: {video}")
    return video


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def probe_video(path: str | None = None) -> str:
    """查看视频基本信息：时长、分辨率、路径。"""
    try:
        video = _ensure_video(path)
    except FileNotFoundError as e:
        return str(e)

    ffmpeg = get_ffmpeg()
    # ffmpeg -i 会把信息打到 stderr，并返回非 0，这是正常现象
    proc = _run([ffmpeg, "-hide_banner", "-i", str(video)])
    text = (proc.stderr or "") + "\n" + (proc.stdout or "")

    duration = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", text)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        duration = h * 3600 + mi * 60 + s

    size = None
    m2 = re.search(r"(\d{2,5})x(\d{2,5})", text)
    if m2:
        size = f"{m2.group(1)}x{m2.group(2)}"

    info = {
        "path": str(video),
        "duration_sec": round(duration, 3) if duration is not None else None,
        "resolution": size,
        "size_mb": round(video.stat().st_size / (1024 * 1024), 2),
    }
    return json.dumps(info, ensure_ascii=False, indent=2)


def trim_keep(
    start_sec: float,
    end_sec: float,
    path: str | None = None,
    confirmed: bool = False,
) -> str:
    """
    只保留 [start_sec, end_sec) 这一段，相当于删掉前后多余部分。

    例子：
    - 去掉前 5 秒：先 probe 得到总时长 T，再 trim_keep(5, T)
    - 只要 10~40 秒：trim_keep(10, 40)

    confirmed=False：只返回计划，不生成文件
    confirmed=True：调用 FFmpeg 写出 output/ 下的新视频
    """
    try:
        video = _ensure_video(path)
    except FileNotFoundError as e:
        return str(e)

    try:
        start = float(start_sec)
        end = float(end_sec)
    except (TypeError, ValueError):
        return "错误：start_sec / end_sec 必须是数字（单位：秒）。"

    if start < 0 or end <= start:
        return "错误：需要满足 0 <= start_sec < end_sec。"

    # 读取时长做基本校验（失败也不阻断，FFmpeg 还会再判）
    meta_raw = probe_video(str(video))
    try:
        meta = json.loads(meta_raw)
        total = meta.get("duration_sec")
    except json.JSONDecodeError:
        total = None

    if total is not None and start >= total:
        return f"错误：start_sec={start} 已超过视频时长 {total} 秒。"
    if total is not None and end > total + 0.05:
        end = float(total)

    keep = round(end - start, 3)
    plan = {
        "action": "trim_keep",
        "input": str(video),
        "start_sec": start,
        "end_sec": end,
        "keep_sec": keep,
        "note": f"将保留原片 {start}s ~ {end}s（约 {keep} 秒），其余丢弃",
    }

    if not confirmed:
        return (
            "【待确认】切片计划：\n"
            + json.dumps(plan, ensure_ascii=False, indent=2)
            + "\n若用户同意，请再次调用 trim_keep，参数相同且 confirmed=true。"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUTPUT_DIR / f"trim_{start:.0f}_{end:.0f}_{stamp}.mp4"

    ffmpeg = get_ffmpeg()
    # -ss 放在 -i 前：快；再 -t 控制时长。教学阶段优先速度。
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(start),
        "-i",
        str(video),
        "-t",
        str(keep),
        "-c",
        "copy",
        str(out),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not out.exists():
        # copy 失败时回退重编码（更稳，稍慢）
        cmd_re = [
            ffmpeg,
            "-y",
            "-ss",
            str(start),
            "-i",
            str(video),
            "-t",
            str(keep),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(out),
        ]
        proc2 = _run(cmd_re)
        if proc2.returncode != 0 or not out.exists():
            err = (proc2.stderr or proc.stderr or "")[-800:]
            return f"FFmpeg 失败：\n{err}"

    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    JOB_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return (
        "切片完成。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + f"\n请用播放器打开: {out.resolve()}"
    )


def list_outputs() -> str:
    """列出 output/ 目录里已经导出的成片。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [p for p in OUTPUT_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return "output/ 里还没有导出的视频。"
    rows = []
    for i, p in enumerate(files, 1):
        mb = round(p.stat().st_size / (1024 * 1024), 2)
        rows.append(f"{i}. {p.name}  ({mb} MB)\n   路径: {p.resolve()}")
    return "已导出成片：\n" + "\n".join(rows)


def delete_output(name_or_path: str, confirmed: bool = False) -> str:
    """
    删除 output/ 里的某个已导出视频（不会删除 samples/ 或用户原片）。
    可传文件名（如 trim_5_84_xxx.mp4）或完整路径。
    """
    text = (name_or_path or "").strip().strip('"')
    if not text:
        return "错误：请提供要删除的文件名或路径。可先 list_outputs。"

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = OUTPUT_DIR / candidate.name
    candidate = candidate.resolve()

    output_root = OUTPUT_DIR.resolve()
    try:
        candidate.relative_to(output_root)
    except ValueError:
        return (
            "错误：只能删除 output/ 目录内的导出文件，"
            "不能删样品或你的原始视频。请先 list_outputs。"
        )

    if not candidate.exists() or not candidate.is_file():
        return f"错误：文件不存在：{candidate}"

    plan = {"action": "delete_output", "file": str(candidate)}
    if not confirmed:
        return (
            "【待确认】将删除导出成片：\n"
            + json.dumps(plan, ensure_ascii=False, indent=2)
            + "\n若用户同意，请再次调用 delete_output，confirmed=true。"
        )

    candidate.unlink()
    return f"已删除：{candidate}"


TOOL_DECLARATIONS = [
    {
        "name": "probe_video",
        "description": (
            "查看指定路径（或默认 PUBG 样本）视频的时长、分辨率等。"
            "用户给出新视频路径时，先调用本工具切换工作对象。"
            "切片前应先调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "视频完整路径；省略则使用默认 PUBG 样本。",
                }
            },
        },
    },
    {
        "name": "trim_keep",
        "description": (
            "只保留视频的 [start_sec, end_sec) 片段并导出新文件到 output/。"
            "去掉前 N 秒：start_sec=N，end_sec=总时长；"
            "截取中间：传入起止秒数。"
            "path 传入用户指定的源视频；省略则用默认样本。"
            "第一次必须 confirmed=false 预览；用户确认后再 confirmed=true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_sec": {
                    "type": "number",
                    "description": "保留区间起点（秒）",
                },
                "end_sec": {
                    "type": "number",
                    "description": "保留区间终点（秒）",
                },
                "path": {
                    "type": "string",
                    "description": "源视频路径，默认 PUBG 样本",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "false=只预览计划；true=执行 FFmpeg 导出",
                },
            },
            "required": ["start_sec", "end_sec"],
        },
    },
    {
        "name": "list_outputs",
        "description": "列出 output/ 里已经剪辑导出的成片，供用户查看或选择删除。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_output",
        "description": (
            "删除 output/ 中的某个已导出成片。"
            "只能删导出结果，不能删用户原片。"
            "先 confirmed=false 预览，用户确认后再 confirmed=true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_path": {
                    "type": "string",
                    "description": "文件名或 output 下完整路径",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "false=预览；true=真正删除",
                },
            },
            "required": ["name_or_path"],
        },
    },
]


def run_tool(name: str, args: dict) -> str:
    args = args or {}
    if name == "probe_video":
        return probe_video(args.get("path"))
    if name == "trim_keep":
        return trim_keep(
            start_sec=args.get("start_sec", 0),
            end_sec=args.get("end_sec", 0),
            path=args.get("path"),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "list_outputs":
        return list_outputs()
    if name == "delete_output":
        return delete_output(
            name_or_path=str(args.get("name_or_path", "")),
            confirmed=bool(args.get("confirmed", False)),
        )
    return f"未知工具：{name}"

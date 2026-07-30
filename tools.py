"""
视频工具：探测、切片、文字贴纸、打开成片。

对应 OpenChatCut 里「裁剪 / 叠加文字」的缩小版：这里直接用 FFmpeg 出新文件。
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from ffmpeg_bin import get_ffmpeg

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
JOB_FILE = ROOT / "data" / "last_job.json"

# 位置预设 → drawtext 的 x/y（相对画面）
_POSITION_XY = {
    "top": ("(w-text_w)/2", "h*0.08"),
    "center": ("(w-text_w)/2", "(h-text_h)/2"),
    "bottom": ("(w-text_w)/2", "h*0.82"),
    "top_left": ("w*0.05", "h*0.08"),
    "top_right": ("w*0.95-text_w", "h*0.08"),
}

# 样式预设：字号 / 描边，偏「能直接用」而不是让用户填一堆参数
_STYLE_PRESETS = {
    "title": {"fontsize": 56, "borderw": 3, "label": "大标题"},
    "subtitle": {"fontsize": 36, "borderw": 2, "label": "底部字幕"},
    "sticker": {"fontsize": 42, "borderw": 3, "label": "贴纸角标"},
}


def _hint(*lines: str) -> str:
    """拼一段「接下来可以试试」的友好提示。"""
    body = "\n".join(f"  · {x}" for x in lines)
    return f"\n\n接下来可以试试：\n{body}"


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


def _list_output_files() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        [
            p
            for p in OUTPUT_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _resolve_output(name_or_path: str | None = None) -> Path:
    """
    解析 output/ 里的成片：
    - 省略 / 「最新」→ 最新导出
    - 文件名或完整路径 → 对应文件（必须在 output/ 内）
    """
    files = _list_output_files()
    text = (name_or_path or "").strip().strip('"')
    if not text or text in {"最新", "latest", "最近", "刚导出的"}:
        if not files:
            raise FileNotFoundError("output/ 里还没有成片。请先切片或加文字后再打开。")
        return files[0].resolve()

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = OUTPUT_DIR / candidate.name
    candidate = candidate.resolve()

    try:
        candidate.relative_to(OUTPUT_DIR.resolve())
    except ValueError as e:
        raise FileNotFoundError(
            "只能操作 output/ 目录内的导出文件。可先 list_outputs。"
        ) from e

    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"文件不存在：{candidate}")
    return candidate


@lru_cache(maxsize=1)
def _find_cjk_font() -> Path | None:
    """尽量找到能显示中文的字体（Windows 优先微软雅黑）。"""
    env = (os.getenv("VIDEO_FONT") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p.resolve()

    candidates: list[Path] = []
    if platform.system() == "Windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        fonts = windir / "Fonts"
        candidates.extend(
            [
                fonts / "msyh.ttc",
                fonts / "msyhbd.ttc",
                fonts / "msyh.ttf",
                fonts / "simhei.ttf",
                fonts / "simsun.ttc",
                fonts / "NotoSansSC-Regular.otf",
            ]
        )
    elif platform.system() == "Darwin":
        candidates.extend(
            [
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/STHeiti Light.ttc"),
                Path("/Library/Fonts/Arial Unicode.ttf"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
            ]
        )

    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def _escape_drawtext(text: str) -> str:
    """FFmpeg drawtext 特殊字符转义。"""
    # 顺序：先反斜杠
    out = text.replace("\\", "\\\\")
    out = out.replace(":", "\\:")
    out = out.replace("'", "\\'")
    out = out.replace("%", "\\%")
    out = out.replace("\n", " ")
    out = out.replace("\r", "")
    return out


def _drawtext_filter(
    text: str,
    *,
    position: str,
    fontsize: int,
    fontcolor: str,
    borderw: int,
    start_sec: float | None,
    end_sec: float | None,
    fontfile: Path,
) -> str:
    x, y = _POSITION_XY.get(position, _POSITION_XY["bottom"])
    # Windows 盘符冒号必须转义，且路径建议加单引号（实测更稳）
    font_path = str(fontfile).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", font_path):
        font_path = font_path[0] + "\\:" + font_path[2:]
    parts = [
        f"fontfile='{font_path}'",
        f"text='{_escape_drawtext(text)}'",
        f"fontsize={int(fontsize)}",
        f"fontcolor={fontcolor}",
        f"borderw={int(borderw)}",
        "bordercolor=black",
        f"x={x}",
        f"y={y}",
    ]
    if start_sec is not None or end_sec is not None:
        s = 0.0 if start_sec is None else float(start_sec)
        if end_sec is None:
            parts.append(f"enable='gte(t\\,{s})'")
        else:
            e = float(end_sec)
            parts.append(f"enable='between(t\\,{s}\\,{e})'")
    return "drawtext=" + ":".join(parts)


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
    tip = ""
    if duration is not None:
        tip = _hint(
            f"去掉前 5 秒：会保留约 {max(0, round(duration - 5, 1))} 秒",
            "只保留某一段：例如「只要 10 秒到 30 秒」",
            "加标题贴纸：例如「加个标题：今日高光」",
        )
    return json.dumps(info, ensure_ascii=False, indent=2) + tip


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
        + _hint(
            "打开刚导出的视频（我会用系统播放器打开最新成片）",
            "给成片加标题：例如「加标题：决赛高光」",
            "加一句底部字幕：例如「底部加字幕：感谢观看」",
        )
    )


def list_outputs() -> str:
    """列出 output/ 目录里已经导出的成片。"""
    files = _list_output_files()
    if not files:
        return "output/ 里还没有导出的视频。先试着「去掉前 5 秒」做一条成片吧。"
    rows = []
    for i, p in enumerate(files, 1):
        mb = round(p.stat().st_size / (1024 * 1024), 2)
        mark = " ← 最新" if i == 1 else ""
        rows.append(f"{i}. {p.name}  ({mb} MB){mark}\n   路径: {p.resolve()}")
    return (
        "已导出成片：\n"
        + "\n".join(rows)
        + _hint(
            "打开最新成片 / 打开某一个文件名",
            "给最新成片加文字贴纸",
            "删除不需要的成片（会先给你确认）",
        )
    )


def delete_output(name_or_path: str, confirmed: bool = False) -> str:
    """
    删除 output/ 里的某个已导出视频（不会删除 samples/ 或用户原片）。
    可传文件名（如 trim_5_84_xxx.mp4）或完整路径。
    """
    text = (name_or_path or "").strip().strip('"')
    if not text:
        return "错误：请提供要删除的文件名或路径。可先 list_outputs。"

    try:
        candidate = _resolve_output(text)
    except FileNotFoundError as e:
        return str(e)

    plan = {"action": "delete_output", "file": str(candidate)}
    if not confirmed:
        return (
            "【待确认】将删除导出成片：\n"
            + json.dumps(plan, ensure_ascii=False, indent=2)
            + "\n若用户同意，请再次调用 delete_output，confirmed=true。"
        )

    candidate.unlink()
    return f"已删除：{candidate}" + _hint("列出剩下的成片", "继续切片或加文字做新成片")


def open_output(name_or_path: str | None = None) -> str:
    """用系统默认播放器打开 output/ 里的成片；省略则打开最新一条。"""
    try:
        target = _resolve_output(name_or_path)
    except FileNotFoundError as e:
        return str(e)

    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            _run(["open", str(target)])
        else:
            _run(["xdg-open", str(target)])
    except OSError as e:
        return f"打开失败：{e}\n请手动打开：{target}"

    return (
        f"已用系统播放器打开：\n{target}"
        + _hint(
            "不满意可以再说怎么改（再切一段 / 换文字）",
            "列出全部成片",
        )
    )


def add_text_overlay(
    text: str,
    path: str | None = None,
    style: str = "title",
    position: str | None = None,
    fontsize: float | None = None,
    fontcolor: str = "white",
    start_sec: float | None = None,
    end_sec: float | None = None,
    confirmed: bool = False,
) -> str:
    """
    在视频上叠加一行文字（标题 / 字幕 / 角标贴纸），导出到 output/。

    style: title | subtitle | sticker
    position: top | center | bottom | top_left | top_right（可省略，按 style 给默认）
    """
    raw = (text or "").strip()
    if not raw:
        return "错误：文字不能为空。例如「决赛高光」或「感谢观看」。"
    if len(raw) > 40:
        return "错误：单行文字请控制在 40 字以内，太长画面会挤在一起。"

    style_key = (style or "title").strip().lower()
    if style_key not in _STYLE_PRESETS:
        return f"错误：style 只能是 {', '.join(_STYLE_PRESETS)}，收到：{style_key}"

    preset = _STYLE_PRESETS[style_key]
    # 样式默认位置：标题居中、字幕底部、贴纸右上
    default_pos = {"title": "center", "subtitle": "bottom", "sticker": "top_right"}[style_key]
    pos_key = (position or default_pos).strip().lower()
    if pos_key not in _POSITION_XY:
        return f"错误：position 只能是 {', '.join(_POSITION_XY)}，收到：{pos_key}"

    try:
        size = int(fontsize) if fontsize is not None else int(preset["fontsize"])
    except (TypeError, ValueError):
        return "错误：fontsize 必须是数字。"
    if size < 12 or size > 120:
        return "错误：fontsize 建议在 12～120 之间。"

    color = (fontcolor or "white").strip() or "white"
    # 简单白名单，避免往滤镜里塞奇怪字符串
    if not re.fullmatch(r"[#A-Za-z0-9_]+", color):
        return "错误：fontcolor 请用 white / yellow / #FFFFFF 这类简单颜色名。"

    # 源视频：显式路径 > 最新成片 > 默认样本
    video: Path
    try:
        if path:
            video = _ensure_video(path)
        else:
            latest = _list_output_files()
            video = latest[0] if latest else _ensure_video(None)
    except FileNotFoundError as e:
        return str(e)

    font = _find_cjk_font()
    if font is None:
        return (
            "错误：找不到可显示中文的字体。"
            "请在 .env 设置 VIDEO_FONT=字体文件完整路径 后重试。"
        )

    s_sec = float(start_sec) if start_sec is not None else None
    e_sec = float(end_sec) if end_sec is not None else None
    if s_sec is not None and s_sec < 0:
        return "错误：start_sec 不能为负。"
    if s_sec is not None and e_sec is not None and e_sec <= s_sec:
        return "错误：需要满足 start_sec < end_sec。"

    time_note = "全程显示"
    if s_sec is not None and e_sec is not None:
        time_note = f"仅在 {s_sec}s ~ {e_sec}s 显示"
    elif s_sec is not None:
        time_note = f"从 {s_sec}s 起一直显示"
    elif e_sec is not None:
        time_note = f"从开头显示到 {e_sec}s"

    plan = {
        "action": "add_text_overlay",
        "input": str(video),
        "text": raw,
        "style": style_key,
        "style_label": preset["label"],
        "position": pos_key,
        "fontsize": size,
        "fontcolor": color,
        "borderw": preset["borderw"],
        "font": str(font),
        "time": time_note,
        "note": f"将以「{preset['label']}」样式叠加文字「{raw}」",
    }

    if not confirmed:
        return (
            "【待确认】文字贴纸计划：\n"
            + json.dumps(plan, ensure_ascii=False, indent=2)
            + "\n若用户同意，请再次调用 add_text_overlay，参数相同且 confirmed=true。"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUTPUT_DIR / f"text_{style_key}_{stamp}.mp4"

    vf = _drawtext_filter(
        raw,
        position=pos_key,
        fontsize=size,
        fontcolor=color,
        borderw=int(preset["borderw"]),
        start_sec=s_sec,
        end_sec=e_sec,
        fontfile=font,
    )
    ffmpeg = get_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = _run(cmd)
    if proc.returncode != 0 or not out.exists():
        # 音频 copy 失败时整段重编码
        cmd_re = [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-vf",
            vf,
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
            err = (proc2.stderr or proc.stderr or "")[-900:]
            return f"FFmpeg 文字叠加失败：\n{err}"

    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    JOB_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return (
        "文字贴纸已加上。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint(
            "打开刚做好的视频看看效果",
            "觉得字太大/太小可以说「字号改成 40」再做一版",
            "还可以换位置：顶部 / 底部 / 右上角",
        )
    )


TOOL_DECLARATIONS = [
    {
        "name": "probe_video",
        "description": (
            "查看指定路径（或默认样本）视频的时长、分辨率等。"
            "用户给出新视频路径时，先调用本工具切换工作对象。"
            "切片前应先调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "视频完整路径；省略则使用默认样本。",
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
                    "description": "源视频路径，默认样本",
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
        "name": "add_text_overlay",
        "description": (
            "给视频叠加一行中文/英文文字贴纸（标题、底部字幕、角标）。"
            "默认作用在最新成片；也可 path 指定源视频。"
            "style=title 大标题居中；subtitle 底部字幕；sticker 右上角角标。"
            "可用 position 覆盖位置：top/center/bottom/top_left/top_right。"
            "可设 start_sec/end_sec 控制出现时段；省略则全程显示。"
            "第一次 confirmed=false 预览；用户确认后再 confirmed=true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要叠加的文字，单行，建议不超过 40 字",
                },
                "path": {
                    "type": "string",
                    "description": "源视频路径；省略则优先用最新成片",
                },
                "style": {
                    "type": "string",
                    "description": "title | subtitle | sticker，默认 title",
                },
                "position": {
                    "type": "string",
                    "description": "top | center | bottom | top_left | top_right；省略则按 style 默认",
                },
                "fontsize": {
                    "type": "number",
                    "description": "字号，可选；省略则用样式预设",
                },
                "fontcolor": {
                    "type": "string",
                    "description": "颜色，如 white / yellow / #FFFFFF，默认 white",
                },
                "start_sec": {
                    "type": "number",
                    "description": "文字开始出现的秒数，可选",
                },
                "end_sec": {
                    "type": "number",
                    "description": "文字消失的秒数，可选",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "false=预览计划；true=执行导出",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "open_output",
        "description": (
            "用系统默认播放器打开 output/ 里的成片。"
            "用户说「打开」「播放」「看看效果」时调用。"
            "省略 name_or_path 则打开最新成片。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_path": {
                    "type": "string",
                    "description": "文件名、路径，或「最新」；省略=最新成片",
                },
            },
        },
    },
    {
        "name": "list_outputs",
        "description": "列出 output/ 里已经剪辑导出的成片，供用户查看、打开或删除。",
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
    if name == "add_text_overlay":
        return add_text_overlay(
            text=str(args.get("text", "")),
            path=args.get("path"),
            style=str(args.get("style") or "title"),
            position=args.get("position"),
            fontsize=args.get("fontsize"),
            fontcolor=str(args.get("fontcolor") or "white"),
            start_sec=args.get("start_sec"),
            end_sec=args.get("end_sec"),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "open_output":
        return open_output(args.get("name_or_path"))
    if name == "list_outputs":
        return list_outputs()
    if name == "delete_output":
        return delete_output(
            name_or_path=str(args.get("name_or_path", "")),
            confirmed=bool(args.get("confirmed", False)),
        )
    return f"未知工具：{name}"

"""
视频工具：探测、切片、删中间、拼接、文字、静音、变速、预览截图、打开成片。

对应 OpenChatCut 里常见剪辑动作的缩小版：这里直接用 FFmpeg 出新文件。
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from ffmpeg_bin import get_ffmpeg

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
PREVIEW_DIR = OUTPUT_DIR / "previews"
JOB_FILE = ROOT / "data" / "last_job.json"
SESSION_FILE = ROOT / "data" / "session.json"

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}

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


def _pending(title: str, summary: str, plan: dict, tool_name: str) -> str:
    """口语化待确认文案 + 精简计划（方便模型原样重调）。"""
    return (
        f"【待确认】{title}\n"
        f"{summary}\n"
        f"计划详情：\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n"
        f"若用户同意，请再次调用 {tool_name}，参数相同且 confirmed=true。"
    )


def _save_job(result: dict) -> None:
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    JOB_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_session() -> dict:
    if not SESSION_FILE.exists():
        return {}
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_session(data: dict) -> None:
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_working_video(path: Path) -> None:
    session = _load_session()
    session["working_video"] = str(path.resolve())
    _save_session(session)


def _get_working_video() -> Path | None:
    raw = (_load_session().get("working_video") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.exists() and p.is_file():
        return p.resolve()
    return None


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


def _resolve_source(
    path: str | None = None,
    *,
    prefer_latest_output: bool = False,
) -> Path:
    """
    解析源视频优先级：
    显式 path >（可选）最新成片 > 会话工作视频 > 默认样本
    """
    if path:
        video = _ensure_video(path)
        _set_working_video(video)
        return video
    if prefer_latest_output:
        latest = _list_output_files()
        if latest:
            return latest[0]
    working = _get_working_video()
    if working is not None:
        return working
    return _ensure_video(None)


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
            if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
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


def _resolve_any_video(name_or_path: str) -> Path:
    """解析任意本地视频：绝对/相对路径，或 output/ 文件名。"""
    text = (name_or_path or "").strip().strip('"')
    if not text:
        raise FileNotFoundError("请提供视频路径或 output/ 下的文件名。")
    if text in {"最新", "latest", "最近", "刚导出的"}:
        return _resolve_output(None)

    candidate = Path(text).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate.resolve()

    in_output = OUTPUT_DIR / Path(text).name
    if in_output.exists() and in_output.is_file():
        return in_output.resolve()

    raise FileNotFoundError(f"找不到视频：{text}")


def _parse_clip_list(clips: object) -> list[Path]:
    """接受 list，或逗号/换行分隔的字符串。"""
    items: list[str] = []
    if clips is None:
        return []
    if isinstance(clips, (list, tuple)):
        items = [str(x).strip() for x in clips if str(x).strip()]
    else:
        text = str(clips).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                items = []
        if not items:
            parts = re.split(r"[,;\n]+", text)
            items = [p.strip().strip('"') for p in parts if p.strip()]

    paths: list[Path] = []
    for item in items:
        paths.append(_resolve_any_video(item))
    return paths


def _video_meta(video: Path) -> dict:
    """读取时长、分辨率（干净 dict，供内部校验）。"""
    ffmpeg = get_ffmpeg()
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

    has_audio = "Audio:" in text
    return {
        "path": str(video.resolve()),
        "duration_sec": round(duration, 3) if duration is not None else None,
        "resolution": size,
        "size_mb": round(video.stat().st_size / (1024 * 1024), 2),
        "has_audio": has_audio,
    }


def _open_path(target: Path) -> str:
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            _run(["open", str(target)])
        else:
            _run(["xdg-open", str(target)])
    except OSError as e:
        return f"打开失败：{e}\n请手动打开：{target}"
    return f"已用系统默认程序打开：\n{target}"


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


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _encode_ok(out: Path, proc: subprocess.CompletedProcess[str]) -> bool:
    return proc.returncode == 0 and out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


def probe_video(path: str | None = None) -> str:
    """查看视频基本信息：时长、分辨率、路径；并记住为当前工作视频。"""
    try:
        video = _resolve_source(path)
    except FileNotFoundError as e:
        return str(e)

    _set_working_video(video)
    info = _video_meta(video)
    tip = ""
    duration = info.get("duration_sec")
    if duration is not None:
        tip = _hint(
            f"去掉前 5 秒：会保留约 {max(0, round(float(duration) - 5, 1))} 秒",
            "删掉中间一段：例如「去掉 10 秒到 20 秒」",
            "加标题贴纸：例如「加个标题：今日高光」",
            "截一张预览图：例如「截第 3 秒看看」",
        )
    working_note = f"\n（已设为当前工作视频）"
    return json.dumps(info, ensure_ascii=False, indent=2) + working_note + tip


def trim_keep(
    start_sec: float,
    end_sec: float,
    path: str | None = None,
    precise: bool = False,
    confirmed: bool = False,
) -> str:
    """
    只保留 [start_sec, end_sec) 这一段。

    precise=True 时强制重编码，切点更准，稍慢。
    """
    try:
        video = _resolve_source(path)
    except FileNotFoundError as e:
        return str(e)

    try:
        start = float(start_sec)
        end = float(end_sec)
    except (TypeError, ValueError):
        return "错误：start_sec / end_sec 必须是数字（单位：秒）。"

    if start < 0 or end <= start:
        return "错误：需要满足 0 <= start_sec < end_sec。"

    meta = _video_meta(video)
    total = meta.get("duration_sec")
    if total is not None and start >= total:
        return f"错误：start_sec={start} 已超过视频时长 {total} 秒。"
    if total is not None and end > float(total) + 0.05:
        end = float(total)

    keep = round(end - start, 3)
    mode = "精密切片（重编码）" if precise else "快速切片（优先 stream copy）"
    plan = {
        "action": "trim_keep",
        "input": str(video),
        "start_sec": start,
        "end_sec": end,
        "keep_sec": keep,
        "precise": bool(precise),
        "note": f"将保留原片 {start}s ~ {end}s（约 {keep} 秒），其余丢弃",
    }
    summary = (
        f"将保留 {start}s ~ {end}s（约 {keep} 秒），其余丢掉。\n"
        f"方式：{mode}\n"
        f"源文件：{video.name}"
    )

    if not confirmed:
        return _pending("切片计划", summary, plan, "trim_keep")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"trim_{start:.0f}_{end:.0f}_{_stamp()}.mp4"
    ffmpeg = get_ffmpeg()

    if precise:
        cmd = [
            ffmpeg, "-y",
            "-ss", str(start), "-i", str(video), "-t", str(keep),
            "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
            str(out),
        ]
        proc = _run(cmd)
        if not _encode_ok(out, proc):
            err = (proc.stderr or "")[-800:]
            return f"FFmpeg 精密切片失败：\n{err}"
    else:
        cmd = [
            ffmpeg, "-y",
            "-ss", str(start), "-i", str(video), "-t", str(keep),
            "-c", "copy", str(out),
        ]
        proc = _run(cmd)
        if not _encode_ok(out, proc):
            cmd_re = [
                ffmpeg, "-y",
                "-ss", str(start), "-i", str(video), "-t", str(keep),
                "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
                str(out),
            ]
            proc2 = _run(cmd_re)
            if not _encode_ok(out, proc2):
                err = (proc2.stderr or proc.stderr or "")[-800:]
                return f"FFmpeg 失败：\n{err}"

    _set_working_video(out)
    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    _save_job(result)
    return (
        "切片完成。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint(
            "打开刚导出的视频看看",
            "删掉中间某一段：例如「去掉 3 秒到 5 秒」",
            "加标题：例如「加标题：决赛高光」",
        )
    )


def cut_out(
    start_sec: float,
    end_sec: float,
    path: str | None = None,
    confirmed: bool = False,
) -> str:
    """删掉 [start_sec, end_sec) 中间一段，前后拼回成新视频。"""
    try:
        video = _resolve_source(path)
    except FileNotFoundError as e:
        return str(e)

    try:
        start = float(start_sec)
        end = float(end_sec)
    except (TypeError, ValueError):
        return "错误：start_sec / end_sec 必须是数字（单位：秒）。"

    if start < 0 or end <= start:
        return "错误：需要满足 0 <= start_sec < end_sec。"

    meta = _video_meta(video)
    total = meta.get("duration_sec")
    if total is None:
        return "错误：读不到视频时长，无法删中间段。请先 probe_video。"
    total_f = float(total)
    if start >= total_f:
        return f"错误：start_sec={start} 已超过视频时长 {total_f} 秒。"
    if end > total_f + 0.05:
        end = total_f
    if start <= 0.01 and end >= total_f - 0.01:
        return "错误：这样会删光整段视频。请缩小要删除的区间。"

    remove = round(end - start, 3)
    remain = round(total_f - remove, 3)
    plan = {
        "action": "cut_out",
        "input": str(video),
        "cut_start_sec": start,
        "cut_end_sec": end,
        "remove_sec": remove,
        "remain_sec": remain,
        "note": f"将删掉 {start}s ~ {end}s（约 {remove} 秒），前后拼回，约剩 {remain} 秒",
    }
    summary = (
        f"将删掉中间 {start}s ~ {end}s（约 {remove} 秒），前后拼回去。\n"
        f"预计剩余约 {remain} 秒。\n"
        f"源文件：{video.name}"
    )

    if not confirmed:
        return _pending("删除中间段", summary, plan, "cut_out")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"cutout_{start:.0f}_{end:.0f}_{_stamp()}.mp4"
    ffmpeg = get_ffmpeg()
    has_audio = bool(meta.get("has_audio"))

    # 边界：删片头 / 删片尾可退化成 trim
    if start <= 0.05:
        return trim_keep(end, total_f, path=str(video), precise=True, confirmed=True)
    if end >= total_f - 0.05:
        return trim_keep(0, start, path=str(video), precise=True, confirmed=True)

    if has_audio:
        fc = (
            f"[0:v]trim=0:{start},setpts=PTS-STARTPTS[v0];"
            f"[0:a]atrim=0:{start},asetpts=PTS-STARTPTS[a0];"
            f"[0:v]trim={end}:{total_f},setpts=PTS-STARTPTS[v1];"
            f"[0:a]atrim={end}:{total_f},asetpts=PTS-STARTPTS[a1];"
            f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
        )
        cmd = [
            ffmpeg, "-y", "-i", str(video),
            "-filter_complex", fc,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
            str(out),
        ]
    else:
        fc = (
            f"[0:v]trim=0:{start},setpts=PTS-STARTPTS[v0];"
            f"[0:v]trim={end}:{total_f},setpts=PTS-STARTPTS[v1];"
            f"[v0][v1]concat=n=2:v=1:a=0[v]"
        )
        cmd = [
            ffmpeg, "-y", "-i", str(video),
            "-filter_complex", fc,
            "-map", "[v]",
            "-c:v", "libx264", "-movflags", "+faststart",
            str(out),
        ]

    proc = _run(cmd)
    if not _encode_ok(out, proc):
        err = (proc.stderr or "")[-900:]
        return f"FFmpeg 删除中间段失败：\n{err}"

    _set_working_video(out)
    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    _save_job(result)
    return (
        "中间段已删除并拼回。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint(
            "打开看看效果",
            "截一张预览图确认画面",
            "继续加标题或字幕",
        )
    )


def concat_videos(clips: object, confirmed: bool = False) -> str:
    """按顺序拼接多段视频，导出到 output/。"""
    try:
        paths = _parse_clip_list(clips)
    except FileNotFoundError as e:
        return str(e)

    if len(paths) < 2:
        return "错误：至少需要 2 个视频才能拼接。可传文件名列表或逗号分隔路径。"

    names = [p.name for p in paths]
    plan = {
        "action": "concat_videos",
        "clips": [str(p) for p in paths],
        "count": len(paths),
        "note": f"将按顺序拼接 {len(paths)} 段：{' → '.join(names)}",
    }
    summary = (
        f"将按顺序拼接 {len(paths)} 段视频：\n"
        + "\n".join(f"  {i}. {n}" for i, n in enumerate(names, 1))
    )

    if not confirmed:
        return _pending("多段拼接", summary, plan, "concat_videos")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"concat_{len(paths)}_{_stamp()}.mp4"
    ffmpeg = get_ffmpeg()

    # concat demuxer + 重编码：不同来源更稳
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
        dir=str(ROOT / "data"),
    ) as tf:
        for p in paths:
            # 正斜杠 + 单引号转义，Windows 下 concat demuxer 更稳
            escaped = str(p.resolve()).replace("\\", "/").replace("'", r"'\''")
            tf.write(f"file '{escaped}'\n")
        list_path = tf.name

    try:
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", "-c:a", "aac",
            "-movflags", "+faststart",
            str(out),
        ]
        proc = _run(cmd)
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass

    if not _encode_ok(out, proc):
        err = (proc.stderr or "")[-900:]
        return f"FFmpeg 拼接失败：\n{err}"

    _set_working_video(out)
    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    _save_job(result)
    return (
        "拼接完成。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint("打开刚拼好的视频", "给成片加标题", "列出全部成片")
    )


def mute_audio(path: str | None = None, confirmed: bool = False) -> str:
    """去掉音轨，保留画面。"""
    try:
        video = _resolve_source(path, prefer_latest_output=True)
    except FileNotFoundError as e:
        return str(e)

    meta = _video_meta(video)
    if not meta.get("has_audio"):
        return f"这个视频本身没有音轨，无需静音：{video}"

    plan = {
        "action": "mute_audio",
        "input": str(video),
        "note": "将去掉全部声音，只保留画面",
    }
    summary = f"将去掉声音，只保留画面。\n源文件：{video.name}"

    if not confirmed:
        return _pending("静音导出", summary, plan, "mute_audio")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"mute_{_stamp()}.mp4"
    ffmpeg = get_ffmpeg()
    cmd = [ffmpeg, "-y", "-i", str(video), "-c:v", "copy", "-an", str(out)]
    proc = _run(cmd)
    if not _encode_ok(out, proc):
        cmd_re = [
            ffmpeg, "-y", "-i", str(video),
            "-c:v", "libx264", "-an", "-movflags", "+faststart", str(out),
        ]
        proc2 = _run(cmd_re)
        if not _encode_ok(out, proc2):
            err = (proc2.stderr or proc.stderr or "")[-800:]
            return f"FFmpeg 静音失败：\n{err}"

    _set_working_video(out)
    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    _save_job(result)
    return (
        "已导出无声版本。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint("打开听听（确认没声音）", "继续加字幕或标题")
    )


def change_speed(
    factor: float,
    path: str | None = None,
    confirmed: bool = False,
) -> str:
    """改变播放速度，factor 支持 0.5～2.0（如 2=两倍速，0.5=慢放）。"""
    try:
        video = _resolve_source(path, prefer_latest_output=True)
    except FileNotFoundError as e:
        return str(e)

    try:
        speed = float(factor)
    except (TypeError, ValueError):
        return "错误：factor 必须是数字，例如 2（两倍速）或 0.5（慢放）。"
    if speed < 0.5 or speed > 2.0:
        return "错误：factor 目前只支持 0.5～2.0（FFmpeg atempo 限制）。"

    meta = _video_meta(video)
    total = meta.get("duration_sec")
    new_dur = round(float(total) / speed, 3) if total is not None else None
    label = f"{speed:g}x"
    plan = {
        "action": "change_speed",
        "input": str(video),
        "factor": speed,
        "new_duration_sec": new_dur,
        "note": f"将以 {label} 速度导出"
        + (f"，约 {new_dur} 秒" if new_dur is not None else ""),
    }
    summary = (
        f"将按 {label} 变速导出"
        + (f"（约变成 {new_dur} 秒）" if new_dur is not None else "")
        + f"。\n源文件：{video.name}"
    )

    if not confirmed:
        return _pending("变速导出", summary, plan, "change_speed")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = str(speed).replace(".", "p")
    out = OUTPUT_DIR / f"speed_{tag}x_{_stamp()}.mp4"
    ffmpeg = get_ffmpeg()
    has_audio = bool(meta.get("has_audio"))
    # setpts: 画面加速；atempo: 声音同步（0.5~2.0）
    v_filter = f"setpts=PTS/{speed}"

    if has_audio:
        fc = f"[0:v]{v_filter}[v];[0:a]atempo={speed}[a]"
        cmd = [
            ffmpeg, "-y", "-i", str(video),
            "-filter_complex", fc,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
            str(out),
        ]
    else:
        cmd = [
            ffmpeg, "-y", "-i", str(video),
            "-vf", v_filter,
            "-c:v", "libx264", "-movflags", "+faststart",
            str(out),
        ]

    proc = _run(cmd)
    if not _encode_ok(out, proc):
        err = (proc.stderr or "")[-900:]
        return f"FFmpeg 变速失败：\n{err}"

    _set_working_video(out)
    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    _save_job(result)
    return (
        f"已按 {label} 导出。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint("打开看看节奏", "觉得太快/太慢可以再说一个倍率")
    )


def export_preview_frame(
    at_sec: float = 0,
    path: str | None = None,
    open_after: bool = True,
) -> str:
    """截取某一秒的 PNG 预览图，方便确认画面/字幕位置。无需 confirmed。"""
    try:
        video = _resolve_source(path, prefer_latest_output=True)
    except FileNotFoundError as e:
        return str(e)

    try:
        t = float(at_sec)
    except (TypeError, ValueError):
        return "错误：at_sec 必须是数字（秒）。"
    if t < 0:
        return "错误：at_sec 不能为负。"

    meta = _video_meta(video)
    total = meta.get("duration_sec")
    if total is not None and t >= float(total):
        t = max(0.0, float(total) - 0.05)

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = PREVIEW_DIR / f"preview_{t:.1f}s_{_stamp()}.png"
    ffmpeg = get_ffmpeg()
    cmd = [
        ffmpeg, "-y",
        "-ss", str(t),
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "2",
        str(out),
    ]
    proc = _run(cmd)
    if not _encode_ok(out, proc):
        err = (proc.stderr or "")[-800:]
        return f"FFmpeg 截帧失败：\n{err}"

    msg = (
        f"预览图已保存（约第 {t} 秒）：\n{out.resolve()}\n"
        f"源视频：{video}"
    )
    if open_after:
        msg += "\n" + _open_path(out)
    return msg + _hint(
        "字不对可以说「字号改成 40」或「换到底部」再加一版",
        "打开整段视频再看一遍",
    )


def list_outputs() -> str:
    """列出 output/ 目录里已经导出的成片。"""
    files = _list_output_files()
    working = _get_working_video()
    header = ""
    if working is not None:
        header = f"当前工作视频：{working}\n\n"

    if not files:
        return header + "output/ 里还没有导出的视频。先试着「去掉前 5 秒」做一条成片吧。"

    rows = []
    for i, p in enumerate(files, 1):
        mb = round(p.stat().st_size / (1024 * 1024), 2)
        mark = " ← 最新" if i == 1 else ""
        rows.append(f"{i}. {p.name}  ({mb} MB){mark}\n   路径: {p.resolve()}")
    return (
        header
        + "已导出成片：\n"
        + "\n".join(rows)
        + _hint(
            "打开最新成片 / 打开某一个文件名",
            "把其中几段拼起来",
            "截一张预览图 / 加文字贴纸",
        )
    )


def delete_output(name_or_path: str, confirmed: bool = False) -> str:
    """删除 output/ 里的某个已导出视频（不会删除 samples/ 或用户原片）。"""
    text = (name_or_path or "").strip().strip('"')
    if not text:
        return "错误：请提供要删除的文件名或路径。可先 list_outputs。"

    try:
        candidate = _resolve_output(text)
    except FileNotFoundError as e:
        return str(e)

    plan = {"action": "delete_output", "file": str(candidate)}
    summary = f"将删除导出成片：{candidate.name}\n（不会动你的原片）"
    if not confirmed:
        return _pending("删除成片", summary, plan, "delete_output")

    candidate.unlink()
    return f"已删除：{candidate}" + _hint("列出剩下的成片", "继续切片或加文字做新成片")


def open_output(name_or_path: str | None = None) -> str:
    """用系统默认播放器打开 output/ 里的成片；省略则打开最新一条。"""
    text = (name_or_path or "").strip().strip('"')
    # 也允许打开预览图
    if text and text.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = PREVIEW_DIR / candidate.name
            if not candidate.exists():
                candidate = OUTPUT_DIR / Path(text).name
        candidate = candidate.resolve()
        if not candidate.exists():
            return f"找不到预览图：{text}"
        return _open_path(candidate) + _hint("继续改文字或切片", "列出全部成片")

    try:
        target = _resolve_output(name_or_path)
    except FileNotFoundError as e:
        return str(e)

    msg = _open_path(target)
    return msg + _hint(
        "不满意可以再说怎么改（再切一段 / 换文字 / 变速）",
        "截一张预览图看看某一帧",
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
    """在视频上叠加一行文字（标题 / 字幕 / 角标贴纸），导出到 output/。"""
    raw = (text or "").strip()
    if not raw:
        return "错误：文字不能为空。例如「决赛高光」或「感谢观看」。"
    if len(raw) > 40:
        return "错误：单行文字请控制在 40 字以内，太长画面会挤在一起。"

    style_key = (style or "title").strip().lower()
    if style_key not in _STYLE_PRESETS:
        return f"错误：style 只能是 {', '.join(_STYLE_PRESETS)}，收到：{style_key}"

    preset = _STYLE_PRESETS[style_key]
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
    if not re.fullmatch(r"[#A-Za-z0-9_]+", color):
        return "错误：fontcolor 请用 white / yellow / #FFFFFF 这类简单颜色名。"

    try:
        video = _resolve_source(path, prefer_latest_output=True)
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
    summary = (
        f"将以「{preset['label']}」在 {pos_key} 叠加「{raw}」"
        f"（字号 {size}，{color}，{time_note}）。\n"
        f"源文件：{video.name}"
    )

    if not confirmed:
        return _pending("文字贴纸", summary, plan, "add_text_overlay")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"text_{style_key}_{_stamp()}.mp4"

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
        ffmpeg, "-y", "-i", str(video),
        "-vf", vf,
        "-c:v", "libx264", "-c:a", "copy", "-movflags", "+faststart",
        str(out),
    ]
    proc = _run(cmd)
    if not _encode_ok(out, proc):
        cmd_re = [
            ffmpeg, "-y", "-i", str(video),
            "-vf", vf,
            "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
            str(out),
        ]
        proc2 = _run(cmd_re)
        if not _encode_ok(out, proc2):
            err = (proc2.stderr or proc.stderr or "")[-900:]
            return f"FFmpeg 文字叠加失败：\n{err}"

    _set_working_video(out)
    result = {
        **plan,
        "output": str(out.resolve()),
        "output_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "status": "ok",
    }
    _save_job(result)
    return (
        "文字贴纸已加上。\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + _hint(
            "截第 1 秒预览图看看字在哪",
            "打开刚做好的视频",
            "字太大/太小可以说「字号改成 40」再做一版",
        )
    )


TOOL_DECLARATIONS = [
    {
        "name": "probe_video",
        "description": (
            "查看视频时长、分辨率等，并设为当前工作视频。"
            "用户给出新路径时先调用；切片/删段前也应先调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "视频完整路径；省略则用工作视频或默认样本。",
                }
            },
        },
    },
    {
        "name": "trim_keep",
        "description": (
            "只保留 [start_sec, end_sec) 并导出到 output/。"
            "去掉前 N 秒：start_sec=N，end_sec=总时长；"
            "截取中间：传入起止秒。"
            "precise=true 强制重编码更准时。"
            "先 confirmed=false，用户确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_sec": {"type": "number", "description": "保留区间起点（秒）"},
                "end_sec": {"type": "number", "description": "保留区间终点（秒）"},
                "path": {"type": "string", "description": "源视频路径；省略用工作视频"},
                "precise": {
                    "type": "boolean",
                    "description": "true=强制重编码精密切片；默认 false",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "false=预览计划；true=执行导出",
                },
            },
            "required": ["start_sec", "end_sec"],
        },
    },
    {
        "name": "cut_out",
        "description": (
            "删掉视频中间 [start_sec, end_sec)，前后拼回成新文件。"
            "用户说「去掉中间」「删掉 10 到 20 秒」「去掉中间那段」时用本工具，"
            "不要用 trim_keep。"
            "先 confirmed=false，确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_sec": {"type": "number", "description": "要删除区间起点（秒）"},
                "end_sec": {"type": "number", "description": "要删除区间终点（秒）"},
                "path": {"type": "string", "description": "源视频；省略用工作视频"},
                "confirmed": {"type": "boolean", "description": "false=预览；true=执行"},
            },
            "required": ["start_sec", "end_sec"],
        },
    },
    {
        "name": "concat_videos",
        "description": (
            "按顺序拼接多段视频。"
            "clips 传文件名列表或逗号分隔路径（可用 output/ 里的成片名）。"
            "先 confirmed=false，确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "clips": {
                    "type": "string",
                    "description": "逗号分隔的路径/文件名，或 JSON 数组字符串",
                },
                "confirmed": {"type": "boolean", "description": "false=预览；true=执行"},
            },
            "required": ["clips"],
        },
    },
    {
        "name": "mute_audio",
        "description": (
            "去掉音轨，只保留画面。默认作用最新成片或工作视频。"
            "先 confirmed=false，确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "源视频；省略优先最新成片"},
                "confirmed": {"type": "boolean", "description": "false=预览；true=执行"},
            },
        },
    },
    {
        "name": "change_speed",
        "description": (
            "改变播放速度并导出。factor：2=两倍速，0.5=慢放一半；范围 0.5～2.0。"
            "默认作用最新成片。先 confirmed=false，确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "factor": {"type": "number", "description": "速度倍率，0.5～2.0"},
                "path": {"type": "string", "description": "源视频；省略优先最新成片"},
                "confirmed": {"type": "boolean", "description": "false=预览；true=执行"},
            },
            "required": ["factor"],
        },
    },
    {
        "name": "export_preview_frame",
        "description": (
            "截取某一秒的 PNG 预览图（默认打开看图），无需确认。"
            "用户说「截一帧」「预览第 N 秒」「看看字幕位置」时调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "at_sec": {"type": "number", "description": "截取秒数，默认 0"},
                "path": {"type": "string", "description": "源视频；省略优先最新成片"},
                "open_after": {
                    "type": "boolean",
                    "description": "截完是否自动打开，默认 true",
                },
            },
        },
    },
    {
        "name": "add_text_overlay",
        "description": (
            "叠加一行文字贴纸。style=title/subtitle/sticker；"
            "可设 position、字号、颜色、出现时段。"
            "未指定源文件时优先最新成片。先 confirmed=false，确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要叠加的文字，单行≤40字"},
                "path": {"type": "string", "description": "源视频；省略优先最新成片"},
                "style": {"type": "string", "description": "title | subtitle | sticker"},
                "position": {
                    "type": "string",
                    "description": "top|center|bottom|top_left|top_right",
                },
                "fontsize": {"type": "number", "description": "字号，可选"},
                "fontcolor": {"type": "string", "description": "white/yellow/#FFFFFF"},
                "start_sec": {"type": "number", "description": "文字开始秒，可选"},
                "end_sec": {"type": "number", "description": "文字结束秒，可选"},
                "confirmed": {"type": "boolean", "description": "false=预览；true=执行"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "open_output",
        "description": (
            "用系统程序打开 output/ 成片或预览图。"
            "「打开」「播放」「看看效果」时调用；省略=最新成片。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_path": {
                    "type": "string",
                    "description": "文件名、路径、「最新」，或预览 png 名",
                },
            },
        },
    },
    {
        "name": "list_outputs",
        "description": "列出 output/ 已导出成片，并显示当前工作视频。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_output",
        "description": (
            "删除 output/ 中某个成片（不能删原片）。"
            "先 confirmed=false，确认后再 true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_path": {"type": "string", "description": "文件名或完整路径"},
                "confirmed": {"type": "boolean", "description": "false=预览；true=删除"},
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
            precise=bool(args.get("precise", False)),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "cut_out":
        return cut_out(
            start_sec=args.get("start_sec", 0),
            end_sec=args.get("end_sec", 0),
            path=args.get("path"),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "concat_videos":
        return concat_videos(
            clips=args.get("clips"),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "mute_audio":
        return mute_audio(
            path=args.get("path"),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "change_speed":
        return change_speed(
            factor=args.get("factor", 1),
            path=args.get("path"),
            confirmed=bool(args.get("confirmed", False)),
        )
    if name == "export_preview_frame":
        open_after = args.get("open_after")
        return export_preview_frame(
            at_sec=args.get("at_sec", 0) or 0,
            path=args.get("path"),
            open_after=True if open_after is None else bool(open_after),
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

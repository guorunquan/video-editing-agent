"""v2.0 editable drafts, music analysis, effects, preview and final rendering."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import uuid
import wave
from array import array
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ffmpeg_bin import get_ffmpeg

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DRAFT_DIR = DATA_DIR / "drafts"
OUTPUT_DIR = ROOT / "output"
PLAN_PREVIEW_DIR = OUTPUT_DIR / "plan_previews"
MUSIC_DIR = ROOT / "uploads" / "music"
MUSIC_CACHE_FILE = DATA_DIR / "music_analysis.json"
AUTO_MUSIC = "__auto__"
BUILTIN_ENERGY_MUSIC = "内置高燃电子_150bpm.wav"
RENDER_VERSION = 3

MUSIC_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
EFFECT_TYPES = {"fade", "crossfade", "slow_motion", "punch_zoom", "flash", "shake"}
EFFECT_DEFAULTS: dict[str, dict[str, Any]] = {
    "fade": {"duration_sec": 0.35},
    "crossfade": {"duration_sec": 0.2},
    "slow_motion": {"duration_sec": 1.2, "speed": 0.65},
    "punch_zoom": {"duration_sec": 0.4, "scale": 1.15},
    "flash": {"duration_sec": 0.12, "strength": 0.3},
    "shake": {"duration_sec": 0.25, "strength": 8},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_bytes(cmd: list[str]) -> tuple[int, bytes, str]:
    import subprocess

    proc = subprocess.run(cmd, capture_output=True)
    return proc.returncode, proc.stdout or b"", (proc.stderr or b"").decode("utf-8", "replace")


def _run_text(cmd: list[str]):
    import subprocess

    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _safe_music(name: str | None) -> Path | None:
    if not name:
        return None
    candidate = (MUSIC_DIR / Path(name).name).resolve()
    try:
        candidate.relative_to(MUSIC_DIR.resolve())
    except ValueError as exc:
        raise ValueError("配乐必须来自本地音乐库") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in MUSIC_SUFFIXES:
        raise FileNotFoundError(f"找不到配乐：{Path(name).name}")
    return candidate


def _ensure_builtin_music() -> Path:
    """Create a deterministic, royalty-free electronic loop for offline use."""
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    destination = MUSIC_DIR / BUILTIN_ENERGY_MUSIC
    if destination.is_file() and destination.stat().st_size > 100_000:
        return destination

    sample_rate = 22_050
    bpm = 150.0
    beat = 60.0 / bpm
    duration = beat * 32  # Eight bars; the renderer loops it for longer edits.
    notes = (55.0, 55.0, 65.41, 73.42, 55.0, 82.41, 73.42, 65.41)
    arpeggio = (220.0, 261.63, 329.63, 392.0, 329.63, 261.63, 246.94, 293.66)
    rng = random.Random(20_260_812)
    frames = array("h")
    for index in range(int(duration * sample_rate)):
        t = index / sample_rate
        beat_position = t % beat
        eighth = beat / 2
        eighth_position = t % eighth
        sixteenth_position = t % (beat / 4)

        kick_frequency = 48.0 + 92.0 * math.exp(-beat_position * 24.0)
        kick = math.sin(2 * math.pi * kick_frequency * beat_position) * math.exp(-beat_position * 11.5)

        beat_index = int(t / beat) % 4
        snare = 0.0
        if beat_index in (1, 3):
            snare = rng.uniform(-1.0, 1.0) * math.exp(-beat_position * 18.0)
        hat = rng.uniform(-1.0, 1.0) * math.exp(-sixteenth_position * 70.0)

        bass_frequency = notes[int(t / eighth) % len(notes)]
        bass_phase = (t * bass_frequency) % 1.0
        bass = (2.0 * bass_phase - 1.0) * min(1.0, eighth_position * 40.0) * math.exp(-eighth_position * 1.8)

        lead_frequency = arpeggio[int(t / (beat / 4)) % len(arpeggio)]
        lead_envelope = math.exp(-sixteenth_position * 9.0)
        lead = (math.sin(2 * math.pi * lead_frequency * t) + 0.35 * math.sin(4 * math.pi * lead_frequency * t)) * lead_envelope

        sidechain = 0.42 + 0.58 * min(1.0, beat_position / 0.14)
        sample = 0.54 * kick + 0.19 * snare + 0.055 * hat + sidechain * (0.20 * bass + 0.095 * lead)
        value = max(-1.0, min(1.0, sample))
        left = int(value * 24_000)
        right = int(max(-1.0, min(1.0, value + lead * 0.025)) * 24_000)
        frames.extend((left, right))

    temporary = destination.with_suffix(".tmp.wav")
    with wave.open(str(temporary), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames.tobytes())
    temporary.replace(destination)
    return destination


def _audio_duration(path: Path) -> float | None:
    proc = _run_text([get_ffmpeg(), "-hide_banner", "-i", str(path)])
    import re

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr or "")
    if not match:
        return None
    return round(int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)), 3)


def analyze_music(path: Path) -> dict[str, Any]:
    """Estimate tempo and a stable beat grid using only FFmpeg + stdlib.

    This is deliberately a lightweight beat tracker: it is suitable for snapping
    cuts by a few frames, not for restructuring a whole song.
    """
    path = path.resolve()
    stat = path.stat()
    key = f"{path}:{stat.st_size}:{stat.st_mtime_ns}"
    cache = _read_json(MUSIC_CACHE_FILE, {})
    if path.name == BUILTIN_ENERGY_MUSIC:
        duration = _audio_duration(path)
        interval = 60.0 / 150.0
        result = {
            "status": "ok",
            "bpm": 150.0,
            "beat_times": [round(index * interval, 3) for index in range(int((duration or 0) / interval) + 1)],
            "duration_sec": duration,
            "analyzer": "builtin_grid_v1",
        }
        cache = cache if isinstance(cache, dict) else {}
        if cache.get(key) != result:
            cache[key] = result
            _write_json(MUSIC_CACHE_FILE, cache)
        return result
    if isinstance(cache, dict) and key in cache:
        return cache[key]

    sample_rate = 11025
    code, raw, error = _run_bytes([
        get_ffmpeg(), "-v", "error", "-i", str(path), "-t", "600",
        "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ])
    if code != 0 or len(raw) < sample_rate:
        result = {"status": "unavailable", "bpm": None, "beat_times": [], "message": error[-300:]}
    else:
        samples = array("h")
        samples.frombytes(raw)
        if os.sys.byteorder != "little":
            samples.byteswap()
        hop = 512
        energies: list[float] = []
        for start in range(0, len(samples) - hop, hop):
            window = samples[start:start + hop]
            energies.append(math.sqrt(sum(value * value for value in window) / len(window)))
        onsets = [0.0]
        for current, previous in zip(energies[1:], energies[:-1]):
            onsets.append(max(0.0, current - previous))
        if not onsets or max(onsets) <= 0:
            bpm, beat_times = None, []
        else:
            mean = sum(onsets) / len(onsets)
            centered = [max(0.0, value - mean) for value in onsets]
            best_bpm, best_score, best_lag = 120.0, -1.0, 0
            for bpm_candidate in range(80, 181):
                lag = max(1, round((60.0 / bpm_candidate) * sample_rate / hop))
                score = sum(centered[index] * centered[index - lag] for index in range(lag, len(centered)))
                if score > best_score:
                    best_bpm, best_score, best_lag = float(bpm_candidate), score, lag
            phase_scores = [sum(centered[index] for index in range(phase, len(centered), best_lag)) for phase in range(best_lag)]
            phase = max(range(len(phase_scores)), key=phase_scores.__getitem__)
            duration = len(samples) / sample_rate
            interval = 60.0 / best_bpm
            first = phase * hop / sample_rate
            beat_times = [round(first + index * interval, 3) for index in range(int((duration - first) / interval) + 1)]
            bpm = round(best_bpm, 1)
        result = {
            "status": "ok" if beat_times else "unavailable",
            "bpm": bpm,
            "beat_times": beat_times[:2000],
            "duration_sec": _audio_duration(path),
            "analyzer": "stdlib_energy_v1",
        }
    cache = cache if isinstance(cache, dict) else {}
    cache[key] = result
    _write_json(MUSIC_CACHE_FILE, cache)
    return result


def list_music() -> list[dict[str, Any]]:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_builtin_music()
    rows = []
    for path in sorted(MUSIC_DIR.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in MUSIC_SUFFIXES:
            continue
        analysis = analyze_music(path)
        rows.append({
            "name": path.name,
            "path": str(path.resolve()),
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            "bpm": analysis.get("bpm"),
            "duration_sec": analysis.get("duration_sec"),
            "builtin": path.name == BUILTIN_ENERGY_MUSIC,
        })
    return rows


def _automatic_music(plan: dict[str, Any]) -> Path | None:
    library = list_music()
    if not library:
        return None
    package = plan.get("package") if isinstance(plan.get("package"), dict) else {}
    mood = str(package.get("music_mood") or package.get("mood") or "与内容匹配")
    high_energy = any(word in mood for word in ("高燃", "电子", "热血", "激烈")) or plan.get("strategy") == "retention_short"
    target_bpm = 150.0 if high_energy else 120.0

    def score(row: dict[str, Any]) -> float:
        name = str(row.get("name") or "").lower()
        bpm = float(row.get("bpm") or target_bpm)
        name_bonus = 80.0 if high_energy and any(word in name for word in ("高燃", "energy", "edm", "electronic")) else 0.0
        builtin_bonus = 15.0 if high_energy and row.get("builtin") else 0.0
        return name_bonus + builtin_bonus - abs(bpm - target_bpm)

    chosen = max(library, key=score)
    return _safe_music(str(chosen["name"]))


def _normalise_effects(effects: Any, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_start = min(float(item["start_sec"]) for item in segments)
    source_end = max(float(item["end_sec"]) for item in segments)
    rows: list[dict[str, Any]] = []
    for raw in effects if isinstance(effects, list) else []:
        if not isinstance(raw, dict):
            continue
        effect_type = str(raw.get("type") or "").strip().lower()
        if effect_type not in EFFECT_TYPES:
            continue
        defaults = EFFECT_DEFAULTS[effect_type]
        at = float(raw.get("start_sec", source_start))
        duration = max(0.05, min(float(raw.get("duration_sec", defaults["duration_sec"])), 3.0))
        if at > source_end or at + duration < source_start:
            continue
        row = {**defaults, **raw, "type": effect_type, "start_sec": round(max(source_start, at), 3), "duration_sec": round(duration, 3)}
        if effect_type == "slow_motion":
            row["speed"] = max(0.5, min(float(row.get("speed", 0.65)), 0.9))
        if effect_type == "punch_zoom":
            row["scale"] = max(1.05, min(float(row.get("scale", 1.15)), 1.35))
        rows.append(row)
    return rows[:20]


def create_draft(
    source: str | Path,
    plan: dict[str, Any],
    *,
    music_name: str | None = AUTO_MUSIC,
    music_volume: float | None = None,
    beat_sync: bool | None = None,
    enabled_effects: list[str] | None = None,
) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到源视频：{source_path}")
    segments = deepcopy(plan.get("segments") or [])
    if not segments:
        raise ValueError("方案没有可渲染片段")
    effects = _normalise_effects(plan.get("effects"), segments)
    if enabled_effects is not None:
        allow = set(enabled_effects)
        effects = [effect for effect in effects if effect["type"] in allow]
        existing_types = {effect["type"] for effect in effects}
        first_start = float(segments[0]["start_sec"])
        first_end = float(segments[0]["end_sec"])
        seed_offsets = {"fade": 0.0, "punch_zoom": 0.2, "flash": 0.65, "shake": 0.9, "slow_motion": 1.1}
        for effect_type in allow - existing_types - {"crossfade"}:
            if effect_type not in EFFECT_DEFAULTS:
                continue
            start = min(first_start + seed_offsets.get(effect_type, 0.0), max(first_start, first_end - 0.1))
            effects.append({
                "type": effect_type,
                "start_sec": round(start, 3),
                **EFFECT_DEFAULTS[effect_type],
                "reason": "用户在预览设置中启用",
            })
    package = plan.get("package") if isinstance(plan.get("package"), dict) else {}
    music_path = _automatic_music(plan) if music_name in (None, AUTO_MUSIC) else _safe_music(music_name)
    resolved_volume = float(package.get("music_volume", 0.18) if music_volume is None else music_volume)
    music_mood = str(package.get("music_mood") or package.get("mood") or "与内容匹配")
    if any(word in music_mood for word in ("高燃", "电子", "热血", "激烈")):
        resolved_volume = max(0.38, resolved_volume)
    resolved_beat_sync = bool(package.get("beat_sync", True) if beat_sync is None else beat_sync)
    music_analysis = analyze_music(music_path) if music_path else None
    draft_id = "draft-" + uuid.uuid4().hex[:12]
    draft = {
        "schema_version": 1,
        "id": draft_id,
        "version": 1,
        "status": "draft",
        "created_at": _now_iso(),
        "source": str(source_path),
        "plan_id": str(plan.get("id") or "manual-plan"),
        "title": str(plan.get("title") or "AI 剪辑草案")[:120],
        "strategy": plan.get("strategy"),
        "music_mood": music_mood,
        "segments": segments,
        "effects": effects,
        "transition": deepcopy(plan.get("transition") or {"type": "crossfade", "duration_sec": 0.2}),
        "music": {
            "name": music_path.name if music_path else None,
            "path": str(music_path) if music_path else None,
            "volume": round(max(0.0, min(resolved_volume, 1.0)), 3),
            "loop": True,
            "fade_in_sec": 0.8,
            "fade_out_sec": 1.2,
            "beat_sync": bool(resolved_beat_sync and music_path),
            "analysis": music_analysis,
        },
        "preview": None,
        "output": None,
    }
    _write_json(DRAFT_DIR / f"{draft_id}.json", draft)
    return draft


def load_draft(draft_id: str) -> dict[str, Any]:
    safe_id = Path(draft_id).name
    if safe_id != draft_id or not safe_id.startswith("draft-"):
        raise ValueError("草稿 ID 无效")
    path = DRAFT_DIR / f"{safe_id}.json"
    draft = _read_json(path, None)
    if not isinstance(draft, dict):
        raise FileNotFoundError(f"找不到草稿：{draft_id}")
    return draft


def update_draft_music(
    draft_id: str,
    *,
    music_name: str | None = AUTO_MUSIC,
    mood: str | None = None,
    volume: float | None = None,
    beat_sync: bool = True,
) -> dict[str, Any]:
    """Change a draft soundtrack and invalidate its rendered preview."""
    draft = load_draft(draft_id)
    if music_name in (None, AUTO_MUSIC):
        music_path = _automatic_music({
            "strategy": draft.get("strategy"),
            "package": {"music_mood": mood or draft.get("music_mood") or "与内容匹配"},
        })
    elif music_name == "":
        music_path = None
    else:
        music_path = _safe_music(music_name)
    previous = draft.get("music") or {}
    analysis = analyze_music(music_path) if music_path else None
    resolved_mood = mood or draft.get("music_mood") or "与内容匹配"
    resolved_volume = float(volume if volume is not None else previous.get("volume", 0.18))
    if any(word in str(resolved_mood) for word in ("高燃", "电子", "热血", "激烈")):
        resolved_volume = max(0.38, resolved_volume)
    draft["music"] = {
        "name": music_path.name if music_path else None,
        "path": str(music_path) if music_path else None,
        "volume": round(max(0.0, min(resolved_volume, 1.0)), 3),
        "loop": True,
        "fade_in_sec": float(previous.get("fade_in_sec", 0.8)),
        "fade_out_sec": float(previous.get("fade_out_sec", 1.2)),
        "beat_sync": bool(beat_sync and music_path),
        "analysis": analysis,
    }
    draft["music_mood"] = resolved_mood
    draft["preview"] = None
    draft["status"] = "draft"
    draft["version"] = int(draft.get("version", 1)) + 1
    _write_json(DRAFT_DIR / f"{draft_id}.json", draft)
    return draft


def _nearest_beat(value: float, beats: list[float]) -> float | None:
    if not beats:
        return None
    candidate = min(beats, key=lambda beat: abs(beat - value))
    return candidate if abs(candidate - value) <= 0.18 else None


def _beat_snapped_segments(draft: dict[str, Any]) -> list[dict[str, Any]]:
    segments = deepcopy(draft["segments"])
    music = draft.get("music") or {}
    beats = ((music.get("analysis") or {}).get("beat_times") or []) if music.get("beat_sync") else []
    cursor = 0.0
    for index, segment in enumerate(segments[:-1]):
        duration = float(segment["end_sec"]) - float(segment["start_sec"])
        cursor += duration
        target = _nearest_beat(cursor, beats)
        if target is None:
            continue
        delta = target - cursor
        new_end = float(segment["end_sec"]) + delta
        if new_end - float(segment["start_sec"]) >= 0.4:
            segment["end_sec"] = round(new_end, 3)
            cursor = target
    return segments


def _effect_filters(
    effect: dict[str, Any], segment_start: float, segment_end: float, width: int, height: int
) -> list[str]:
    at = float(effect.get("start_sec", segment_start))
    duration = float(effect.get("duration_sec", 0.2))
    local_start = max(0.0, at - segment_start)
    local_end = min(segment_end - segment_start, local_start + duration)
    if local_end <= 0 or local_start >= segment_end - segment_start:
        return []
    effect_type = effect["type"]
    if effect_type == "punch_zoom":
        scale = float(effect.get("scale", 1.15))
        return [f"crop=iw/{scale:.3f}:ih/{scale:.3f}:(iw-ow)/2:(ih-oh)/2", f"scale={width}:{height}"]
    if effect_type == "flash":
        strength = float(effect.get("strength", 0.3))
        return [f"eq=brightness={strength:.3f}:saturation=0.75"]
    if effect_type == "shake":
        strength = max(2.0, min(float(effect.get("strength", 8)), 16.0))
        margin = int(strength * 2 + 4)
        return [f"crop=iw-{margin}:ih-{margin}:({margin}/2)+{strength:.2f}*sin(70*t):({margin}/2)+{strength:.2f}*cos(83*t)", f"scale={width}:{height}"]
    return []


def _expand_slow_motion_segments(segments: list[dict[str, Any]], effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split effect windows so filters never leak into surrounding context."""
    expanded: list[dict[str, Any]] = []
    for original_index, segment in enumerate(segments):
        start, end = float(segment["start_sec"]), float(segment["end_sec"])
        applicable = [effect for effect in effects if effect.get("type") != "fade" and start <= float(effect.get("start_sec", -1)) < end]
        boundaries = {start, end}
        for effect in applicable:
            effect_start = max(start, float(effect["start_sec"]))
            effect_end = min(end, effect_start + float(effect.get("duration_sec", 0.2)))
            boundaries.update((effect_start, effect_end))
        ordered = sorted(boundaries)
        for part_start, part_end in zip(ordered, ordered[1:]):
            if part_end - part_start < 0.01:
                continue
            active = [
                effect for effect in applicable
                if float(effect["start_sec"]) <= part_start + 0.001
                and float(effect["start_sec"]) + float(effect.get("duration_sec", 0.2)) >= part_end - 0.001
            ]
            slow = next((effect for effect in active if effect["type"] == "slow_motion"), None)
            expanded.append({
                **segment,
                "start_sec": round(part_start, 3),
                "end_sec": round(part_end, 3),
                "original_index": original_index,
                "speed": float(slow.get("speed", 0.65)) if slow else 1.0,
                "active_effects": [effect for effect in active if effect["type"] != "slow_motion"],
            })
    return expanded


def _build_render_command(draft: dict[str, Any], out: Path, preview: bool) -> tuple[list[str], float]:
    source = Path(draft["source"])
    plan_segments = _beat_snapped_segments(draft)
    effects = draft.get("effects") or []
    segments = _expand_slow_motion_segments(plan_segments, effects)
    music_path = (draft.get("music") or {}).get("path")
    meta_proc = _run_text([get_ffmpeg(), "-hide_banner", "-i", str(source)])
    meta_text = meta_proc.stderr or ""
    has_audio = "Audio:" in meta_text
    import re

    size_match = re.search(r"(\d{2,5})x(\d{2,5})", meta_text)
    source_width = int(size_match.group(1)) if size_match else 1280
    source_height = int(size_match.group(2)) if size_match else 720
    # Preview is a decision artifact: visual effects and fine gameplay details
    # must remain judgeable, so retain the source resolution and quality. The
    # faster encoder preset still keeps preview turnaround below final export.
    target_width = source_width // 2 * 2
    target_height = source_height // 2 * 2
    filters: list[str] = []
    durations: list[float] = []
    for index, segment in enumerate(segments):
        start, end = float(segment["start_sec"]), float(segment["end_sec"])
        duration = end - start
        applicable = segment.get("active_effects") or []
        speed = float(segment.get("speed", 1.0))
        durations.append(duration / speed)
        vf = [f"trim={start:.3f}:{end:.3f}", "setpts=PTS-STARTPTS"]
        if speed != 1.0:
            vf.append(f"setpts=PTS/{speed:.4f}")
        for effect in applicable:
            vf.extend(_effect_filters(effect, start, end, target_width, target_height))
        vf.extend([f"scale={target_width}:{target_height}", "fps=30", "settb=AVTB", "setsar=1", "format=yuv420p"])
        filters.append(f"[0:v]{','.join(vf)}[v{index}]")
        if has_audio:
            af = [f"atrim={start:.3f}:{end:.3f}", "asetpts=PTS-STARTPTS"]
            if speed != 1.0:
                af.append(f"atempo={speed:.4f}")
            filters.append(f"[0:a]{','.join(af)}[a{index}]")

    transition = draft.get("transition") or {}
    transition_duration = max(0.0, min(float(transition.get("duration_sec", 0.2)), 0.5)) if transition.get("type") == "crossfade" else 0.0
    if len(segments) == 1:
        video_label = "v0"
        audio_label = "a0" if has_audio else None
        total_duration = durations[0]
    elif transition_duration > 0:
        video_label = "v0"
        audio_label = "a0" if has_audio else None
        cursor = durations[0]
        for index in range(1, len(segments)):
            next_video = f"vx{index}"
            is_plan_boundary = segments[index].get("original_index") != segments[index - 1].get("original_index")
            if is_plan_boundary:
                offset = max(0.01, cursor - transition_duration)
                filters.append(f"[{video_label}][v{index}]xfade=transition=fade:duration={transition_duration:.3f}:offset={offset:.3f}[{next_video}]")
            else:
                filters.append(f"[{video_label}][v{index}]concat=n=2:v=1:a=0,settb=AVTB[{next_video}]")
            video_label = next_video
            if has_audio and audio_label:
                next_audio = f"ax{index}"
                if is_plan_boundary:
                    filters.append(f"[{audio_label}][a{index}]acrossfade=d={transition_duration:.3f}[{next_audio}]")
                else:
                    filters.append(f"[{audio_label}][a{index}]concat=n=2:v=0:a=1[{next_audio}]")
                audio_label = next_audio
            cursor += durations[index] - (transition_duration if is_plan_boundary else 0.0)
        total_duration = cursor
    else:
        video_inputs = "".join(f"[v{index}]" for index in range(len(segments)))
        filters.append(f"{video_inputs}concat=n={len(segments)}:v=1:a=0[vcat]")
        video_label = "vcat"
        if has_audio:
            audio_inputs = "".join(f"[a{index}]" for index in range(len(segments)))
            filters.append(f"{audio_inputs}concat=n={len(segments)}:v=0:a=1[acat]")
            audio_label = "acat"
        else:
            audio_label = None
        total_duration = sum(durations)

    fade_effect = next((effect for effect in effects if effect["type"] == "fade"), None)
    if fade_effect:
        fade_duration = min(float(fade_effect.get("duration_sec", 0.35)), total_duration / 3)
        filters.append(f"[{video_label}]fade=t=in:st=0:d={fade_duration:.3f},fade=t=out:st={max(0,total_duration-fade_duration):.3f}:d={fade_duration:.3f}[vout]")
        video_label = "vout"

    cmd = [get_ffmpeg(), "-y", "-i", str(source)]
    if music_path:
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
        music = draft["music"]
        volume = float(music.get("volume", 0.18))
        fade_in = min(float(music.get("fade_in_sec", 0.8)), total_duration / 3)
        fade_out = min(float(music.get("fade_out_sec", 1.2)), total_duration / 3)
        filters.append(
            f"[1:a]atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS,volume={volume:.3f},"
            f"afade=t=in:st=0:d={fade_in:.3f},afade=t=out:st={max(0,total_duration-fade_out):.3f}:d={fade_out:.3f}[music]"
        )
        if audio_label:
            high_energy = any(word in str(draft.get("music_mood") or "") for word in ("高燃", "电子", "热血", "激烈"))
            original_volume = 0.58 if high_energy else 0.88
            filters.append(f"[{audio_label}]volume={original_volume:.2f}[original_ducked]")
            filters.append("[original_ducked][music]amix=inputs=2:duration=first:dropout_transition=1:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        else:
            filters.append("[music]loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
        audio_label = "aout"

    cmd += ["-filter_complex", ";".join(filters), "-map", f"[{video_label}]"]
    if audio_label:
        cmd += ["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast" if preview else "medium", "-crf", "20", "-movflags", "+faststart", "-t", f"{total_duration:.3f}", str(out)]
    return cmd, round(total_duration, 3)


def render_draft(draft_id: str, *, preview: bool) -> dict[str, Any]:
    draft = load_draft(draft_id)
    fingerprint_data = {
        "renderer_version": RENDER_VERSION,
        **{key: draft.get(key) for key in ("source", "segments", "effects", "transition", "music")},
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    if preview:
        PLAN_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        out = PLAN_PREVIEW_DIR / f"{draft_id}_{fingerprint}.mp4"
        existing = draft.get("preview") or {}
        if existing.get("fingerprint") == fingerprint and out.is_file() and out.stat().st_size > 0:
            return {**existing, "cached": True, "draft": draft}
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUTPUT_DIR / f"v2_{draft['plan_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

    cmd, duration = _build_render_command(draft, out, preview)
    proc = _run_text(cmd)
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size <= 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg {'预览' if preview else '导出'}失败：{(proc.stderr or '')[-1400:]}")
    result = {
        "path": str(out.resolve()),
        "name": out.name,
        "duration_sec": duration,
        "size_mb": round(out.stat().st_size / (1024 * 1024), 2),
        "fingerprint": fingerprint,
        "cached": False,
        "rendered_at": _now_iso(),
    }
    if preview:
        draft["preview"] = result
        draft["status"] = "previewed"
    else:
        draft["output"] = result
        draft["status"] = "confirmed"
    draft["version"] = int(draft.get("version", 1)) + 1
    _write_json(DRAFT_DIR / f"{draft_id}.json", draft)
    return {**result, "draft": draft}


def confirm_draft(draft_id: str) -> dict[str, Any]:
    draft = load_draft(draft_id)
    if not draft.get("preview"):
        raise ValueError("请先生成并观看方案预览，再确认导出")
    return render_draft(draft_id, preview=False)

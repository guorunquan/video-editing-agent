"""
Mini Video Agent Web UI（v0.5）

本地体验站：上传 → 对话剪辑 → 确认按钮 / 成片点选 / 多会话记录。
复用 agent.py / tools.py。

运行：
  .\\.venv\\Scripts\\activate
  python web_app.py
然后打开 http://127.0.0.1:7860
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import VideoAgent, load_settings
from tools import ROOT, get_media_state, safe_output_stem, set_working_video

load_dotenv()
os.environ.setdefault("WEB_MODE", "1")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

STATIC_DIR = ROOT / "static"
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "output"
SAMPLES_DIR = ROOT / "samples"
PREVIEW_DIR = OUTPUT_DIR / "previews"
DATA_DIR = ROOT / "data"
CHAT_LOG_FILE = DATA_DIR / "chat_log.json"  # 旧版扁平日志，启动时会迁移
CHAT_SESSIONS_FILE = DATA_DIR / "chat_sessions.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("WEB_MAX_UPLOAD_MB") or "100") * 1024 * 1024
MAX_SESSIONS = 40
MAX_ITEMS_PER_SESSION = 200
SESSION_GAP_SEC = 3 * 3600  # 超过 3 小时无消息 → 自动新开会话
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
MEDIA_ROOTS = (UPLOAD_DIR, OUTPUT_DIR, SAMPLES_DIR)

app = FastAPI(title="Mini Video Agent", version="0.5.1")

_agent: VideoAgent | None = None
_chat_lock = False
_job_state: dict[str, dict] = {}
_sessions: dict = {"active_id": "", "sessions": []}


def _now() -> float:
    return time.time()


def _session_title_from_text(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return "新对话"
    return raw[:28] + ("…" if len(raw) > 28 else "")


def _find_session(session_id: str) -> dict | None:
    for s in _sessions.get("sessions", []):
        if s.get("id") == session_id:
            return s
    return None


def _active_session() -> dict | None:
    return _find_session(_sessions.get("active_id") or "")


def _new_session(title: str = "新对话") -> dict:
    sid = uuid.uuid4().hex[:12]
    ts = _now()
    session = {
        "id": sid,
        "title": title or "新对话",
        "created_at": ts,
        "updated_at": ts,
        "items": [],
    }
    _sessions.setdefault("sessions", []).insert(0, session)
    _sessions["active_id"] = sid
    # 裁剪会话数量
    if len(_sessions["sessions"]) > MAX_SESSIONS:
        _sessions["sessions"] = _sessions["sessions"][:MAX_SESSIONS]
    return session


def _save_sessions() -> None:
    CHAT_SESSIONS_FILE.write_text(
        json.dumps(_sessions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _migrate_legacy_log() -> None:
    """把旧 chat_log.json 收成一条历史会话。"""
    if not CHAT_LOG_FILE.exists():
        return
    try:
        data = json.loads(CHAT_LOG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, list) or not data:
        return
    first_user = next((x for x in data if x.get("role") == "user"), None)
    title = _session_title_from_text((first_user or {}).get("text") or "历史对话")
    created = float(data[0].get("ts") or _now())
    updated = float(data[-1].get("ts") or created)
    session = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "created_at": created,
        "updated_at": updated,
        "items": data[-MAX_ITEMS_PER_SESSION:],
    }
    _sessions["sessions"] = [session]
    _sessions["active_id"] = session["id"]
    _save_sessions()
    try:
        CHAT_LOG_FILE.rename(DATA_DIR / "chat_log.migrated.json")
    except OSError:
        pass


def _load_sessions() -> None:
    global _sessions
    if CHAT_SESSIONS_FILE.exists():
        try:
            data = json.loads(CHAT_SESSIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sessions"), list):
                _sessions = data
                if not _sessions.get("active_id") and _sessions["sessions"]:
                    _sessions["active_id"] = _sessions["sessions"][0]["id"]
                return
        except (OSError, json.JSONDecodeError):
            pass
    _sessions = {"active_id": "", "sessions": []}
    _migrate_legacy_log()
    if not _sessions["sessions"]:
        _new_session("新对话")
        _save_sessions()


def _ensure_active_for_append() -> dict:
    """按时间间隔自动开新会话。"""
    active = _active_session()
    if active is None:
        return _new_session("新对话")
    items = active.get("items") or []
    if items:
        last_ts = float(items[-1].get("ts") or active.get("updated_at") or 0)
        if _now() - last_ts >= SESSION_GAP_SEC:
            return _new_session("新对话")
    return active


def _append_chat(role: str, text: str) -> dict:
    session = _ensure_active_for_append()
    item = {
        "id": uuid.uuid4().hex[:12],
        "role": role,
        "text": text,
        "ts": _now(),
    }
    session.setdefault("items", []).append(item)
    if len(session["items"]) > MAX_ITEMS_PER_SESSION:
        session["items"] = session["items"][-MAX_ITEMS_PER_SESSION:]
    session["updated_at"] = item["ts"]
    if role == "user" and (session.get("title") in {"", "新对话"}):
        session["title"] = _session_title_from_text(text)
    # 把活跃会话挪到最前
    sid = session["id"]
    others = [s for s in _sessions["sessions"] if s.get("id") != sid]
    _sessions["sessions"] = [session, *others]
    _sessions["active_id"] = sid
    _save_sessions()
    return item


def _start_new_session(title: str = "新对话") -> dict:
    session = _new_session(title)
    _save_sessions()
    return session


def _session_summaries() -> list[dict]:
    rows = []
    for s in _sessions.get("sessions", []):
        items = s.get("items") or []
        rows.append(
            {
                "id": s.get("id"),
                "title": s.get("title") or "新对话",
                "created_at": s.get("created_at"),
                "updated_at": s.get("updated_at"),
                "count": len(items),
                "preview": next(
                    (
                        x.get("text", "")[:40]
                        for x in items
                        if x.get("role") == "user"
                    ),
                    "",
                ),
            }
        )
    rows.sort(key=lambda x: float(x.get("updated_at") or 0), reverse=True)
    return rows


def _group_sessions_by_day(summaries: list[dict]) -> list[dict]:
    groups: dict[str, list] = {}
    order: list[str] = []
    for s in summaries:
        ts = float(s.get("updated_at") or s.get("created_at") or 0)
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "未知日期"
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append(s)
    return [{"date": day, "sessions": groups[day]} for day in order]


def _needs_confirm(reply: str, agent: VideoAgent | None = None) -> bool:
    if agent is not None and getattr(agent, "last_needs_confirm", False):
        return True
    text = reply or ""
    if "【待确认】" in text:
        return True
    return any(
        key in text
        for key in ("待确认", "请确认", "确认后", "回复「确认」", "回复\"确认\"")
    )


def _strip_machine_markers(text: str) -> str:
    """不把给 Agent 解析用的确认 marker 展示给用户。"""
    return re.sub(r"__VIDEO_AGENT_PENDING__\{[^\n]*\}\n?", "", text or "").strip()


def _friendly_error(exc: BaseException) -> str:
    msg = str(exc)
    name = type(exc).__name__
    if (
        "10060" in msg
        or "10061" in msg
        or "ConnectTimeout" in name
        or "ConnectError" in name
        or "Connection" in name
    ):
        return (
            "连不上 Gemini（连接超时）。浏览器开了 VPN 有时帮不到 Python。\n"
            "请任选其一：VPN 开「系统代理 / TUN 模式」；或在 .env 设置\n"
            "  HTTPS_PROXY=http://127.0.0.1:7890\n"
            "（端口改成你的 Clash/V2Ray 本地端口），保存后重启 web_app。"
        )
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return (
            "Gemini 额度用尽或请求太频繁（429）。"
            "请改 .env 的 GEMINI_MODEL（如 gemini-flash-lite-latest）后重启。"
        )
    if "503" in msg or "UNAVAILABLE" in msg or "high demand" in msg.lower():
        return "模型暂时繁忙（503）。请等 1～2 分钟再试，或换 lite 模型后重启。"
    if "Timeout" in name or "timeout" in msg.lower():
        return "请求超时。请检查 VPN / HTTPS_PROXY 后重试。"
    return f"{name}: {msg[:400]}"


def _get_agent() -> VideoAgent:
    global _agent
    if _agent is None:
        api_key, model = load_settings()
        _agent = VideoAgent(api_key=api_key, model=model)
    return _agent


def _safe_stem(name: str) -> str:
    return safe_output_stem(name)


def _path_under_allowed(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    for root in MEDIA_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            if resolved.is_file():
                return resolved
        except ValueError:
            continue
    raise HTTPException(status_code=403, detail="不允许访问该路径")


def _output_file(name: str) -> Path:
    text = (name or "").strip().strip('"')
    if not text:
        raise HTTPException(status_code=400, detail="请提供文件名")
    candidate = (OUTPUT_DIR / Path(text).name).resolve()
    try:
        candidate.relative_to(OUTPUT_DIR.resolve())
    except ValueError as e:
        raise HTTPException(status_code=403, detail="只能操作 output/ 内文件") from e
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"找不到成片：{candidate.name}")
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="不是支持的视频文件")
    return candidate


def _to_media_url(path: str | Path | None) -> str | None:
    if not path:
        return None
    try:
        target = _path_under_allowed(Path(path))
    except HTTPException:
        return None
    rel = target.relative_to(ROOT.resolve())
    stamp = int(target.stat().st_mtime)
    return f"/media/{rel.as_posix()}?t={stamp}"


def _enrich_state() -> dict:
    state = get_media_state()
    working = state.get("working_video")
    latest = state.get("latest_output")
    preview = state.get("latest_preview")
    return {
        "working_video": (
            {**working, "url": _to_media_url(working["path"])} if working else None
        ),
        "latest_output": (
            {**latest, "url": _to_media_url(latest["path"])} if latest else None
        ),
        "latest_preview": (
            {**preview, "url": _to_media_url(preview["path"])} if preview else None
        ),
        "play_url": _to_media_url(state.get("play_path")),
        "output_dir": state.get("output_dir") or str(OUTPUT_DIR.resolve()),
        "outputs": [
            {**item, "url": _to_media_url(item["path"])} for item in state.get("outputs", [])
        ],
        "previews": [
            {**item, "url": _to_media_url(item["path"])}
            for item in state.get("previews", [])
        ],
    }


def _history_payload(session_id: str | None = None) -> dict:
    sid = session_id or _sessions.get("active_id")
    session = _find_session(sid or "") if sid else None
    summaries = _session_summaries()
    return {
        "active_id": _sessions.get("active_id"),
        "sessions": summaries,
        "groups": _group_sessions_by_day(summaries),
        "items": list(session.get("items") or []) if session else [],
        "session": (
            {
                "id": session.get("id"),
                "title": session.get("title"),
                "created_at": session.get("created_at"),
                "updated_at": session.get("updated_at"),
                "count": len(session.get("items") or []),
            }
            if session
            else None
        ),
        "count": len(session.get("items") or []) if session else 0,
    }


def _reveal_in_explorer(path: Path) -> str:
    path = path.resolve()
    system = platform.system()
    try:
        if system == "Windows":
            if path.is_file():
                subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603
            else:
                os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "Darwin":
            if path.is_file():
                subprocess.Popen(["open", "-R", str(path)])  # noqa: S603
            else:
                subprocess.Popen(["open", str(path)])  # noqa: S603
        else:
            folder = path if path.is_dir() else path.parent
            subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"无法打开文件夹：{e}") from e
    return str(path)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class RenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    new_name: str = Field(..., min_length=1, max_length=200)


class RevealRequest(BaseModel):
    name: str | None = None


class HistorySelectRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)


def _job_update(job_id: str, **values: object) -> dict:
    job = _job_state.setdefault(job_id, {"id": job_id})
    job.update(values)
    job["updated_at"] = time.time()
    return job


_load_sessions()


@app.get("/api/health")
def health() -> dict:
    model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    return {"ok": True, "version": "1.0.0", "model": model, "web_mode": True}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = _job_state.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到处理任务")
    return job


@app.get("/api/state")
def api_state() -> dict:
    return _enrich_state()


@app.get("/api/history")
def api_history(session_id: str | None = None) -> dict:
    return _history_payload(session_id)


@app.post("/api/history/new")
def api_history_new() -> dict:
    """开新对话会话（旧会话保留，可在目录里回看）。"""
    agent = _get_agent()
    agent.history.clear()
    session = _start_new_session("新对话")
    note = "已开始新对话（历史会话仍可在「对话记录」里查看）"
    _append_chat("system", note)
    return {"ok": True, "message": note, "history": _history_payload(session["id"])}


@app.post("/api/history/select")
def api_history_select(body: HistorySelectRequest) -> dict:
    session = _find_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="找不到该会话")
    _sessions["active_id"] = session["id"]
    _save_sessions()
    return {"ok": True, "history": _history_payload(session["id"])}


@app.post("/api/outputs/rename")
def api_rename_output(body: RenameRequest) -> dict:
    src = _output_file(body.name)
    new_raw = (body.new_name or "").strip().strip('"')
    if not new_raw:
        raise HTTPException(status_code=400, detail="新文件名不能为空")
    # 保留小数点文件名（如 1.5倍速），后缀沿用原成片
    stem = _safe_stem(new_raw)
    new_name = f"{stem}{src.suffix.lower()}"
    dest = (OUTPUT_DIR / new_name).resolve()
    try:
        dest.relative_to(OUTPUT_DIR.resolve())
    except ValueError as e:
        raise HTTPException(status_code=403, detail="只能重命名到 output/ 内") from e
    if dest.exists() and dest != src:
        raise HTTPException(status_code=400, detail=f"已存在同名文件：{dest.name}")
    if dest != src:
        src.rename(dest)
    # 若工作视频就是它，同步更新
    try:
        set_working_video(dest)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "message": f"已重命名：{src.name} → {dest.name}",
        "old_name": src.name,
        "new_name": dest.name,
        "path": str(dest),
        "state": _enrich_state(),
    }


@app.post("/api/outputs/reveal")
def api_reveal_output(body: RevealRequest) -> dict:
    if body.name:
        target = _output_file(body.name)
    else:
        target = OUTPUT_DIR.resolve()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    shown = _reveal_in_explorer(target)
    return {
        "ok": True,
        "message": f"已在文件管理器中打开：{shown}",
        "path": shown,
        "output_dir": str(OUTPUT_DIR.resolve()),
    }


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "upload.mp4"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {', '.join(sorted(ALLOWED_SUFFIXES))} 视频",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB）",
        )

    out_name = f"{_safe_stem(filename)}_{uuid.uuid4().hex[:8]}{suffix}"
    dest = UPLOAD_DIR / out_name
    dest.write_bytes(data)

    video = set_working_video(dest)
    agent = _get_agent()
    agent.history.clear()

    note = f"已上传并设为当前工作视频：{video.name}"
    _append_chat("system", note)

    return {
        "ok": True,
        "message": note,
        "path": str(video),
        "url": _to_media_url(video),
        "state": _enrich_state(),
        "history": _history_payload(),
    }


@app.post("/api/chat")
def api_chat(body: ChatRequest) -> dict:
    global _chat_lock
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    if _chat_lock:
        raise HTTPException(
            status_code=429,
            detail="上一条还在处理中，请稍等完成后再发（重复点击会堆请求）。",
        )

    job_id = uuid.uuid4().hex[:12]
    _job_update(job_id, status="running", stage="理解指令", message="正在理解你的剪辑要求")
    _append_chat("user", text)
    _chat_lock = True
    agent = _get_agent()
    try:
        _job_update(job_id, stage="调用剪辑工具", message="正在分析视频并准备剪辑")
        reply = agent.chat(text)
    except SystemExit as e:
        detail = str(e) or "请检查 .env 中的 GEMINI_API_KEY"
        _job_update(job_id, status="failed", stage="失败", message=detail)
        _append_chat("assistant", detail)
        raise HTTPException(status_code=500, detail=detail) from e
    except Exception as e:  # noqa: BLE001
        detail = _friendly_error(e)
        _job_update(job_id, status="failed", stage="失败", message=detail)
        _append_chat("assistant", detail)
        raise HTTPException(status_code=500, detail=detail) from e
    finally:
        _chat_lock = False

    if "ConnectTimeout" in reply or "10060" in reply or "10061" in reply:
        reply = _friendly_error(TimeoutError(reply))

    reply = _strip_machine_markers(reply)
    _append_chat("assistant", reply)
    confirmation = getattr(agent, "last_confirmation", None)
    _job_update(job_id, status="completed", stage="完成", message="处理完成")
    return {
        "job_id": job_id,
        "reply": reply,
        "needs_confirm": _needs_confirm(reply, agent),
        "confirmation": confirmation,
        "state": _enrich_state(),
        "history": _history_payload(),
    }


@app.get("/api/outputs/download/{name:path}")
def api_download_output(name: str):
    return FileResponse(_output_file(name), filename=Path(name).name)


@app.post("/api/reset")
def api_reset() -> dict:
    """清空当前模型上下文，并开启新会话（旧会话仍保留）。"""
    agent = _get_agent()
    agent.history.clear()
    _start_new_session("新对话")
    note = "已开启新对话（旧对话仍可在「对话记录」目录中查看；成片未删除）"
    _append_chat("system", note)
    return {
        "ok": True,
        "message": note,
        "state": _enrich_state(),
        "history": _history_payload(),
    }


@app.get("/media/{file_path:path}")
def media(file_path: str):
    target = _path_under_allowed(ROOT / file_path)
    return FileResponse(target)


@app.get("/favicon.ico")
def favicon() -> Response:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
        "<rect width='32' height='32' rx='8' fill='#0f7a6c'/>"
        "<text x='16' y='22' text-anchor='middle' font-size='14' "
        "font-family='Segoe UI,sans-serif' fill='#f3fffc'>V</text></svg>"
    )
    return Response(content=svg, media_type="image/svg+xml")


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    os.environ["WEB_MODE"] = "1"
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    host = (os.getenv("WEB_HOST") or "127.0.0.1").strip()
    port = int(os.getenv("WEB_PORT") or "7860")
    print("=" * 50)
    print("Mini Video Agent Web v0.5.1")
    print(f"open: http://{host}:{port}")
    print("多会话记录 · 成片重命名/打开文件夹 · 截帧秒数")
    print("使用说明见 USAGE.md")
    print("=" * 50)
    uvicorn.run(app, host=host, port=port, reload=False)

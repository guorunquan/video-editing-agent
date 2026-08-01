"""
Mini Video Agent Web UI（v0.4）

本地体验站：上传视频 → 对话剪辑 → 页内预览。
复用 agent.py / tools.py，不改剪辑能力本身。

运行：
  .\\.venv\\Scripts\\activate
  python web_app.py
然后打开 http://127.0.0.1:7860
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import VideoAgent, load_settings
from tools import ROOT, get_media_state, set_working_video

load_dotenv()
os.environ.setdefault("WEB_MODE", "1")

# Windows 默认 Proactor 在浏览器中断视频 Range 请求时会刷 ConnectionResetError
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

STATIC_DIR = ROOT / "static"
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "output"
SAMPLES_DIR = ROOT / "samples"
PREVIEW_DIR = OUTPUT_DIR / "previews"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("WEB_MAX_UPLOAD_MB") or "100") * 1024 * 1024
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
MEDIA_ROOTS = (UPLOAD_DIR, OUTPUT_DIR, SAMPLES_DIR)

app = FastAPI(title="Mini Video Agent", version="0.4.0")

_agent: VideoAgent | None = None


def _get_agent() -> VideoAgent:
    global _agent
    if _agent is None:
        api_key, model = load_settings()
        _agent = VideoAgent(api_key=api_key, model=model)
    return _agent


def _safe_stem(name: str) -> str:
    stem = Path(name).stem
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", stem, flags=re.UNICODE).strip("_")
    return (cleaned or "upload")[:60]


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


def _to_media_url(path: str | Path | None) -> str | None:
    if not path:
        return None
    try:
        target = _path_under_allowed(Path(path))
    except HTTPException:
        return None
    rel = target.relative_to(ROOT.resolve())
    # 带 mtime，避免浏览器缓存旧成片
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
        "outputs": [
            {**item, "url": _to_media_url(item["path"])} for item in state.get("outputs", [])
        ],
        "previews": [
            {**item, "url": _to_media_url(item["path"])}
            for item in state.get("previews", [])
        ],
    }


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


@app.get("/api/health")
def health() -> dict:
    model = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    return {"ok": True, "version": "0.4.0", "model": model, "web_mode": True}


@app.get("/api/state")
def api_state() -> dict:
    return _enrich_state()


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

    state = _enrich_state()
    return {
        "ok": True,
        "message": f"已上传并设为当前工作视频：{video.name}",
        "path": str(video),
        "url": _to_media_url(video),
        "state": state,
    }


@app.post("/api/chat")
def api_chat(body: ChatRequest) -> dict:
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    try:
        reply = _get_agent().chat(text)
    except SystemExit as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)[:500]}",
        ) from e

    return {"reply": reply, "state": _enrich_state()}


@app.post("/api/reset")
def api_reset() -> dict:
    agent = _get_agent()
    agent.history.clear()
    return {"ok": True, "message": "对话已清空（工作视频与成片保留）", "state": _enrich_state()}


@app.get("/media/{file_path:path}")
def media(file_path: str):
    target = _path_under_allowed(ROOT / file_path)
    return FileResponse(target)


@app.get("/favicon.ico")
def favicon() -> Response:
    # 简易占位，避免控制台 404 刷屏
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
    # 再设一次，确保 uvicorn 建 loop 前生效（减轻 Windows 视频 Range 噪音）
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    host = (os.getenv("WEB_HOST") or "127.0.0.1").strip()
    port = int(os.getenv("WEB_PORT") or "7860")
    print("=" * 50)
    print("Mini Video Agent Web v0.4")
    print(f"open: http://{host}:{port}")
    print("上传视频后即可对话剪辑；成片在右侧播放器预览。")
    print("使用说明见 USAGE.md")
    print("=" * 50)
    uvicorn.run(app, host=host, port=port, reload=False)

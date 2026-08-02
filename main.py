"""
迷你视频切片 Agent 入口。

运行（先开 VPN）：
  .\\.venv\\Scripts\\activate
  python main.py
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from agent import VideoAgent, load_settings


def main() -> None:
    load_dotenv()
    api_key, model = load_settings()
    agent = VideoAgent(api_key=api_key, model=model)

    default_video = Path(os.getenv("DEFAULT_VIDEO") or "samples/demo.mp4")
    if not default_video.is_absolute():
        default_video = Path(__file__).resolve().parent / default_video

    print("=" * 50)
    print("Mini Video Agent v0.5 (Gemini + FFmpeg)")
    print(f"model: {model}")
    print(f"default video: {default_video}")
    print("exists:", default_video.exists())
    print("CLI 入口；网页：python web_app.py｜用法 USAGE.md｜排障 PROBLEMS.md｜交接 HANDOFF.md")
    print("可以这样说：")
    print("  - 这个视频多长？")
    print("  - 去掉前 5 秒")
    print("  - 删掉中间 2 秒到 4 秒")
    print("  - 把这两段拼起来：a.mp4, b.mp4")
    print("  - 两倍速 / 静音")
    print("  - 加标题：决赛高光")
    print("  - 截第 1 秒看看")
    print("  - 打开刚导出的视频")
    print("  (会改文件的操作都会先给计划，你再说「确认」)")
    print("type quit to exit")
    print("=" * 50)

    while True:
        try:
            user = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break
        if not user:
            continue
        if user.lower() in {"quit", "exit", "q"}:
            print("bye")
            break
        reply = agent.chat(user)
        print(f"\n助手: {reply}")


if __name__ == "__main__":
    main()

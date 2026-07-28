"""
找到可用的 ffmpeg 可执行文件。

优先顺序：
1. 系统 PATH 里的 ffmpeg（若已 winget 安装）
2. imageio-ffmpeg 自带的静态二进制（免安装，方便练手）
"""

from __future__ import annotations

import shutil
from functools import lru_cache


@lru_cache(maxsize=1)
def get_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()

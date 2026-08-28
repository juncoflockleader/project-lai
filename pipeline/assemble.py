"""把渲染出来的帧序列拼成视频。走 ffmpeg，不走 Blender 的视频序列编辑器。

    python3 -m pipeline.assemble out/ep01/sh010 out/ep01/sh010.mp4
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from pipeline.shotspec import load_style


def assemble(frames_dir: str, output: str, style: dict | None = None) -> int:
    style = style or load_style()
    fps = style["timing"]["fps"]

    if shutil.which("ffmpeg") is None:
        print("没找到 ffmpeg。brew install ffmpeg")
        return 1
    if not os.path.isdir(frames_dir):
        print(f"没有这个目录：{frames_dir}")
        return 1

    frames = [f for f in os.listdir(frames_dir) if f.endswith(".png")]
    if not frames:
        print(f"{frames_dir} 里没有 png。先渲染。")
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        # 不做时间域降噪、不做去块，糊了就糊了
        "-preset", "veryfast",
        "-crf", "20",
        output,
    ]
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"写好了：{output}  （{len(frames)} 帧 @ {fps}fps）")
    return result.returncode


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    return assemble(argv[1], argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""校验所有分镜和画质规格。不需要 Blender。

    python3 -m pipeline.validate
    python3 -m pipeline.validate shots/ep01/sh010.yaml
"""

from __future__ import annotations

import os
import sys

from pipeline.shotspec import (
    REPO_ROOT,
    SpecError,
    find_shots,
    load_shot,
    load_style,
)


def main(argv: list[str]) -> int:
    paths = argv[1:] or find_shots()
    if not paths:
        print("shots/ 下面一个镜头都没有。")
        return 1

    try:
        style = load_style()
    except SpecError as exc:
        print(f"FAIL  画质规格: {exc}")
        return 1

    fps = style["timing"]["fps"]
    step = style["timing"]["step"]
    print(f"画质规格 OK  fps={fps} step={step} 有效帧率={fps / step:g}")
    print()

    failures = 0
    missing_assets: set[str] = set()
    total_frames = 0

    for path in paths:
        rel = os.path.relpath(path, REPO_ROOT)
        try:
            shot = load_shot(path)
        except SpecError as exc:
            print(f"FAIL  {rel}\n      {exc}")
            failures += 1
            continue
        except Exception as exc:  # YAML 本身坏了
            print(f"FAIL  {rel}\n      读不了: {exc}")
            failures += 1
            continue

        frames = shot.frame_count(fps)
        total_frames += frames
        proxied = []
        for subject in shot.subjects:
            if subject.asset and not subject.has_asset():
                missing_assets.add(subject.asset)
                proxied.append(subject.name)
            elif not subject.asset:
                proxied.append(subject.name)

        tail = f"  代理={','.join(proxied)}" if proxied else ""
        print(
            f"OK    {rel}  {shot.duration:g}s / {frames}帧  "
            f"{len(shot.subjects)}个东西 {len(shot.dialogue)}句词{tail}"
        )

    print()
    if missing_assets:
        print("以下资产还没建，这些镜头会用积木代理渲染：")
        for asset in sorted(missing_assets):
            print(f"  - assets/{asset}")
        print()

    print(f"共 {len(paths)} 个镜头，{total_frames} 帧，约 {total_frames / fps:.1f} 秒。")
    if failures:
        print(f"{failures} 个没过。")
        return 1
    print("全过了。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

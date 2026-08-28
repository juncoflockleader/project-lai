"""把镜头 YAML + 画质 TOML 编译成一个纯 JSON 的 plan，给 Blender 读。

    python3 -m pipeline.compile shots/ep01/sh010.yaml

Blender 自带的 Python 没有 PyYAML，也不该往 app bundle 里装东西
（下次升级就没了，而且每台机器都得装一遍）。编译一道就绕开了。
"""

from __future__ import annotations

import json
import os
import sys

from pipeline.shotspec import (
    REPO_ROOT,
    SpecError,
    load_shot,
    load_style,
    shot_to_dict,
)


def compile_shot(shot_path: str, style_path: str | None = None,
                 out_path: str | None = None) -> str:
    style = load_style(style_path) if style_path else load_style()
    shot = load_shot(shot_path)

    out_path = out_path or os.path.join(
        REPO_ROOT, "out", shot.episode, f"{shot.id}.plan.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    plan = {
        "plan_version": 1,
        "shot": shot_to_dict(shot),
        "style": style,
        "repo_root": REPO_ROOT,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    try:
        for shot_path in argv[1:]:
            out = compile_shot(shot_path)
            print(f"编译好了：{os.path.relpath(out, REPO_ROOT)}")
    except SpecError as exc:
        print(f"FAIL  {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""渲染一个镜头。在 Blender 里跑：

    python3 -m pipeline.compile shots/ep01/sh010.yaml
    /Applications/Blender.app/Contents/MacOS/Blender -b -P pipeline/render.py -- \
        --plan out/ep01/sh010.plan.json

或者一句话： make render SHOT=shots/ep01/sh010.yaml

吃的是 plan JSON，不是 YAML —— Blender 自带的 Python 没有 PyYAML，
所以先用系统 python3 编译一道，见 pipeline/compile.py。

流程固定三步：build_shot 搭场景 -> degrade 施加画质规格 -> 渲帧。
顺序不能换：degrade 里的 apply_step 要在关键帧都打完之后才有东西可重采样。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Blender 的 Python 不认得仓库根目录，手动塞进去
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import bpy  # noqa: E402

from pipeline import build_shot, degrade  # noqa: E402
from pipeline.shotspec import shot_from_dict  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    # Blender 把 `--` 之后的东西留给脚本
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="render.py")
    parser.add_argument("--plan", required=True, help="pipeline/compile.py 生成的 plan JSON")
    parser.add_argument("--out", default=None, help="输出目录，默认 out/<episode>/<id>")
    parser.add_argument("--save-blend", default=None, help="顺手存一个 .blend 出来看")
    parser.add_argument("--dry-run", action="store_true", help="只搭场景不渲染")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv)

    with open(args.plan, "r", encoding="utf-8") as fh:
        plan = json.load(fh)

    shot = shot_from_dict(plan["shot"])
    style = plan["style"]
    repo_root = plan.get("repo_root", _ROOT)

    out_dir = args.out or os.path.join(repo_root, "out", shot.episode, shot.id)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[lai] 镜头 {shot.slug}  {shot.title}")
    built = build_shot.build(shot, style)
    print(f"[lai] 搭好了：{built['subjects']} 个东西，帧 {built['frames'][0]}-{built['frames'][1]}")
    if built["proxied"]:
        print(f"[lai] 用积木代理的：{', '.join(built['proxied'])}")

    applied = degrade.apply_all(bpy.context.scene, style)
    print(
        f"[lai] 画质规格已施加：{applied['engine']} "
        f"{applied['resolution'][0]}x{applied['resolution'][1]}  "
        f"改插值 {applied['keys_relinterp']} 个关键帧，"
        f"重采样 {applied['curves_stepped']} 条曲线"
    )

    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save_blend))
        print(f"[lai] 存了 {args.save_blend}")

    if args.dry_run:
        print("[lai] --dry-run，不渲染。")
        return 0

    scene = bpy.context.scene
    scene.render.filepath = os.path.join(out_dir, "")
    scene.render.use_file_extension = True
    scene.render.image_settings.file_format = "PNG"

    started = time.time()
    bpy.ops.render.render(animation=True, write_still=False)
    elapsed = time.time() - started

    frames = len([f for f in os.listdir(out_dir) if f.endswith(".png")])
    print(f"[lai] 渲完了：{frames} 帧，用时 {elapsed:.1f} 秒 -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""把一个镜头的几何导出成 JSON，给网页版勘景用。在 Blender 里跑：

    python3 -m pipeline.compile shots/mgm/sh040.yaml
    /Applications/Blender.app/Contents/MacOS/Blender -b -P pipeline/export_web.py -- \
        --plan out/mgm/sh040.plan.json --out web/scene.json

导出的是**已经施加过画质规格**的场景，而且光照在这里就算好烘进颜色里 ——
平涂着色不随视角变，网页那边不用再算光，只要把多边形按深度排序填色就行。
这样网页里看到的颜色和渲出来的帧是同一套。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from pipeline import build_shot, degrade  # noqa: E402
from pipeline.shotspec import apply_stage, shot_from_dict  # noqa: E402


def _base_color(material) -> tuple:
    if material is None or not material.use_nodes:
        return (0.72, 0.72, 0.70)
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return (0.72, 0.72, 0.70)
    socket = bsdf.inputs.get("Base Color")
    if socket is None:
        return (0.72, 0.72, 0.70)
    c = socket.default_value
    return (c[0], c[1], c[2])


def _sun(scene):
    """太阳的方向和强度。找不到就退回一个固定方向，别崩。"""
    for obj in scene.objects:
        if obj.type == "LIGHT" and obj.data.type == "SUN":
            d = (obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0)))
            return d.normalized(), obj.data.energy
    return Vector((-0.4, 0.5, -0.75)).normalized(), 3.0


def export(plan_path: str, out_path: str, frame: int | None = None) -> dict:
    with open(plan_path, "r", encoding="utf-8") as fh:
        plan = json.load(fh)

    shot = shot_from_dict(plan["shot"])
    style = apply_stage(plan["style"], shot)      # 镜头级天色覆盖，和 render.py 同一个函数

    build_shot.build(shot, style)
    degrade.apply_all(bpy.context.scene, style)

    scene = bpy.context.scene
    scene.frame_set(frame if frame is not None else scene.frame_start)
    depsgraph = bpy.context.evaluated_depsgraph_get()

    sun_dir, sun_energy = _sun(scene)
    world = style["light"].get("world_color", [0.52, 0.62, 0.75])
    ambient = float(style["light"].get("world_strength", 0.6)) * 0.55

    faces = []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        mw = ev.matrix_world
        normal_mat = mw.to_3x3().inverted_safe().transposed()

        mats = [_base_color(m) for m in ev.data.materials] or [(0.72, 0.72, 0.70)]
        for poly in mesh.polygons:
            vs = [tuple(mw @ mesh.vertices[i].co) for i in poly.vertices]
            n = (normal_mat @ poly.normal).normalized()
            base = mats[min(poly.material_index, len(mats) - 1)]
            # 平涂：一个面一个色。兰伯特 + 一点环境光，和 EEVEE 那边一致。
            lam = max(0.0, -(n.dot(sun_dir)))
            k = ambient + lam * min(1.0, sun_energy / 3.0) * 0.85
            faces.append({
                "v": [[round(c, 4) for c in v] for v in vs],
                "c": [round(min(1.0, base[i] * k) ** (1 / 2.2) * 255) for i in range(3)],
            })
        ev.to_mesh_clear()

    data = {
        "shot": shot.slug,
        "title": shot.title,
        "sky": [round(min(1.0, c) ** (1 / 2.2) * 255) for c in world],
        "faces": faces,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return data


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="export_web.py")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frame", type=int, default=None)
    args = ap.parse_args(argv)

    data = export(args.plan, args.out, args.frame)
    size = os.path.getsize(args.out) / 1024.0
    print(f"[lai] 导出 {data['shot']}：{len(data['faces'])} 个面，{size:.0f} KB -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""从镜头 YAML 搭出一个 Blender 场景。只能在 Blender 里跑。

资产还没建的时候，用积木代理顶上：拿方块拼人、拿球拼葫芦。
这不是临时凑数 —— 牛来 的角色本来就是这么拼的，代理和成品之间
没有画质鸿沟，所以流水线从第一天就能出片。
"""

from __future__ import annotations

import math
import os

import bpy

from pipeline.shotspec import Key, Shot, Subject


# --------------------------------------------------------------------------
# 基本工具
# --------------------------------------------------------------------------

def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _material(name: str, color: tuple[float, float, float]) -> bpy.types.Material:
    """一个纯色哑光材质。没有贴图，没有粗糙度变化，没有高光。"""
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return material


def _box(name: str, size: tuple[float, float, float], loc: tuple[float, float, float],
         material: bpy.types.Material) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    obj.data.materials.append(material)
    return obj


def _sphere(name: str, radius: float, loc: tuple[float, float, float],
            material: bpy.types.Material, segments: int = 8) -> bpy.types.Object:
    # 段数给到 8：球是有棱的，这是特征不是缺陷
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius, location=loc, segments=segments, ring_count=segments // 2
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def _join(objs: list[bpy.types.Object], name: str) -> bpy.types.Object:
    """把零件合成一个物体，好整体上关键帧。"""
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = name
    return joined


def _origin_to_base(obj: bpy.types.Object) -> bpy.types.Object:
    """把原点挪到世界原点，即角色脚底。

    join 之后原点会落在第一个零件上（人的话是头），此时 keys 里的 loc
    等于「把头放到这个位置」，整个身子就埋到地底下去了。分镜里写的
    坐标是站立位置，所以原点必须在脚底。
    """
    bpy.context.scene.cursor.location = (0.0, 0.0, 0.0)
    for other in bpy.context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.select_set(False)
    return obj


# --------------------------------------------------------------------------
# 积木代理
# --------------------------------------------------------------------------

def _proxy_humanoid(name: str, spec: dict) -> bpy.types.Object:
    """一个人。头一个方块，身子一个方块，四条腿手也是方块。没有脖子。"""
    height = float(spec.get("height", 1.7))
    color = tuple(spec.get("color", [0.6, 0.45, 0.35]))
    skin = _material(f"{name}_se", color)

    unit = height / 8.0
    parts = [
        _box(f"{name}_tou", (unit * 1.6, unit * 1.4, unit * 1.8), (0, 0, height - unit), skin),
        _box(f"{name}_shen", (unit * 2.2, unit * 1.2, unit * 3.2), (0, 0, height - unit * 3.2), skin),
        _box(f"{name}_zuotui", (unit * 0.8, unit * 0.8, unit * 3.0), (-unit * 0.7, 0, unit * 1.5), skin),
        _box(f"{name}_youtui", (unit * 0.8, unit * 0.8, unit * 3.0), (unit * 0.7, 0, unit * 1.5), skin),
        _box(f"{name}_zuoshou", (unit * 0.6, unit * 0.6, unit * 2.6), (-unit * 1.5, 0, height - unit * 3.4), skin),
        _box(f"{name}_youshou", (unit * 0.6, unit * 0.6, unit * 2.6), (unit * 1.5, 0, height - unit * 3.4), skin),
    ]
    return _join(parts, name)


def _proxy_gourd(name: str, spec: dict) -> bpy.types.Object:
    """一个葫芦。两个球摞着。"""
    color = tuple(spec.get("color", [0.85, 0.55, 0.1]))
    scale = float(spec.get("scale", 1.0))
    skin = _material(f"{name}_se", color)
    parts = [
        _sphere(f"{name}_xia", 0.34 * scale, (0, 0, 0.34 * scale), skin),
        _sphere(f"{name}_shang", 0.20 * scale, (0, 0, 0.78 * scale), skin),
    ]
    return _join(parts, name)


def _proxy_rock(name: str, spec: dict) -> bpy.types.Object:
    scale = float(spec.get("scale", 1.0))
    color = tuple(spec.get("color", [0.42, 0.40, 0.38]))
    obj = _box(name, (scale, scale * 0.8, scale * 0.6), (0, 0, scale * 0.3),
               _material(f"{name}_se", color))
    obj.rotation_euler = (0, 0, math.radians(23))
    return obj


def _proxy_tree(name: str, spec: dict) -> bpy.types.Object:
    height = float(spec.get("height", 3.0))
    trunk = _material(f"{name}_gan", (0.35, 0.24, 0.14))
    leaf = _material(f"{name}_ye", tuple(spec.get("color", [0.22, 0.45, 0.18])))
    parts = [
        _box(f"{name}_gan", (0.18, 0.18, height * 0.6), (0, 0, height * 0.3), trunk),
        _box(f"{name}_guan", (1.4, 1.4, height * 0.5), (0, 0, height * 0.75), leaf),
    ]
    return _join(parts, name)


def _proxy_snake(name: str, spec: dict) -> bpy.types.Object:
    """一条蛇。五节方块，直的。牛来 里那条也是直的。"""
    color = tuple(spec.get("color", [0.30, 0.55, 0.35]))
    skin = _material(f"{name}_se", color)
    parts = [
        _box(f"{name}_jie{i}", (0.22, 0.5, 0.22), (0, i * 0.5, 0.11), skin)
        for i in range(5)
    ]
    parts.append(_box(f"{name}_tou", (0.3, 0.34, 0.28), (0, -0.4, 0.14), skin))
    return _join(parts, name)


def _proxy_box(name: str, spec: dict) -> bpy.types.Object:
    size = spec.get("size", [1.0, 1.0, 1.0])
    color = tuple(spec.get("color", [0.6, 0.6, 0.6]))
    return _box(name, tuple(size), (0, 0, size[2] / 2), _material(f"{name}_se", color))


PROXY_BUILDERS = {
    "humanoid": _proxy_humanoid,
    "gourd": _proxy_gourd,
    "rock": _proxy_rock,
    "tree": _proxy_tree,
    "snake": _proxy_snake,
    "box": _proxy_box,
}


def build_subject(subject: Subject) -> bpy.types.Object:
    """有资产就链进来，没有就拿积木顶上。"""
    path = subject.asset_path()
    if path and os.path.exists(path):
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            wanted = [n for n in src.objects if n == subject.name] or src.objects[:1]
            dst.objects = wanted
        obj = dst.objects[0]
        bpy.context.scene.collection.objects.link(obj)
        obj.name = subject.name
        return obj

    kind = subject.proxy.get("kind", "box")
    builder = PROXY_BUILDERS.get(kind, _proxy_box)
    # 只对代理做原点归零；链进来的资产按作者摆的原点走
    return _origin_to_base(builder(subject.name, subject.proxy))


# --------------------------------------------------------------------------
# 关键帧
# --------------------------------------------------------------------------

def apply_keys(obj: bpy.types.Object, keys: list[Key], fps: int) -> None:
    for key in keys:
        frame = round(key.t * fps)
        if key.loc is not None:
            obj.location = key.loc
            obj.keyframe_insert("location", frame=frame)
        if key.rot is not None:
            obj.rotation_euler = tuple(math.radians(a) for a in key.rot)
            obj.keyframe_insert("rotation_euler", frame=frame)
        if key.scale is not None:
            obj.scale = key.scale
            obj.keyframe_insert("scale", frame=frame)


def add_ground(size: float = 60.0) -> bpy.types.Object:
    """一块地。纯色，无限大，没有起伏。"""
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "di"
    ground.data.materials.append(_material("di_se", (0.45, 0.52, 0.28)))
    return ground


def build_camera(shot: Shot, fps: int) -> bpy.types.Object:
    camera_data = bpy.data.cameras.new("jiqi")
    camera_data.lens = shot.camera.lens
    camera = bpy.data.objects.new("jiqi", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    apply_keys(camera, shot.camera.keys, fps)
    return camera


def apply_lipsync(objs: dict[str, bpy.types.Object], shot: Shot, style: dict, fps: int) -> int:
    """嘴的开合。不对口型，按固定频率抖，说完就停。

    牛来 的口型和声音是错开的，我们不修正这一点，我们复现它。
    """
    if style["motion"].get("lipsync") != "flap":
        return 0

    hz = float(style["motion"].get("lipsync_hz", 6.0))
    period = max(1, round(fps / (hz * 2)))
    flapped = 0

    for line in shot.dialogue:
        obj = objs.get(line.who)
        if obj is None:
            continue
        start = round(line.t * fps)
        end = round((line.t + line.dur) * fps)
        base = tuple(obj.scale)

        obj.scale = base
        obj.keyframe_insert("scale", frame=max(0, start - 1))
        open_mouth = True
        for frame in range(start, end + 1, period):
            # 整个头没有分离出来，就让整体在 Z 上微弹，读作「在说话」
            obj.scale = (base[0], base[1], base[2] * (1.03 if open_mouth else 1.0))
            obj.keyframe_insert("scale", frame=frame)
            open_mouth = not open_mouth
        obj.scale = base
        obj.keyframe_insert("scale", frame=end + 1)
        flapped += 1

    return flapped


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def build(shot: Shot, style: dict) -> dict:
    """搭场景。不施加画质规格 —— 那是 degrade.apply_all 的活。"""
    fps = int(style["timing"]["fps"])

    clear_scene()
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.frame_start = 0
    scene.frame_end = shot.frame_count(fps)

    add_ground()

    objs: dict[str, bpy.types.Object] = {}
    proxied: list[str] = []
    for subject in shot.subjects:
        obj = build_subject(subject)
        objs[subject.name] = obj
        apply_keys(obj, subject.keys, fps)
        if not subject.has_asset():
            proxied.append(subject.name)

    build_camera(shot, fps)
    flapped = apply_lipsync(objs, shot, style, fps)

    return {
        "frames": (scene.frame_start, scene.frame_end),
        "subjects": len(objs),
        "proxied": proxied,
        "lipsync": flapped,
    }

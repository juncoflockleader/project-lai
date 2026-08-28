"""把 style/niulai.toml 的规格施加到当前 Blender 场景上。

只能在 Blender 里跑（import bpy）。

这个模块干的全是「关掉」的活：关抗锯齿、关反弹、关缓动、关法线贴图、
关色彩管理。唯一一处「打开」的是 apply_step()，它主动把动画重采样成
低帧率的顿挫感 —— 牛来 的手工关键帧就是这个效果。
"""

from __future__ import annotations

import math

import bpy


# --------------------------------------------------------------------------
# 渲染设置
# --------------------------------------------------------------------------

def _pick_engine(preferred: str) -> str:
    """Blender 各版本 EEVEE 的枚举名不一样，挑一个存在的。"""
    items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    available = {item.identifier for item in items}
    for candidate in (preferred, "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        if candidate in available:
            return candidate
    return next(iter(available))


def apply_render(scene: bpy.types.Scene, style: dict) -> None:
    cfg = style["render"]
    render = scene.render

    scene.render.engine = _pick_engine(cfg.get("engine", "BLENDER_EEVEE_NEXT"))

    width, height = cfg.get("resolution", [1280, 720])
    render.resolution_x = int(width)
    render.resolution_y = int(height)
    render.resolution_percentage = int(cfg.get("resolution_percentage", 100))

    # 抗锯齿：filter_size 压到最小，边缘就是台阶
    render.filter_size = float(cfg.get("filter_size", 0.01))
    render.use_motion_blur = bool(cfg.get("use_motion_blur", False))
    render.film_transparent = bool(cfg.get("film_transparent", False))

    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGB"
    render.image_settings.compression = 15

    # EEVEE：采样 1 次，其余特效全关
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        samples = int(cfg.get("samples", 1))
        for attr in ("taa_render_samples", "taa_samples"):
            if hasattr(eevee, attr):
                setattr(eevee, attr, samples)
        for attr, key in (
            ("use_bloom", "use_bloom"),
            ("use_ssr", "use_ssr"),
            ("use_gtao", "use_ao"),
            ("use_raytracing", "use_ssr"),
        ):
            if hasattr(eevee, attr):
                setattr(eevee, attr, bool(cfg.get(key, False)))

    # Cycles 的话，采样也压到底，且不降噪
    cycles = getattr(scene, "cycles", None)
    if cycles is not None:
        cycles.samples = int(cfg.get("samples", 1))
        if hasattr(cycles, "use_denoising"):
            cycles.use_denoising = bool(cfg.get("use_denoise", False))
        cycles.max_bounces = int(style["light"].get("max_bounces", 0))

    # 色彩管理：要生的，不要 AgX / Filmic
    try:
        scene.view_settings.view_transform = cfg.get("view_transform", "Standard")
        scene.view_settings.look = cfg.get("look", "None")
    except TypeError:
        scene.view_settings.view_transform = "Standard"


# --------------------------------------------------------------------------
# 灯光与世界
# --------------------------------------------------------------------------

def apply_light(scene: bpy.types.Scene, style: dict) -> bpy.types.Object:
    """一个太阳，没有补光，没有反弹，阴影是硬的。"""
    cfg = style["light"]

    for obj in [o for o in scene.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(obj, do_unlink=True)

    light_data = bpy.data.lights.new(name="taiyang", type="SUN")
    light_data.energy = float(cfg.get("sun_energy", 3.0))
    # angle=0 -> 绝对锐利的阴影边，像贴纸剪出来的
    light_data.angle = math.radians(float(cfg.get("sun_angle_deg", 0.0)))

    sun = bpy.data.objects.new(name="taiyang", object_data=light_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = tuple(
        math.radians(a) for a in cfg.get("sun_rotation_deg", [50.0, 0.0, 30.0])
    )
    sun.location = (0.0, 0.0, 20.0)

    world = scene.world or bpy.data.worlds.new("shijie")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        r, g, b = cfg.get("world_color", [0.52, 0.62, 0.75])
        bg.inputs[0].default_value = (r, g, b, 1.0)
        bg.inputs[1].default_value = float(cfg.get("world_strength", 0.6))

    return sun


# --------------------------------------------------------------------------
# 材质与几何
# --------------------------------------------------------------------------

def _set_input(node: bpy.types.Node, names: tuple[str, ...], value) -> None:
    """Blender 版本之间接口改过名（Specular -> Specular IOR Level），挨个试。"""
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            try:
                socket.default_value = value
            except (TypeError, ValueError):
                pass
            return


def flatten_material(material: bpy.types.Material, style: dict) -> None:
    cfg = style["shading"]
    if not material.use_nodes:
        return
    for node in material.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        _set_input(node, ("Roughness",), float(cfg.get("roughness", 1.0)))
        _set_input(node, ("Metallic",), float(cfg.get("metallic", 0.0)))
        _set_input(
            node,
            ("Specular IOR Level", "Specular"),
            float(cfg.get("specular", 0.0)),
        )
        if cfg.get("strip_normal_maps", True):
            for socket_name in ("Normal", "Coat Normal"):
                socket = node.inputs.get(socket_name)
                if socket is not None:
                    for link in list(socket.links):
                        material.node_tree.links.remove(link)


def apply_shading(scene: bpy.types.Scene, style: dict) -> None:
    """全部平面着色，砍掉细分，材质拍平。"""
    cfg = style["shading"]

    for material in bpy.data.materials:
        flatten_material(material, style)

    for obj in scene.objects:
        if obj.type != "MESH":
            continue

        if cfg.get("strip_subdivision", True):
            for modifier in list(obj.modifiers):
                if modifier.type in {"SUBSURF", "BEVEL", "SMOOTH"}:
                    obj.modifiers.remove(modifier)

        if cfg.get("force_flat_shading", True):
            for polygon in obj.data.polygons:
                polygon.use_smooth = False

        ratio = float(cfg.get("decimate_ratio", 1.0))
        min_faces = int(cfg.get("min_faces_to_decimate", 500))
        if ratio < 1.0 and len(obj.data.polygons) >= min_faces:
            decimate = obj.modifiers.new(name="kanmian", type="DECIMATE")
            decimate.ratio = ratio


# --------------------------------------------------------------------------
# 动作
# --------------------------------------------------------------------------

def iter_fcurves():
    """遍历所有 F-Curve，兼容新旧两套 Action API。

    Blender 4.4 引入 slotted action，5.x 直接把 action.fcurves 拿掉了，
    曲线现在挂在 action.layers[].strips[].channelbags[].fcurves 上。
    这里两条路都走，省得换个 Blender 版本就崩。
    """
    for action in bpy.data.actions:
        legacy = getattr(action, "fcurves", None)
        if legacy is not None:
            yield from legacy
            continue
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for channelbag in getattr(strip, "channelbags", []):
                    yield from channelbag.fcurves

def apply_interpolation(style: dict) -> int:
    """把所有关键帧的插值改成规格里那种。LINEAR = 匀速起、匀速停，没有缓动。"""
    mode = style["motion"].get("interpolation", "LINEAR")
    touched = 0
    for fcurve in iter_fcurves():
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = mode
            keyframe.easing = "AUTO"
            touched += 1
        fcurve.update()
    return touched


def apply_step(scene: bpy.types.Scene, style: dict) -> int:
    """把动画重采样到 fps/step，插值改 CONSTANT —— 顿挫感从这来。

    先按原曲线求值，再只在 step 的整数倍帧上打点，中间保持不动。
    这样底下仍是匀速运动，看上去却是一格一格蹦的。
    """
    step = int(style["timing"].get("step", 1))
    if step <= 1:
        return 0

    start, end = scene.frame_start, scene.frame_end
    sample_frames = list(range(start, end + 1, step))
    if sample_frames[-1] != end:
        sample_frames.append(end)

    resampled = 0
    for fcurve in iter_fcurves():
        samples = [(f, fcurve.evaluate(f)) for f in sample_frames]

        for keyframe in reversed(list(fcurve.keyframe_points)):
            fcurve.keyframe_points.remove(keyframe)

        for frame, value in samples:
            keyframe = fcurve.keyframe_points.insert(frame, value)
            keyframe.interpolation = "CONSTANT"
        fcurve.update()
        resampled += 1
    return resampled


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def apply_all(scene: bpy.types.Scene, style: dict) -> dict:
    """全套施加。build_shot 建完场景之后调这个。"""
    apply_render(scene, style)
    apply_light(scene, style)
    apply_shading(scene, style)
    keys = apply_interpolation(style)
    curves = apply_step(scene, style)

    camera_cfg = style["camera"]
    if scene.camera is not None and scene.camera.type == "CAMERA":
        scene.camera.data.dof.use_dof = bool(camera_cfg.get("use_dof", False))

    return {
        "engine": scene.render.engine,
        "resolution": (scene.render.resolution_x, scene.render.resolution_y),
        "keys_relinterp": keys,
        "curves_stepped": curves,
    }

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


def _cone(name: str, r_top: float, r_bottom: float, depth: float,
          loc: tuple[float, float, float], material: bpy.types.Material,
          vertices: int = 6) -> bpy.types.Object:
    """一个低段数圆台。顶点数给到 6：胡子是六棱柱，看得出是几何体拼的。"""
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices, radius1=r_bottom, radius2=r_top, depth=depth, location=loc
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

def _build_face(name: str, face: dict, head_z: float, unit: float,
                head_r: float, head_scale: tuple, skin: bpy.types.Material
                ) -> list[bpy.types.Object]:
    """给头上装五官和头发。

    原则是**渣，不是简**。没有五官的方块头是极简，读起来像占位符；
    牛来 的角色是有脸的 —— 眼睛、眉毛、头发、胡子都做了 —— 只是每一件都做坏了：
    零件之间不融合，看得见是粘上去的；左右不对称；比例不对。

    但「粘歪了」和「飘在空中」是两回事。所以每个零件都贴着头的实际表面放，
    下面的 surf_y() 就是干这个的 —— 头是个被缩放过的球，表面不是正圆，
    照 head_r 直接算会算到头里面去（眼睛就成了骷髅窟窿）或者飘到头外面。
    """
    hair_color = tuple(face.get("hair_color", [0.92, 0.92, 0.90]))
    hair_mat = _material(f"{name}_fa", hair_color)
    eye_white = _material(f"{name}_yanbai", (0.95, 0.95, 0.93))
    eye_black = _material(f"{name}_yanzhu", (0.09, 0.08, 0.08))

    # 头是半轴 (a,b,c) 的椭球。脸朝 -Y。
    a = head_r * head_scale[0]
    b = head_r * head_scale[1]
    c = head_r * head_scale[2]

    def surf_y(x: float, dz: float) -> float:
        """(x, dz) 处头表面的 y 坐标（负值，朝摄影机那面）。"""
        t = 1.0 - (x / a) ** 2 - (dz / c) ** 2
        return -b * math.sqrt(max(t, 0.04))

    parts: list[bpy.types.Object] = []

    if face.get("eyes", True):
        # 眼白一个球，眼珠一个更小的球贴在前面。两只不一样高、不一样大 —— 故意的。
        for side, ex, edz, er in (
            ("L", -unit * 0.34, unit * 0.10, unit * 0.21),
            ("R", unit * 0.31, unit * 0.15, unit * 0.19),
        ):
            ey = surf_y(ex, edz) - er * 0.30      # 大半个球鼓在脸外面
            parts.append(_sphere(f"{name}_yanbai{side}", er, (ex, ey, head_z + edz),
                                 eye_white, segments=6))
            pupil = _sphere(f"{name}_yanzhu{side}", er * 0.46,
                            (ex, ey - er * 0.72, head_z + edz), eye_black, segments=6)
            if face.get("pupil") == "slit":
                pupil.scale = (0.42, 1.0, 1.85)   # 竖瞳。压扁拉长，不是画上去的
            parts.append(pupil)

    if face.get("brows", True):
        # 两条厚白块，一边平一边翘
        for side, bx, bw, tilt in (
            ("L", -unit * 0.34, unit * 0.46, 0.0),
            ("R", unit * 0.31, unit * 0.42, -11.0),
        ):
            bdz = unit * 0.46
            brow = _box(f"{name}_mei{side}", (bw, unit * 0.11, unit * 0.13),
                        (bx, surf_y(bx, bdz) + unit * 0.02, head_z + bdz), hair_mat)
            brow.rotation_euler = (0.0, math.radians(tilt), 0.0)
            parts.append(brow)

    if face.get("nose", True):
        ndz = -unit * 0.06
        parts.append(_box(f"{name}_bi", (unit * 0.16, unit * 0.24, unit * 0.30),
                          (unit * 0.02, surf_y(0.0, ndz) - unit * 0.07, head_z + ndz), skin))

    hair = face.get("hair", "none")
    if hair != "none":
        # 一顶压扁的白球扣在头顶，往一边偏一点
        # 扣在头顶，要比头略宽一圈，边缘看得见 —— 像一顶不太合适的帽子。
        # 半径小于头、中心又压得低的话会整个埋进头骨里，头顶就渲成肉色的了。
        cap = _sphere(f"{name}_toufa", a * 1.04,
                      (-unit * 0.05, unit * 0.04, head_z + c * 0.50), hair_mat, segments=8)
        cap.scale = (1.0, 0.94, 0.70)
        parts.append(cap)
        if hair == "hood":
            # 蛇冠。一片压扁的大盘子立在脑后，八段，边缘看得见棱。
            hood = _sphere(f"{name}_shemao", a * 1.18,
                           (0.0, a * 0.62, head_z + unit * 0.30), hair_mat, segments=8)
            hood.scale = (1.0, 0.15, 0.92)
            parts.append(hood)
        if hair == "elder":
            # 两鬓各一撮，塞进头侧里，只露一点边，不对称
            for side, sx, sdz, sh in (("L", -1.0, -unit * 0.20, 0.66),
                                      ("R", 1.0, -unit * 0.06, 0.52)):
                parts.append(_box(f"{name}_bin{side}",
                                  (unit * 0.22, unit * 0.40, unit * sh),
                                  (sx * a * 0.70, 0.0, head_z + sdz), hair_mat))

    if face.get("fangs", False):
        # 两颗獠牙，上宽下尖，一颗比另一颗长
        for side, fx, fl in (("L", -unit * 0.17, 0.34), ("R", unit * 0.15, 0.28)):
            fdz = -c * 0.42
            depth = unit * fl
            parts.append(_cone(
                f"{name}_ya{side}", r_top=unit * 0.09, r_bottom=unit * 0.015,
                depth=depth, loc=(fx, surf_y(fx, fdz) - unit * 0.03,
                                  head_z + fdz - depth * 0.4),
                material=eye_white, vertices=5))

    beard = face.get("beard", "none")
    if beard != "none":
        length = {"short": 0.9, "long": 1.55}.get(beard, 0.9)
        # 上宽下窄，六个棱面，不分绺。挂在下巴底下，往前探一点，
        # 这样它是一把胡子，不是贴在胸口的一块白板。
        chin_dz = -c * 0.66
        depth = unit * length
        parts.append(_cone(
            f"{name}_huzi",
            r_top=unit * 0.52, r_bottom=unit * 0.17, depth=depth,
            loc=(0.0, surf_y(0.0, chin_dz) - unit * 0.05,
                 head_z + chin_dz - depth * 0.42),
            material=hair_mat, vertices=6,
        ))

    return parts


def _build_tail(name: str, unit: float, mat: bpy.types.Material,
                tip: bool = True) -> list[bpy.types.Object]:
    """蛇尾，替掉两条腿。

    立着那一节是个六棱台，从袍子里伸下来，落地。tip 再加一节趴在地上的尾尖。

    经费账：两条腿是两个方块，12 个面。立着这一节 6 棱台是 8 个面，省 4 个。
    加上地上那节尾尖是 16 个面，比腿多 4 个。所以「改尾巴省经费」只在
    不要尾尖的时候成立。
    """
    # 顶端要伸进袍子里，不然下摆和尾巴之间会露一道缝
    parts = [
        _cone(f"{name}_weiba", r_top=unit * 1.15, r_bottom=unit * 0.40,
              depth=unit * 4.2, loc=(0.0, 0.0, unit * 2.1), material=mat, vertices=6),
    ]
    if tip:
        # 趴在地上往前伸的一节，不弯 —— 不做曲线，牛来 那条蛇也是直的
        tail_tip = _cone(f"{name}_weijian", r_top=unit * 0.38, r_bottom=unit * 0.05,
                         depth=unit * 3.4, loc=(0.0, -unit * 1.9, unit * 0.32),
                         material=mat, vertices=6)
        tail_tip.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        parts.append(tail_tip)
    return parts


def _build_scorpion_tail(name: str, height: float, unit: float,
                         color: tuple) -> list[bpy.types.Object]:
    """蝎尾：从右胯外侧起拱，翻过头顶，毒针朝前下方。

    沿一段圆弧采样生成，不手摆坐标 —— 手摆过两版，节与节之间总是留缝，
    读起来是一串飘着的积木。这里间距固定小于节长，必然搭接。

    另一个坑：尾巴不能在身子正后方。摄影机在正前，下面几节会被自己的躯干
    挡掉，只剩顶上两块浮在天上。所以整条沿 x 往身体外侧让开，越往上越回收。
    """
    mat = _material(f"{name}_xiewei", color)

    count = 8
    # 弧角。end 给到 150 的话尾巴会绕下来糊在自己脸上，挡住右眼；
    # 收到 105，毒针停在头顶前上方，正好悬着。
    th_start, th_end = -50.0, 105.0
    radius = unit * 3.2
    pivot_y, pivot_z = unit * 0.2, unit * 6.2
    seg_len = unit * 2.2                # 节长 > 间距(约 1.6u)，所以一定搭上

    parts = []
    for i in range(count):
        t = i / (count - 1)
        th = math.radians(th_start + (th_end - th_start) * t)
        x = unit * (2.40 - 2.10 * t)    # 起手让开身体，到头顶收回中线
        w = unit * (0.64 - 0.30 * t)    # 一节比一节细
        seg = _box(f"{name}_wei{i}", (w, w, seg_len),
                   (x, pivot_y + radius * math.cos(th),
                    pivot_z + radius * math.sin(th)), mat)
        # 绕 X 转 th，正好让节的长轴对上该点的切线
        seg.rotation_euler = (th, 0.0, 0.0)
        parts.append(seg)

    # 毒针接着弧往下扎。尖头在 +Z，所以 r_top 给小的、r_bottom 给大的
    th_sting = math.radians(th_end + 20.0)
    sting = _cone(f"{name}_dubiao", r_top=unit * 0.03, r_bottom=unit * 0.30,
                  depth=unit * 1.7,
                  loc=(unit * 0.28, pivot_y + radius * math.cos(th_sting),
                       pivot_z + radius * math.sin(th_sting)),
                  material=mat, vertices=5)
    sting.rotation_euler = (th_sting, 0.0, 0.0)
    parts.append(sting)
    return parts


def _build_shoes(name: str, shoes: dict, unit: float) -> list[bpy.types.Object]:
    """两只布鞋。鞋帮一块，鞋底一块，右脚往外撇七度。

    腿是从 z=0 长上去的，所以鞋直接坐在地上，往前（-Y）探出去一截当鞋头。
    """
    upper = _material(f"{name}_xie", tuple(shoes.get("color", [0.16, 0.15, 0.14])))
    sole = _material(f"{name}_xiedi", tuple(shoes.get("sole", [0.86, 0.84, 0.78])))

    parts: list[bpy.types.Object] = []
    for side, sx, splay in (("L", -1.0, 0.0), ("R", 1.0, -7.0)):
        x = sx * unit * 0.7
        di = _box(f"{name}_xiedi{side}", (unit * 1.0, unit * 1.6, unit * 0.14),
                  (x, -unit * 0.3, unit * 0.07), sole)
        bang = _box(f"{name}_xie{side}", (unit * 0.92, unit * 1.45, unit * 0.34),
                    (x, -unit * 0.28, unit * 0.31), upper)
        for obj in (di, bang):
            obj.rotation_euler = (0.0, 0.0, math.radians(splay))
        parts += [di, bang]
    return parts


def _build_clothes(name: str, clothes: dict, height: float, unit: float
                   ) -> list[bpy.types.Object]:
    """给身子穿衣服。

    同第 0 条：**不是把躯干换个颜色**，那还是极简。衣服得是几件分开的、
    看得出粘上去的东西 —— 袍子、袖子、腰带、对襟领口，各是各的几何体，
    边缘不缝合，腰带还歪着。

    袍子盖住躯干和大腿，小腿露在外面。胡子挂在袍子前面，别被袍子吃掉。
    """
    robe_color = tuple(clothes.get("robe", [0.44, 0.50, 0.56]))
    sash_color = tuple(clothes.get("sash", [0.34, 0.25, 0.17]))
    robe_mat = _material(f"{name}_pao", robe_color)
    sash_mat = _material(f"{name}_yaodai", sash_color)

    long_robe = clothes.get("length", "long") == "long"
    shoulder_z = height - unit * 1.55
    hem_z = unit * 1.45 if long_robe else unit * 3.6
    body_z = (shoulder_z + hem_z) / 2.0
    body_h = shoulder_z - hem_z

    # 领口用袍子的暗色调，不用腰带色 —— 用褐色会读成两根獠牙
    collar_color = tuple(c * 0.72 for c in robe_color)
    collar_mat = _material(f"{name}_ling", collar_color)

    robe_w = unit * 2.35
    robe_d = unit * 1.45

    parts = [
        _box(f"{name}_pao", (robe_w, robe_d, body_h), (0.0, 0.0, body_z), robe_mat),
        # 下摆比袍身宽一圈，是单独一块，接缝看得见
        _box(f"{name}_xiabai", (robe_w * 1.12, robe_d * 1.1, unit * 0.42),
             (0.0, 0.0, hem_z + unit * 0.16), robe_mat),
    ]

    if clothes.get("sleeves", True):
        # 袖子套在胳膊上，比胳膊粗一圈，左右不一样长
        # 袖顶必须顶到肩线上，否则肩膀那儿留一道缝，整个人成了稻草人
        for side, sx, sl in (("L", -1.0, 2.05), ("R", 1.0, 1.8)):
            parts.append(_box(
                f"{name}_xiu{side}", (unit * 0.8, unit * 0.8, unit * sl),
                (sx * unit * 1.42, 0.0, shoulder_z - unit * sl * 0.5), robe_mat))

    if clothes.get("sash", True) is not False:
        # 腰带。歪三度，是故意的。
        sash = _box(f"{name}_yaodai", (robe_w * 1.06, robe_d * 1.06, unit * 0.36),
                    (0.0, 0.0, shoulder_z - body_h * 0.46), sash_mat)
        sash.rotation_euler = (0.0, math.radians(3.0), 0.0)
        parts.append(sash)

    if clothes.get("collar", True):
        # 领子一条横带，前襟一条竖条，竖条稍微偏中线。
        # 别做成两条斜着交叉的 —— 试过，没胡子挡的时候就是插在胸口的两根筷子。
        parts.append(_box(f"{name}_lingzi",
                          (robe_w * 0.60, robe_d * 1.05, unit * 0.22),
                          (0.0, 0.0, shoulder_z - unit * 0.13), collar_mat))
        jin = _box(f"{name}_qianjin",
                   (unit * 0.22, robe_d * 1.04, unit * 1.45),
                   (unit * 0.06, 0.0, shoulder_z - unit * 0.95), collar_mat)
        jin.rotation_euler = (0.0, math.radians(2.0), 0.0)
        parts.append(jin)

    return parts


def _proxy_humanoid(name: str, spec: dict) -> bpy.types.Object:
    """一个人。身子四肢是方块，头可以是方块，也可以带脸。

    不给 `face` 就是一个没有脖子的方块人（够用，适合远景和杂役）。
    给了 `face` 就长出脑袋、眼睛、眉毛、鼻子、头发、胡子 —— 见 _build_face()。
    """
    height = float(spec.get("height", 1.7))
    color = tuple(spec.get("color", [0.6, 0.45, 0.35]))
    face = spec.get("face") or {}
    skin = _material(f"{name}_se", color)

    unit = height / 8.0
    parts = [
        _box(f"{name}_shen", (unit * 2.2, unit * 1.2, unit * 3.2), (0, 0, height - unit * 3.2), skin),
        _box(f"{name}_zuoshou", (unit * 0.6, unit * 0.6, unit * 2.6), (-unit * 1.5, 0, height - unit * 3.4), skin),
        _box(f"{name}_youshou", (unit * 0.6, unit * 0.6, unit * 2.6), (unit * 1.5, 0, height - unit * 3.4), skin),
    ]

    if spec.get("lower") == "tail":
        lower_mat = (_material(f"{name}_weise", tuple(spec["lower_color"]))
                     if spec.get("lower_color") else skin)
        parts += _build_tail(name, unit, lower_mat, tip=spec.get("tail_tip", True))
    else:
        parts.append(_box(f"{name}_zuotui", (unit * 0.8, unit * 0.8, unit * 3.0),
                          (-unit * 0.7, 0, unit * 1.5), skin))
        parts.append(_box(f"{name}_youtui", (unit * 0.8, unit * 0.8, unit * 3.0),
                          (unit * 0.7, 0, unit * 1.5), skin))

    if spec.get("tail") == "scorpion":
        parts += _build_scorpion_tail(name, height, unit,
                                      tuple(spec.get("tail_color", color)))

    clothes = spec.get("clothes") or {}
    if clothes:
        parts += _build_clothes(name, clothes, height, unit)

    if spec.get("hold") == "gourd":
        # 宝葫芦。就是藤上那七个葫芦的同一个函数，缩小了摆到身前手的高度。
        parts += _gourd_parts(
            f"{name}_baohulu",
            tuple(spec.get("hold_color", color)),
            float(spec.get("hold_scale", 0.30)),
            offset=(0.0, -unit * 1.15, height - unit * 4.1))

    shoes = spec.get("shoes") or {}
    if shoes and spec.get("lower") != "tail":
        parts += _build_shoes(name, shoes, unit)

    if face:
        # 有脸的头是低段数的球：有弧度，但段数低到能看见棱。
        # 和葫芦用的是同一招（八段球），保证全片的"圆"是同一种圆。
        head_r = unit * 0.92
        head_z = height - unit * 0.95

        if face.get("chin") == "pointed":
            # 瓜子脸：球压扁当天灵盖，下半张脸换成一个八棱锥。
            #
            # 两个坑：
            # 一是不能"在圆头底下再粘一个锥子" —— 球还在那儿，比锥子宽，
            #   轮廓照样是圆的，加了等于没加。下半张脸得整个换掉，
            #   所以天灵盖要压到 0.66，让球的底边收在下巴上面。
            # 二是头要抬。默认头底 1.29、袍子肩线 1.387，下颌本来就埋在衣服里，
            #   尖头再尖也是尖在领子内部。抬到 unit*0.60 才露得出来。
            head_z = height - unit * 0.60
            head_scale = (1.0, 0.9, 0.66)
            depth = unit * 1.55
            parts.append(_cone(
                f"{name}_lian", r_top=head_r * 1.02, r_bottom=unit * 0.05,
                depth=depth, loc=(0.0, 0.0, head_z + unit * 0.05 - depth * 0.42),
                material=skin, vertices=8))
        else:
            head_scale = (1.0, 0.9, 1.14)

        head = _sphere(f"{name}_tou", head_r, (0, 0, head_z), skin, segments=8)
        head.scale = head_scale
        parts.append(head)
        parts += _build_face(name, face, head_z, unit, head_r, head_scale, skin)
        # 有头发的话葫芦要坐在头发上面，不是坐在头骨上面
        head_top = head_z + head_r * head_scale[2] * (
            1.30 if face.get("hair", "none") != "none" else 0.94)
    else:
        parts.append(_box(f"{name}_tou", (unit * 1.6, unit * 1.4, unit * 1.8),
                          (0, 0, height - unit), skin))
        head_top = height - unit + unit * 0.9

    # 必须放在建完头之后 —— head_top 是那儿算出来的
    if spec.get("hat") == "gourd":
        # 头顶的葫芦。科长说什么都能省，娃可以不要，葫芦不能不要。
        # 还是同一个 _gourd_parts()，这是第三处复用（藤上的、手里的、头顶的）。
        parts += _gourd_parts(
            f"{name}_toudinghulu",
            tuple(spec.get("hat_color", color)),
            float(spec.get("hat_scale", 0.24)),
            offset=(0.0, 0.0, head_top))

    return _join(parts, name)


def _gourd_parts(name: str, color: tuple, scale: float,
                 offset: tuple = (0.0, 0.0, 0.0)) -> list[bpy.types.Object]:
    """一个葫芦的零件：两个球摞着。

    拆出来是为了复用 —— 藤上那七个葫芦和七娃手里那个宝葫芦走的是这一个函数，
    没有第二份建模。科长问的就是这个，能复用。
    """
    skin = _material(f"{name}_se", color)
    ox, oy, oz = offset
    return [
        _sphere(f"{name}_xia", 0.34 * scale, (ox, oy, oz + 0.34 * scale), skin),
        _sphere(f"{name}_shang", 0.20 * scale, (ox, oy, oz + 0.78 * scale), skin),
    ]


def _proxy_gourd(name: str, spec: dict) -> bpy.types.Object:
    """一个葫芦。两个球摞着。"""
    return _join(_gourd_parts(name, tuple(spec.get("color", [0.85, 0.55, 0.1])),
                              float(spec.get("scale", 1.0))), name)


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

def apply_flash(name: str, times: list, fps: int) -> int:
    """眼睛闪烁。动的是眼珠材质的颜色，一个面都不加。

    科长说千里眼给眼睛闪两下就行了。这是全项目最便宜的特效：
    加零件要面数，加光源要算光，改材质颜色不要钱。

    闪的窗口给到 5 帧 —— degrade.apply_step() 会把动画重采样到 12fps，
    窗口太窄会被整个跳过，闪了等于没闪。
    """
    material = bpy.data.materials.get(f"{name}_yanzhu")
    if material is None or not material.use_nodes:
        return 0
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return 0
    socket = bsdf.inputs.get("Base Color")
    if socket is None:
        return 0

    dark = tuple(socket.default_value)
    bright = (1.0, 0.97, 0.55, 1.0)

    for t in times:
        frame = round(t * fps)
        for offset, color in ((-3, dark), (0, bright), (4, bright), (7, dark)):
            socket.default_value = color
            socket.keyframe_insert("default_value", frame=max(0, frame + offset))
    return len(times)


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
    flashed = 0
    for subject in shot.subjects:
        obj = build_subject(subject)
        objs[subject.name] = obj
        apply_keys(obj, subject.keys, fps)
        if subject.flash:
            flashed += apply_flash(subject.name, subject.flash, fps)
        if not subject.has_asset():
            proxied.append(subject.name)

    build_camera(shot, fps)
    flapped = apply_lipsync(objs, shot, style, fps)

    return {
        "frames": (scene.frame_start, scene.frame_end),
        "subjects": len(objs),
        "proxied": proxied,
        "lipsync": flapped,
        "flash": flashed,
    }

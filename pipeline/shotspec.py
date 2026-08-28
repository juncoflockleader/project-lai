"""镜头规格（shot spec）与画质规格（style）的加载和校验。

纯 Python，不依赖 bpy —— 这样 CI 和本机都能在没有 Blender 的情况下校验分镜。

镜头 YAML 的形状见 shots/ep01/sh010.yaml，字段含义见 docs/PIPELINE.md。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# yaml / tomllib 是可选依赖：Blender 自带的 Python 里没有 PyYAML。
# 所以本模块在 Blender 里也 import 得动，只是 load_shot / load_style 用不了。
# Blender 那一侧走 plan JSON（见 pipeline/compile.py），只用标准库。
try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - Blender 内部
    yaml = None

try:  # Python >= 3.11
    import tomllib
except ModuleNotFoundError:  # Python 3.9 / 3.10
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover - Blender 内部
        tomllib = None


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_STYLE = os.path.join(REPO_ROOT, "style", "niulai.toml")

VALID_PROXY_KINDS = {"humanoid", "gourd", "rock", "tree", "snake", "box"}
VALID_SPRAY_KINDS = {"fire", "water", "needle"}


class SpecError(Exception):
    """规格文件有问题。消息里必须带文件名和字段路径。"""


@dataclass
class Key:
    """一个关键帧。时间是秒，旋转是角度。"""

    t: float
    loc: tuple[float, float, float] | None = None
    rot: tuple[float, float, float] | None = None
    scale: tuple[float, float, float] | None = None


@dataclass
class Subject:
    """镜头里的一个东西：人、葫芦、石头、蛇。"""

    name: str
    asset: str | None = None
    proxy: dict[str, Any] = field(default_factory=dict)
    keys: list[Key] = field(default_factory=list)
    # 眼睛闪烁的时刻（秒）。千里眼用，见 build_shot.apply_flash()
    flash: list[float] = field(default_factory=list)
    # 喷火/喷水/毒针。{kind, at: [秒...], dur, yaw, pitch}，见 build_shot.apply_spray()
    spray: dict[str, Any] = field(default_factory=dict)
    # 变色。{at: [秒...], dur, color}。三娃铜头铁臂用
    tint: dict[str, Any] = field(default_factory=dict)
    # 隐身。{at: [秒...], dur}。人缩没 + 星星闪。六娃用
    vanish: dict[str, Any] = field(default_factory=dict)

    def asset_path(self, root: str = REPO_ROOT) -> str | None:
        if not self.asset:
            return None
        return os.path.join(root, "assets", self.asset)

    def has_asset(self, root: str = REPO_ROOT) -> bool:
        p = self.asset_path(root)
        return bool(p) and os.path.exists(p)


@dataclass
class Line:
    """一句台词。dur 是秒，用来驱动嘴的开合，不对口型。"""

    t: float
    who: str
    line: str
    dur: float = 1.0


@dataclass
class Camera:
    lens: float = 35.0
    keys: list[Key] = field(default_factory=list)


@dataclass
class Shot:
    id: str
    episode: str
    duration: float
    camera: Camera
    title: str = ""
    subjects: list[Subject] = field(default_factory=list)
    dialogue: list[Line] = field(default_factory=list)
    notes: str = ""
    source_path: str = ""

    def frame_count(self, fps: int) -> int:
        return max(1, round(self.duration * fps))

    @property
    def slug(self) -> str:
        return f"{self.episode}/{self.id}"


def _vec3(value: Any, where: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise SpecError(f"{where}: 需要三个数字，拿到 {value!r}")
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{where}: 三个值必须是数字，拿到 {value!r}") from exc


def _parse_key(raw: Any, where: str) -> Key:
    if not isinstance(raw, dict):
        raise SpecError(f"{where}: 关键帧必须是 mapping，拿到 {type(raw).__name__}")
    if "t" not in raw:
        raise SpecError(f"{where}: 关键帧缺 t")
    try:
        t = float(raw["t"])
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{where}.t: 必须是数字，拿到 {raw['t']!r}") from exc
    if t < 0:
        raise SpecError(f"{where}.t: 不能是负数，拿到 {t}")

    unknown = set(raw) - {"t", "loc", "rot", "scale"}
    if unknown:
        raise SpecError(f"{where}: 不认识的字段 {sorted(unknown)}")

    return Key(
        t=t,
        loc=_vec3(raw["loc"], f"{where}.loc") if "loc" in raw else None,
        rot=_vec3(raw["rot"], f"{where}.rot") if "rot" in raw else None,
        scale=_vec3(raw["scale"], f"{where}.scale") if "scale" in raw else None,
    )


def _check_keys(keys: list[Key], duration: float, where: str) -> None:
    if not keys:
        raise SpecError(f"{where}: 至少要一个关键帧")
    times = [k.t for k in keys]
    if times != sorted(times):
        raise SpecError(f"{where}: 关键帧的 t 必须递增，拿到 {times}")
    if len(set(times)) != len(times):
        raise SpecError(f"{where}: 有重复的 t，拿到 {times}")
    if times[-1] > duration + 1e-6:
        raise SpecError(f"{where}: 最后一个关键帧 t={times[-1]} 超出镜头时长 {duration}")


def load_style(path: str = DEFAULT_STYLE) -> dict[str, Any]:
    """读画质规格。缺必需段就直接报错，不给默认值 —— 规格必须显式。"""
    if tomllib is None:
        raise SpecError(
            "这个 Python 读不了 TOML（缺 tomli）。"
            "在 Blender 里请改用 pipeline/compile.py 生成的 plan JSON。"
        )
    if not os.path.exists(path):
        raise SpecError(f"找不到画质规格：{path}")
    with open(path, "rb") as fh:
        style = tomllib.load(fh)

    for section in ("timing", "render", "light", "shading", "motion", "camera"):
        if section not in style:
            raise SpecError(f"{path}: 缺 [{section}] 段")

    step = style["timing"].get("step", 1)
    if not isinstance(step, int) or step < 1:
        raise SpecError(f"{path}: timing.step 必须是 >=1 的整数，拿到 {step!r}")

    interp = style["motion"].get("interpolation")
    if interp not in {"LINEAR", "CONSTANT", "BEZIER"}:
        raise SpecError(
            f"{path}: motion.interpolation 只能是 LINEAR / CONSTANT / BEZIER，拿到 {interp!r}"
        )
    return style


def load_shot(path: str) -> Shot:
    """读一个镜头 YAML 并校验。有问题就抛 SpecError。"""
    if yaml is None:
        raise SpecError(
            "这个 Python 没有 PyYAML。"
            "在 Blender 里请改用 pipeline/compile.py 生成的 plan JSON。"
        )
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise SpecError(f"{path}: 顶层必须是 mapping")

    for required in ("id", "episode", "duration", "camera"):
        if required not in raw:
            raise SpecError(f"{path}: 缺字段 {required}")

    try:
        duration = float(raw["duration"])
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{path}: duration 必须是数字，拿到 {raw['duration']!r}") from exc
    if duration <= 0:
        raise SpecError(f"{path}: duration 必须 > 0，拿到 {duration}")

    cam_raw = raw["camera"]
    if not isinstance(cam_raw, dict):
        raise SpecError(f"{path}: camera 必须是 mapping")
    camera = Camera(
        lens=float(cam_raw.get("lens", 35.0)),
        keys=[
            _parse_key(k, f"{path}: camera.keys[{i}]")
            for i, k in enumerate(cam_raw.get("keys", []))
        ],
    )
    _check_keys(camera.keys, duration, f"{path}: camera.keys")

    subjects: list[Subject] = []
    for i, s_raw in enumerate(raw.get("subjects", [])):
        where = f"{path}: subjects[{i}]"
        if not isinstance(s_raw, dict) or "name" not in s_raw:
            raise SpecError(f"{where}: 必须是 mapping 且有 name")
        proxy = s_raw.get("proxy") or {}
        if proxy and proxy.get("kind") not in VALID_PROXY_KINDS:
            raise SpecError(
                f"{where}.proxy.kind: 只能是 {sorted(VALID_PROXY_KINDS)}，拿到 {proxy.get('kind')!r}"
            )
        if not s_raw.get("asset") and not proxy:
            raise SpecError(f"{where}: asset 和 proxy 至少要有一个")
        flash_raw = s_raw.get("flash") or []
        if not isinstance(flash_raw, (list, tuple)):
            raise SpecError(f"{where}.flash: 要一个时刻列表，拿到 {flash_raw!r}")
        flash: list[float] = []
        for j, ft in enumerate(flash_raw):
            try:
                ftv = float(ft)
            except (TypeError, ValueError) as exc:
                raise SpecError(f"{where}.flash[{j}]: 必须是数字，拿到 {ft!r}") from exc
            if ftv < 0 or ftv > duration + 1e-6:
                raise SpecError(
                    f"{where}.flash[{j}]: {ftv} 不在镜头时长 0~{duration} 之内")
            flash.append(ftv)
        if flash and not (s_raw.get("proxy") or {}).get("face", {}).get("eyes", False):
            raise SpecError(f"{where}.flash: 要闪眼睛，proxy.face.eyes 得是 true")

        spray = s_raw.get("spray") or {}
        if spray:
            if not isinstance(spray, dict):
                raise SpecError(f"{where}.spray: 要一个 mapping，拿到 {spray!r}")
            if spray.get("kind") not in VALID_SPRAY_KINDS:
                raise SpecError(
                    f"{where}.spray.kind: 只能是 {sorted(VALID_SPRAY_KINDS)}，"
                    f"拿到 {spray.get('kind')!r}")
            spray_at = spray.get("at") or []
            if not spray_at:
                raise SpecError(f"{where}.spray.at: 至少要一个时刻")
            spray_dur = float(spray.get("dur", 0.9))
            for j, st in enumerate(spray_at):
                stv = float(st)
                if stv < 0 or stv + spray_dur > duration + 1e-6:
                    raise SpecError(
                        f"{where}.spray.at[{j}]: {stv}+{spray_dur} 超出镜头时长 {duration}")

        subject = Subject(
            name=str(s_raw["name"]),
            asset=s_raw.get("asset"),
            proxy=proxy,
            keys=[
                _parse_key(k, f"{where}.keys[{j}]")
                for j, k in enumerate(s_raw.get("keys", []))
            ],
            flash=flash,
            spray=spray,
            tint=s_raw.get("tint") or {},
            vanish=s_raw.get("vanish") or {},
        )
        _check_keys(subject.keys, duration, f"{where}.keys")
        subjects.append(subject)

    names = [s.name for s in subjects]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise SpecError(f"{path}: subjects 里有重名 {sorted(dupes)}")

    dialogue: list[Line] = []
    for i, d_raw in enumerate(raw.get("dialogue", [])):
        where = f"{path}: dialogue[{i}]"
        if not isinstance(d_raw, dict):
            raise SpecError(f"{where}: 必须是 mapping")
        for required in ("t", "who", "line"):
            if required not in d_raw:
                raise SpecError(f"{where}: 缺字段 {required}")
        if d_raw["who"] not in names:
            raise SpecError(
                f"{where}.who: {d_raw['who']!r} 不在 subjects 里（有 {names}）"
            )
        t = float(d_raw["t"])
        dur = float(d_raw.get("dur", 1.0))
        if t + dur > duration + 1e-6:
            raise SpecError(f"{where}: 台词 t+dur={t + dur} 超出镜头时长 {duration}")
        dialogue.append(Line(t=t, who=str(d_raw["who"]), line=str(d_raw["line"]), dur=dur))

    return Shot(
        id=str(raw["id"]),
        episode=str(raw["episode"]),
        title=str(raw.get("title", "")),
        duration=duration,
        camera=camera,
        subjects=subjects,
        dialogue=dialogue,
        notes=str(raw.get("notes", "")),
        source_path=path,
    )


def find_shots(root: str = REPO_ROOT) -> list[str]:
    """列出 shots/ 下所有镜头文件，episode.yaml 不算镜头。"""
    found: list[str] = []
    shots_dir = os.path.join(root, "shots")
    for dirpath, _dirnames, filenames in os.walk(shots_dir):
        for name in sorted(filenames):
            if name.endswith((".yaml", ".yml")) and name != "episode.yaml":
                found.append(os.path.join(dirpath, name))
    return sorted(found)


# --------------------------------------------------------------------------
# plan：给 Blender 用的中间格式
#
# Blender 自带的 Python 没有 PyYAML，装进 app bundle 又会被下次升级抹掉。
# 所以多一道编译：系统 python3 把 YAML + TOML 合成一个纯 JSON 的 plan，
# Blender 只读 JSON，一个第三方依赖都不需要。
# 顺带的好处：plan 是渲染那一刻的完整快照，出了问题可以照着复现。
# --------------------------------------------------------------------------

def _key_to_dict(key: Key) -> dict[str, Any]:
    out: dict[str, Any] = {"t": key.t}
    if key.loc is not None:
        out["loc"] = list(key.loc)
    if key.rot is not None:
        out["rot"] = list(key.rot)
    if key.scale is not None:
        out["scale"] = list(key.scale)
    return out


def shot_to_dict(shot: Shot) -> dict[str, Any]:
    return {
        "id": shot.id,
        "episode": shot.episode,
        "title": shot.title,
        "duration": shot.duration,
        "notes": shot.notes,
        "source_path": shot.source_path,
        "camera": {
            "lens": shot.camera.lens,
            "keys": [_key_to_dict(k) for k in shot.camera.keys],
        },
        "subjects": [
            {
                "name": s.name,
                "asset": s.asset,
                "proxy": s.proxy,
                "keys": [_key_to_dict(k) for k in s.keys],
                "flash": s.flash,
                "spray": s.spray,
                "tint": s.tint,
                "vanish": s.vanish,
            }
            for s in shot.subjects
        ],
        "dialogue": [
            {"t": d.t, "who": d.who, "line": d.line, "dur": d.dur}
            for d in shot.dialogue
        ],
    }


def shot_from_dict(raw: dict[str, Any]) -> Shot:
    """plan JSON -> Shot。只用标准库，Blender 那边调这个。"""

    def keys(items: list[dict[str, Any]]) -> list[Key]:
        return [
            Key(
                t=float(k["t"]),
                loc=tuple(k["loc"]) if "loc" in k else None,
                rot=tuple(k["rot"]) if "rot" in k else None,
                scale=tuple(k["scale"]) if "scale" in k else None,
            )
            for k in items
        ]

    return Shot(
        id=raw["id"],
        episode=raw["episode"],
        title=raw.get("title", ""),
        duration=float(raw["duration"]),
        camera=Camera(
            lens=float(raw["camera"].get("lens", 35.0)),
            keys=keys(raw["camera"].get("keys", [])),
        ),
        subjects=[
            Subject(
                name=s["name"],
                asset=s.get("asset"),
                proxy=s.get("proxy") or {},
                keys=keys(s.get("keys", [])),
                flash=[float(f) for f in s.get("flash", [])],
                spray=s.get("spray") or {},
                tint=s.get("tint") or {},
                vanish=s.get("vanish") or {},
            )
            for s in raw.get("subjects", [])
        ],
        dialogue=[
            Line(t=float(d["t"]), who=d["who"], line=d["line"], dur=float(d.get("dur", 1.0)))
            for d in raw.get("dialogue", [])
        ],
        notes=raw.get("notes", ""),
        source_path=raw.get("source_path", ""),
    )

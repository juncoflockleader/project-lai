"""运镜校验的回归测试。纯标准库 + PyYAML，不需要 Blender，也不需要 pytest。

    python3 tests/test_camera_rules.py

tests/badcam/ 里每个文件都是一种**故意写坏**的运镜。一个只会说 OK 的校验器
没有价值，所以这里反过来断言：该拦的必须拦住，不该拦的不能误伤。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.shotspec import check_camera, load_shot, load_style  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# 文件名 -> (期望的运镜类型, 是否该判死)
CASES = {
    "curve":   ("linear_dolly", True),    # 三个点不共线 = 曲线运镜
    "orbit":   ("combined", True),        # 边推边转 = 跟拍/环绕
    "pantilt": ("combined", True),        # 俯仰和水平同时转 = 复合摇
    "roll":    ("linear_dolly", True),    # rot 的 Y 分量不为 0 = 横滚/斜角
    "tilt":    ("linear_tilt", True),     # 纯俯仰，不在 allowed_moves 里
    "speed":   ("linear_dolly", False),   # 直线但不匀速：只提示，不判死
}


def main() -> int:
    style = load_style()
    failures = []

    for name, (want_kind, want_reject) in sorted(CASES.items()):
        path = os.path.join(HERE, "badcam", f"{name}.yaml")
        shot = load_shot(path)
        kind, problems, notes = check_camera(shot, style)

        if kind != want_kind:
            failures.append(f"{name}: 运镜判成了 {kind}，应该是 {want_kind}")
        if want_reject and not problems:
            failures.append(f"{name}: 应该被拦住，但一个问题都没报")
        if not want_reject and problems:
            failures.append(f"{name}: 不该被拦，却报了 {problems}")

        mark = "拦住" if problems else "放过"
        extra = f"  提示{len(notes)}条" if notes else ""
        print(f"  {name:<8} {kind:<14} {mark}{extra}")

    # 正片里的镜头必须全过 —— 防止把规格改严之后自己的片子先崩了
    from pipeline.shotspec import find_shots
    for path in find_shots():
        shot = load_shot(path)
        kind, problems, _ = check_camera(shot, style)
        if problems:
            failures.append(f"{os.path.basename(path)}: 正片镜头不该被拦，却报了 {problems}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        return 1
    print(f"运镜校验测试全过（{len(CASES)} 个坏例子 + 正片全部镜头）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

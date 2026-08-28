"""project-lai 重制流水线。

模块分两类：
  - 纯 Python（shotspec / validate / assemble）：用系统 python3 跑，不依赖 Blender。
  - bpy 模块（build_shot / degrade / render）：只能在 Blender 内部跑。

所以这个 __init__ 不要 import 任何 bpy 模块。
"""

__version__ = "0.1.0"

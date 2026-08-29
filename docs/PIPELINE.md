# 流水线

## 数据流

```
shots/ep01/sh010.yaml   分镜（手写）
style/niulai.toml       画质规格（手写）
        │
        │  python3 -m pipeline.compile        ← 系统 Python，有 PyYAML
        ▼
out/ep01/sh010.plan.json   plan：一次渲染的完整快照
        │
        │  Blender -b -P pipeline/render.py   ← Blender 的 Python，只用标准库
        ▼
out/ep01/sh010/0000.png …  帧序列
        │
        │  python3 -m pipeline.assemble       ← ffmpeg
        ▼
out/ep01/sh010.mp4
```

一句话跑完：

```bash
make render SHOT=shots/ep01/sh010.yaml
```

## 为什么中间要有一道 compile

Blender 自带的 Python 里没有 PyYAML，也没有 `tomli`。往 app bundle 里 pip install
是能装，但下次 Blender 升级就没了，而且每台机器、每个 CI runner 都得再装一遍。

所以拆成两段：系统 Python 负责读 YAML/TOML、校验、编译；Blender 只读一个 JSON，
一个第三方依赖都不需要。附带三个好处：

1. **CI 不用装 Blender。** `.github/workflows/validate.yml` 在 ubuntu 上跑校验，几秒钟。
2. **plan 是可归档的快照。** 里面同时冻结了分镜和当时的画质规格，
   出了问题照着 plan 就能复现，不用猜当时 `niulai.toml` 是什么样。
3. **校验早于渲染。** 分镜写错了在编译阶段就报错，不会渲到一半才发现。

## 模块

| 模块 | 跑在哪 | 干什么 |
|---|---|---|
| `pipeline/shotspec.py` | 两边都能 import | 数据类 + 校验 + plan 的序列化/反序列化。`yaml`/`tomllib` 是可选依赖，缺了也 import 得动 |
| `pipeline/validate.py` | 系统 Python | 校验全部分镜，CI 跑的就是它 |
| `pipeline/compile.py` | 系统 Python | YAML + TOML → plan JSON |
| `pipeline/build_shot.py` | **只能在 Blender 里** | 搭场景：地面、角色（或积木代理）、摄影机、关键帧、口型 |
| `pipeline/degrade.py` | **只能在 Blender 里** | 施加画质规格。全是「关掉」，只有 `apply_step()` 是主动加工 |
| `pipeline/render.py` | **只能在 Blender 里** | 入口：读 plan → build → degrade → 渲帧 |
| `pipeline/assemble.py` | 系统 Python | 帧序列 → mp4，走 ffmpeg |

`pipeline/__init__.py` 里不许 import 任何 bpy 模块，否则系统 Python 那一侧全废。

## 两个踩过的坑，都在流水线层面

### 一、Blender 脚本报错，退出码还是 0

实测：`-b -P script.py` 里未捕获的异常 → 退出码 **0**；`sys.exit(n)` → 退出码 **n**。

后果是 `make render` 里渲染这步挂了，make 不知道，接着跑 assemble，
assemble 拿上一轮留在 `out/` 的旧帧照样拼出一个 mp4 —— 日志里有「写好了」
没有「渲完了」，不细看就当成功了，改的参数看着像没生效。

所以 `render.py` 的入口自己兜住异常并显式 `sys.exit(1)`。改这个文件的
入口部分时不要把那圈 try 去掉。

### 二、代理的物体级缩放会压扁挂上去的东西

`_box()` 是靠设 `obj.scale` 定尺寸的，join 之后这个缩放留在合并出来的物体上
（娃是 `(0.316, 0.172, 0.46)`）。角色自己渲出来没问题，网格已经除过了，
**但任何 parent 到它身上的东西都会被这一层缩放压扁**。

喷火喷水就是这么坏的：喷嘴局部 z=0.95（嘴），乘上 0.46 变成 0.437，
掉到胯上，还被非等比缩放挤成一个点。

修法是 **`_join()` 里一律 `_apply_scale()`**，凡是合并出来的物体 scale 都是 `(1,1,1)`。

这个坑咬过两次，第二次换了个样子：六娃隐身的星星也是 `_box` 拼的，join 出来自带
缩放 `(0.214, 0.016, 0.016)`，而开关动画又拿 `scale = 1.0` 去覆盖它 ——
等于把星星放大六十多倍，整个飞出画面，只在地上留下一道找不着来源的影子。

所以不要只在调用处补救。`_box()` 用 `obj.scale` 定尺寸是根，谁 join 谁中招。

### 三、渲染前不清目录，缩短镜头会拼出旧画面

把一个镜头从 2.0 秒改到 0.8 秒，`make render` 只写了新的 0000–0019，
上一版留下的 0020–0048 还在目录里，`assemble` 照单全收 ——
拼出来的片子比分镜长，**后半截是上一版的画面**。

更阴的是帧数统计：`render.py` 数的是目录里的 png，不是它实际渲了多少，
所以日志跟着一起报错数（说「渲完了 49 帧」，其实只渲了 20 帧）。

修法是 `render.py` 渲之前先清掉目录里的旧 png，并打印清了多少张。

这是「日志绿 ≠ 做对了」在这个项目里的**第三个变体**：

| # | 表现 | 根因 |
|---|---|---|
| 1 | 渲染报错，make 照跑 assemble，拼出旧帧 | Blender 脚本抛异常退出码仍是 0 |
| 2 | 相机变了但人没在跑，日志全绿时长也对 | 改分镜的正则缩进写错，字段没写进去 |
| 3 | 镜头改短了，成片却更长且后半截是旧的 | 输出目录不清，帧数又是数目录 |

共同点：**只要有一部分变了，就容易以为整个都对了。**
所以核对要落到具体的数 —— 帧数对不对得上 `duration × fps + 1`、
字段有没有真写进 YAML（`grep -c`）、退出码是不是零。

## 三步的顺序不能换

```
build_shot.build()  →  degrade.apply_all()  →  渲帧
```

`degrade.apply_step()` 要把动画重采样成 12fps 的顿挫感，它得先有关键帧可采。
如果在搭场景之前施加规格，曲线是空的，什么也不会发生，而且不报错 ——
渲出来只是动作变顺了，很容易漏掉。

## 积木代理

资产没建完的时候，`build_subject()` 拿 primitive 拼一个顶上：
`humanoid` `gourd` `rock` `tree` `snake` `box` 六种，见 `build_shot.PROXY_BUILDERS`。

这不是临时凑数。在这套画质规格下（平面着色、纯色材质、零反弹光照），
方块拼的人和精心建的人渲出来的差距远小于常规流水线，所以运镜、节奏、
时长可以先跑通，资产后补。分镜里 `asset` 和 `proxy` 可以同时写：
资产文件存在就用资产，不存在就退回代理，`make validate` 会列出哪些走了代理。

代理的原点由 `_origin_to_base()` 归到世界原点，也就是脚底 ——
join 之后原点默认落在第一个零件（人的话是头）上，不归零的话
分镜里的 `loc` 会把整个身子埋到地底下。

## 分镜 YAML 字段

```yaml
id: sh010                 # 必填，文件名去掉扩展名
episode: ep01             # 必填，所在目录名
title: 一句话说清这个镜头     # 选填
duration: 4.0             # 必填，秒

camera:
  lens: 35                # 焦距 mm
  keys:                   # 至少一个
    - {t: 0.0, loc: [0,-9,2.6], rot: [84,0,0]}

subjects:
  - name: yeye            # 必填，同一镜头内不能重名
    asset: characters/yeye.blend    # 选填，相对 assets/
    proxy: {kind: humanoid, height: 1.62, color: [0.62,0.48,0.36]}
    keys:
      - {t: 0.0, loc: [-1.6,0,0], rot: [0,0,18]}
    flash: [2.4, 3.0]       # 选填，眼睛闪烁的时刻（秒）。要 proxy.face.eyes = true
    spray:                  # 选填，喷火/喷水
      kind: fire            # fire | water
      at: [2.6]             # 什么时候喷（秒）
      dur: 1.4
      yaw: -52              # 绕 Z 偏多少度。别对着镜头喷，会被透视压成一个点
      pitch: 48             # 绕 X，90 是正前方，小于 90 往上抬

dialogue:
  - {t: 0.6, who: yeye, line: "这个山，要塌。", dur: 1.4}

notes: |
  给人看的，不进渲染。
```

- `t` 是秒，不是帧。帧号由 `t * fps` 算，fps 在画质规格里。
- `rot` 是角度，不是弧度。
- `keys` 的 `t` 必须递增、不能重复、不能超过 `duration`。
- `asset` 和 `proxy` 至少要有一个。
- `flash` 是 subject 级的，不在 proxy 里 —— 它是动画不是几何。时刻要落在 `duration` 内。
- `dialogue[].who` 必须在 `subjects` 里，`t + dur` 不能超过 `duration`。

校验器会逐条检查这些，报错带文件名和字段路径。

## 运镜校验

`style/niulai.toml` 的 `[camera].allowed_moves` 从「写在文档里的一句话」变成了
可执行的检查。`make validate` 会给每个镜头判一个类型：

| 类型 | 判定 |
|---|---|
| `static` | 位置和角度都不变 |
| `linear_dolly` | 只动位置，且路径是直线 |
| `linear_pan` | 只转水平角 |
| `linear_tilt` | 只转俯仰角（**不在默认准用列表里**） |
| `combined` | 位置和角度同时变，或俯仰和水平同时转 |

四条硬伤会判死：路径是曲线、推的时候还转（跟拍/环绕）、俯仰和水平同时转
（复合摇）、`rot` 的 Y 分量不为 0（横滚/斜角）。判出来的类型再对照
`allowed_moves`，不在里面就报错，并提示要么改分镜、要么把它加进 toml。

变焦不用判：`lens` 是镜头级的标量，关键帧里放 `lens` 会被 `_parse_key`
以「不认识的字段」直接拒掉。

「直线但不匀速」只出提示不判死 —— 手工片里「先停一下再推」是合理的。

判定逻辑在 `pipeline/shotspec.py` 的 `classify_camera_move()` / `check_camera()`。

### 校验器自己也要被校验

`tests/badcam/` 下面是六个**故意写坏**的运镜，`make test` 断言该拦的拦得住、
不该拦的不误伤，顺带断言正片七个镜头一个都不该被拦。

一个只会说 OK 的校验器没有价值。加规则的时候先往 `tests/badcam/` 里放一个
会触发它的反例，再去写判定。

## 常用命令

```bash
make validate                              # 校验全部分镜和运镜，不需要 Blender
make test                                  # 跑运镜校验的回归测试
make render SHOT=shots/ep01/sh020.yaml     # 渲一个镜头
make preview SHOT=shots/ep01/sh020.yaml    # 只搭场景，存 .blend 出来手动看
make all                                   # 渲全部
make clean                                 # 删 out/
```

Blender 不在默认路径的话：`make render BLENDER=/path/to/blender`。

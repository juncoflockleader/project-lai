# 牛来 画质规格

这份文档是 `style/niulai.toml` 的说明书。每一条是一个观察，配一个配置键，
再配一句「为什么不修」。改配置之前先读对应的条目。

参照物：《牛来》(2026)，信雨萌导演、孙丽芳编剧作曲，两人五年，二手电脑，
用 SketchUp 一帧一帧手打关键帧，中途烧过主板。

**总原则：这套规格里绝大多数条目是「关掉」，不是「打开」。**
牛来 的画质不是加了什么效果做出来的，是所有现代渲染管线默认打开的东西
它都没有。我们要复现的是这个「没有」，不是模仿它的失误。

---

## 一、几何与材质

### 1. 硬边，不倒角
SketchUp 是建筑软件，推拉出来的面天然是硬的，没有人会在里面做倒角。
→ `[shading].force_flat_shading = true`，`degrade.py` 把所有多边形 `use_smooth = False`。
建模阶段也不许加 bevel，见 `assets/characters/README.md`。

### 2. 原始几何拼装，面数低
角色是方块和球拼的，不是雕的。球用 8 段，有明显的棱。
→ `[shading].decimate_ratio = 0.35`，超过 500 面的物体会被砍。
→ 代理生成器 `build_shot._proxy_*` 直接用 primitive 拼。

### 3. 纯色材质，没有贴图
没有 albedo 贴图，没有法线贴图，没有粗糙度变化。一个物体一个色。
→ `[shading].roughness = 1.0`、`specular = 0.0`、`metallic = 0.0`、
  `strip_normal_maps = true`。
高光是「专业感」的最大来源，关掉它一步到位。

---

## 二、光照

### 4. 一个太阳，零反弹
没有补光，没有环境光遮蔽，没有全局光照。背光面就是死黑往上提一点点。
→ `[light].max_bounces = 0`，`degrade.apply_light()` 会先删掉场景里所有灯再建一个。
→ 引擎选 EEVEE，它天生没有 GI，正好省事。

### 5. 阴影是绝对硬边
太阳角直径设成 0，阴影边缘一个像素的过渡都没有，像贴纸剪出来的。
→ `[light].sun_angle_deg = 0.0`。

---

## 三、渲染

### 6. 不抗锯齿
斜边上的台阶是这套画质最显眼的签名。
→ `[render].samples = 1`（EEVEE TAA 采样 1 次）
→ `[render].filter_size = 0.01`（Blender 允许的最小值，把像素滤波也压掉）

### 7. 没有大气
没有雾、没有体积光、没有辉光、没有耀斑。天空是一块纯色，
和地面之间是一条硬地平线。
→ `[light].world_color` + `world_strength`，`[render].use_bloom = false`。
分镜里凡是原片有烟有光效的地方，一律不补。

### 8. 色彩管理要生的
Blender 默认的 AgX / Filmic 会把高光滚下来，看着就「像电影」。关掉。
→ `[render].view_transform = "Standard"`、`look = "None"`。

### 9. 不降噪、不景深、不运动模糊
→ `[render].use_denoise = false`、`use_motion_blur = false`、`[camera].use_dof = false`。

---

## 四、动作

### 10. 线性插值，没有缓动
匀速起步，匀速停住，没有加速度。这是手打关键帧不做曲线编辑的必然结果。
→ `[motion].interpolation = "LINEAR"`，`degrade.apply_interpolation()` 会把
  所有关键帧的插值和 easing 全部推平。

### 11. 有效帧率 12
动作一格一格地蹦。
→ `[timing].fps = 24` + `step = 2`。
→ 实现在 `degrade.apply_step()`：先按原曲线求值，再只在 step 的整数倍帧上
  打点、插值改 `CONSTANT`。底下仍是匀速运动，看上去是顿的。
**注意这是全片唯一一处主动「加工」，其余都是关掉。**

### 12. 不做 IK，脚会滑
角色平移的时候脚不锁地。
→ `[motion].foot_lock = false`。这条目前是声明性的：代理本来就没骨骼，
  关键帧打在整个物体上。建资产的时候也别加骨骼。

### 13. 口型只开合，不对位
嘴按固定频率抖，和音轨对不上。
→ `[motion].lipsync = "flap"`、`lipsync_hz = 6.0`，实现在 `build_shot.apply_lipsync()`。
→ 目前代理没有分离的嘴，用整体 Z 轴微缩放（1.03 倍）顶替，读作「在说话」。
  等角色资产建好，改成驱动一个独立的嘴部物体。

---

## 五、运镜与声音

### 14. 只有静止、直线推、直线摇
没有手持，没有环绕，没有变焦，没有跟随。
→ `[camera].allowed_moves = ["static", "linear_dolly", "linear_pan"]`。
这条目前靠人守，校验器还没检查（见 `docs/ROADMAP.md`）。

### 15. 音频不做响度归一
忽大忽小是特征。
→ `[audio].normalize = false`。

---

## 什么不算 牛来

有几件事看着像，其实是别的东西，不要往这个方向做：

- **故意做丑的贴图**（手绘涂鸦、错位 UV）。牛来 没有贴图，不是贴图做得丑。
- **抖动的手持镜头**。牛来 的镜头是死的，不是晃的。
- **低分辨率 / 压缩噪点**。牛来 是 2K 交付的，糊在几何和光照上，不在码率上。
- **复古滤镜、扫描线、VHS**。那是另一种审美，是「加」，方向相反。
- **穿模、破面、渲染错误**。这些是 bug，不是风格。要能重复渲出同样的结果。

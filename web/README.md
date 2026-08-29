# 网页勘景

第一人称走进已经建好的布景里看。`web/kanjing.html` 是自包含的单文件，
双击就能开（或者 `python3 -m http.server --directory web`）。

**没有用任何三维库。** 渲染器是手写的画家算法，一百多行：

- 平涂，一个面一个色，光照在导出时就烘进颜色里 —— 平涂着色不随视角变，
  所以网页这边不用算光，颜色和渲出来的帧是同一套
- 画布 480×270，用 CSS `image-rendering: pixelated` 放大 ——
  低分辨率放大正好对上规格里「不抗锯齿」那条，不是将就
- 近平面裁剪。不裁的话，跨在相机后面的多边形会投影成满屏乱线
- 按面的平均深度排序，远的先画

**为什么不用 three.js。** Artifact 的 CSP 挡掉所有外部脚本，从 CDN 加载不进去；
把六百多 KB 的库下下来内联也不合适。而我们的规格本来就不需要它 ——
没有贴图、没有透明、没有柔和阴影、没有抗锯齿，剩下的东西手写就够了。

## 重新生成

```bash
python3 -m pipeline.compile shots/mgm/sh040.yaml
/Applications/Blender.app/Contents/MacOS/Blender -b -P pipeline/export_web.py -- \
    --plan out/mgm/sh040.plan.json --out web/scene_mgm.json
python3 web/build.py          # 把场景内联进 kanjing.html
```

`--frame N` 可以导某一帧的状态（比如 ep01/sh070 取第 100 帧，
那时候火和水正喷着）。

`web/scene_*.json` 是中间产物，不入库；`kanjing.html` 入库，因为它是成品。

## 一个踩过的坑

镜头级的 `stage.world_color` 覆盖原来只写在 `render.py` 里，导出器没有 ——
结果迷宫在网页里天是蓝的，渲出来是紫的。同一个设置两处实现，漏了一处。
现在抽成 `shotspec.apply_stage()`，两边共用。

**另外：HTML 要写 `<meta charset="utf-8">`。** 不写的话 `python3 -m http.server`
不带 charset，浏览器按 latin-1 解，中文全是乱码。

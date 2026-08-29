"""把场景 JSON 内联进一个自包含的 HTML。

内联而不是 fetch —— file:// 下 fetch 会被 CORS 挡掉，而且自包含的单文件
才能当 Artifact 发。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES = [("scene_teng.json", "葫芦藤（第一集 sh070）"),
          ("scene_mgm.json",  "魔女（迷宫 sh040）"),
          ("scene_grid.json", "阵列（迷宫 sh020）")]

def main():
    data = []
    for fn, label in SCENES:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            print(f"缺 {fn}，跳过"); continue
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        d["label"] = label
        data.append(d)
    if not data:
        print("一个场景都没有"); return 1

    tpl = open(os.path.join(HERE, "kanjing.tpl.html"), encoding="utf-8").read()
    out = tpl.replace("/*__SCENES__*/", json.dumps(data, separators=(",", ":")))
    dst = os.path.join(HERE, "kanjing.html")
    open(dst, "w", encoding="utf-8").write(out)
    total = sum(len(d["faces"]) for d in data)
    print(f"写好了 {dst}：{len(data)} 个场景，{total} 个面，"
          f"{os.path.getsize(dst)/1024:.0f} KB")
    return 0

if __name__ == "__main__":
    sys.exit(main())

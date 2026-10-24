# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""宣传片素材准备：从一次真实运行的 _autocut/ 目录和生成的剪映草稿里取数据，输出 build/data.js 和图片。

用法: uv run --script prepare.py <_autocut 目录> <剪映草稿目录> <白名单 clip_id,时间;...>

隐私：只有白名单里的「人工逐秒核对过没有人」的风景画面会清晰出现；其余缩略图一律打成大马赛克。
"""
import csv
import json
import os
import subprocess
import sys

from PIL import Image

W, DRAFT, WHITELIST = sys.argv[1], sys.argv[2], sys.argv[3]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
A = os.path.join(OUT, "assets")
os.makedirs(A, exist_ok=True)

inv = list(csv.DictReader(open(f"{W}/inventory.csv", encoding="utf-8-sig")))
by_id = {r["clip_id"]: r for r in inv}
by_path = {r["path"]: r["clip_id"] for r in inv}
white = [(c, float(t)) for c, t in (x.split("@") for x in WHITELIST.split(";"))]
white_ids = {c for c, _ in white}


def mosaic(src, dst, w=192, h=108):
    im = Image.open(src).convert("RGB").resize((w, h))
    im.resize((8, 5), Image.BILINEAR).resize((w, h), Image.NEAREST).save(dst, quality=85)


def grab(clip, t, dst, width=1600):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", by_id[clip]["path"], "-frames:v", "1",
                    "-vf", f"scale={width}:-2", "-q:v", "3", dst], check=True)


# 1 风景大图（白名单）
heroes = []
for c, t in white:
    p = f"hero_{c}_{int(t)}.jpg"
    grab(c, t, os.path.join(A, p))
    heroes.append(p)

# 2 素材墙：每段素材一格；白名单素材用清晰风景帧，其余打马赛克
thumbs = sorted(os.listdir(f"{W}/thumbs"))
wall = []
for r in inv:
    cid = r["clip_id"]
    p = f"wall_{cid}.jpg"
    if cid in white_ids:
        t = next(t for c, t in white if c == cid)
        grab(cid, t, os.path.join(A, p), width=192)
    else:
        first = next((f for f in thumbs if f.startswith(cid + "_")), None)
        if not first:
            continue
        mosaic(f"{W}/thumbs/{first}", os.path.join(A, p))
    wall.append({"id": cid, "img": p, "clear": cid in white_ids})

# 3 坏帧示例（无人：全黑帧、挂着晃拍的歪倒帧）
bad = []
for name, label in [("c056_0004.00.jpg", "过暗"), ("c024_0204.00.jpg", "歪倒"), ("c024_0060.00.jpg", "歪倒")]:
    Image.open(f"{W}/thumbs/{name}").convert("RGB").save(os.path.join(A, "bad_" + name), quality=90)
    bad.append({"img": "bad_" + name, "label": label, "id": name[:4]})
frames = list(csv.DictReader(open(f"{W}/frames.csv", encoding="utf-8-sig")))
_o = json.load(open(f"{W}/orientation.json"))
orient = _o["clips"]
c024_tilted = sum(v in ("tilt", "flip") for v in _o["labels"].get("c024", {}).values())

# 4 MiMo 的画面描述（只取白名单风景素材）
cu = json.load(open(f"{W}/clip_understanding.json"))
captions = []
for c, t in white:
    sc = cu.get(c, {}).get("scenes", [])
    if sc:
        txt = sc[0]["description"]
        captions.append({"id": c, "img": f"hero_{c}_{int(t)}.jpg", "text": txt if len(txt) <= 46 else txt[:45] + "…"})

# 5 故事与分镜
story = json.load(open(f"{W}/story_plan.json"))
shots = list(csv.DictReader(open(f"{W}/shots.csv", encoding="utf-8-sig")))
order, seen = [], set()
for s in shots:
    if s["chapter"] not in seen:
        seen.add(s["chapter"])
        order.append(s["chapter"])
chap_meta = {str(i + 1): ch for i, ch in enumerate(story["chapters"])}
chapters = []
for no in order:
    ch = chap_meta[no]
    dur = sum(int(s["dur_us"]) for s in shots if s["chapter"] == no) / 1e6
    chapters.append({"no": no, "title": ch["title"], "function": ch.get("function", ""),
                     "intercut": bool(ch.get("intercut")), "dur": round(dur, 1)})
b_line = {cid for ch in story["chapters"] if ch.get("intercut") for cid in ch["intercut"].get("b", [])}
shot_rows = [{"start": int(s["start_us"]) / 1e6, "dur": int(s["dur_us"]) / 1e6, "chapter": s["chapter"],
              "kind": s["kind"], "b": by_path.get(s["source"]) in b_line} for s in shots]

# 6 剪映草稿的轨道
#   草稿被剪映打开过就加密了（本项目的已知限制），读不回来时用生成它的同一份输入重建：
#   视频轨 = shots.csv，标题轨 = 每章开头 3 秒，BGM 轨 = build.bgm_segments（同一个函数）
try:
    d = json.load(open(os.path.join(DRAFT, "draft_info.json")))
    tracks = [{"type": t["type"], "n": len(t["segments"]),
               "segs": [[s["target_timerange"]["start"] / 1e6, s["target_timerange"]["duration"] / 1e6]
                        for s in t["segments"]]} for t in d["tracks"]]
    version, canvas = d["new_version"], f'{d["canvas_config"]["width"]}×{d["canvas_config"]["height"]}'
except (json.JSONDecodeError, UnicodeDecodeError):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
    from common import detect_versions
    bgm = os.environ["PROMO_BGM"]       # 生成草稿时用的那首歌，只用来取时长
    song = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", bgm],
                                capture_output=True, text=True).stdout)
    total_us = sum(int(s["dur_us"]) for s in shots)
    segs, t0 = [], 0
    while t0 < total_us:                 # 与 build.bgm_segments 相同的循环规则
        dd = min(round(song * 1e6), total_us - t0)
        segs.append([t0 / 1e6, dd / 1e6])
        t0 += dd
    firsts = {}
    for s in shots:
        firsts.setdefault(s["chapter"], int(s["start_us"]) / 1e6)
    tracks = [{"type": "video", "n": len(shots), "segs": [[r["start"], r["dur"]] for r in shot_rows_tmp]}
              for shot_rows_tmp in [[{"start": int(s["start_us"]) / 1e6, "dur": int(s["dur_us"]) / 1e6} for s in shots]]]
    tracks += [{"type": "text", "n": len(firsts), "segs": [[v, 3.0] for v in firsts.values()]},
               {"type": "audio", "n": len(segs), "segs": segs}]
    version = detect_versions()["new_version"]
    canvas = "3840×2160"
    print("草稿已被剪映加密，轨道按生成输入重建")

total_s = sum(float(r["duration_s"]) for r in inv)
data = {
    "folder": {"clips": len(inv), "minutes": round(total_s / 60), "gb": round(sum(float(r["size_mb"]) for r in inv) / 1024, 1)},
    "inventory": [{"id": r["clip_id"], "name": r["name"], "dur": float(r["duration_s"]),
                   "res": f'{r["width"]}×{r["height"]}', "fps": r["fps"]} for r in inv[10:40]],
    "frames": {"n": len(frames), "bad": sum(int(f["bad"]) for f in frames)},
    "orient": {"unusable": [c for c, v in orient.items() if v.get("unusable")],
               "c024_bad": c024_tilted,
               "c024_total": len([f for f in frames if f["clip_id"] == "c024"])},
    "heroes": heroes, "wall": wall, "bad": bad, "captions": captions,
    "chapters": chapters, "shots": shot_rows, "total": round(sum(r["dur"] for r in shot_rows), 3),
    "draft": {"name": os.path.basename(DRAFT.rstrip("/")), "version": version, "canvas": canvas, "tracks": tracks},
}
with open(os.path.join(OUT, "data.js"), "w", encoding="utf-8") as f:
    f.write("window.DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")
print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in data.items() if k != "draft"}, ensure_ascii=False))
print("draft tracks:", [(t["type"], t["n"]) for t in tracks])

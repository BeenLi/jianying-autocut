# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""第 3 步 画面方向：把 Claude 看联系表的判断写成 orientation.json（第 5、6 步会读）

用法: uv run --script orient.py --work W [--flip c012,c013] [--unusable c020] [--bad c005@12,c005@20]

  --flip      整段上下颠倒（运动相机倒挂等），草稿里转 180°
  --unusable  大半画面歪倒（挂在胸前晃着拍等），整段不用
  --bad       个别歪倒的帧，写法是 素材@联系表上的秒数；挑镜头时避开

联系表上的秒数是四舍五入后的，这里换回 frames.csv 里的精确抽帧时间。每次运行都重写整个文件。
"""
import argparse
import json
import os
from collections import defaultdict

from common import read_csv

MAX_LABEL_ERROR = 1.0    # 联系表秒数与真实抽帧时间最多差这么多，超过说明写错了


def build_orientation(frames, flip=(), unusable=(), bad=()):
    """frames: {clip_id: [抽帧秒数]} → orientation.json 的内容。写错素材或时间时抛 ValueError。"""
    def times_of(cid, spec):
        if cid not in frames:
            raise ValueError(f"{spec}：frames.csv 里没有素材 {cid}")
        return frames[cid]

    clips = {}
    for cid in flip:
        times_of(cid, cid)
        clips[cid] = {"rotate": 180, "bad": []}
    for spec in bad:
        cid, _, t = spec.partition("@")
        times = times_of(cid, spec)
        nearest = min(times, key=lambda x: abs(x - float(t)))
        if abs(nearest - float(t)) > MAX_LABEL_ERROR:
            raise ValueError(f"{spec}：这段素材在这个时间附近没有抽帧")
        clips.setdefault(cid, {"rotate": 0, "bad": []})["bad"].append(nearest)
    for cid in unusable:
        clips[cid] = {"rotate": 0, "bad": sorted(times_of(cid, cid)), "unusable": True}
    return {"clips": clips}


def _ids(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--flip", default="")
    ap.add_argument("--unusable", default="")
    ap.add_argument("--bad", default="")
    args = ap.parse_args()

    frames = defaultdict(list)
    for f in read_csv(os.path.join(args.work, "frames.csv")):
        frames[f["clip_id"]].append(float(f["t"]))
    try:
        out = build_orientation(frames, _ids(args.flip), _ids(args.unusable), _ids(args.bad))
    except ValueError as e:
        raise SystemExit(str(e))
    path = os.path.join(args.work, "orientation.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(out['clips'])} 段素材有方向标记 → {path}")


if __name__ == "__main__":
    main()

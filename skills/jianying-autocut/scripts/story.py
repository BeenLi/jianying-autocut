# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""第 4 步 故事脚本 → story_plan.json（第 5 步唯一认的格式）

用法:
  uv run --script story.py --work W --check               # 校验 Claude 写的 story_plan.json 并打印
  uv run --script story.py --work W --default --chapters 5  # 没写故事：按拍摄时间间隔切章（兜底）
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

from common import read_csv
from plan import RHYTHMS

EDGE_S = 0.5


def _ts(row):
    try:
        return datetime.fromisoformat(row["shot_time"].replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def default_chapters(inv_rows, n):
    """按拍摄时间间隔最大的 n-1 处断开，得到 n 章。"""
    rows = sorted(inv_rows, key=lambda r: (r["shot_time"], r["clip_id"]))
    n = max(1, min(n, len(rows)))
    gaps = sorted(range(1, len(rows)), key=lambda i: _ts(rows[i]) - _ts(rows[i - 1]), reverse=True)[: n - 1]
    bounds = [0] + sorted(gaps) + [len(rows)]
    out = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
        cs = rows[a:b]
        out.append({"id": f"ch{i}", "title": f"第{i}章 {cs[0]['shot_time'][5:16].replace('T', ' ')}",
                    "function": "setup", "clip_ids": [r["clip_id"] for r in cs], "pool": "own", "pins": []})
    return out


def usable_seconds(work):
    """每段素材的可用秒数：去掉首尾各 0.5s，再按坏帧比例打折（与第 5 步的估算一致）。"""
    inv = read_csv(os.path.join(work, "inventory.csv"))
    bad = {}
    fp = os.path.join(work, "frames.csv")
    if os.path.exists(fp):
        for f in read_csv(fp):
            bad.setdefault(f["clip_id"], []).append(int(f["bad"]))
    out = {}
    for r in inv:
        b = bad.get(r["clip_id"], [])
        ratio = sum(b) / len(b) if b else 0.0
        out[r["clip_id"]] = max(0.0, float(r["duration_s"]) - 2 * EDGE_S) * (1 - ratio)
    return inv, out


def _expand_ids(spec):
    """'c002,c059-c062' → {'c002','c059','c060','c061','c062'}"""
    out = set()
    for part in filter(None, (p.strip() for p in (spec or "").split(","))):
        m = re.fullmatch(r"c(\d+)-c?(\d+)", part)
        if m:
            width = len(m.group(1))
            out |= {f"c{i:0{width}d}" for i in range(int(m.group(1)), int(m.group(2)) + 1)}
        else:
            out.add(part)
    return out


def apply_exclude(plan, spec):
    """把与主题无关的素材（日常、测试镜头、别的行程）从所有章节和 pins 里剔除；剔空的章节丢弃。"""
    drop = _expand_ids(spec)
    if not drop:
        return plan
    chapters = []
    for ch in plan["chapters"]:
        ch = dict(ch, clip_ids=[c for c in ch["clip_ids"] if c not in drop],
                  pins=[p for p in ch.get("pins", []) if p.get("clip_id") not in drop])
        if ch["clip_ids"] or ch.get("pool") == "all":
            chapters.append(ch)
    return dict(plan, chapters=chapters)


def validate(plan, inv_ids):
    errs = []
    seen = set()
    for ch in plan.get("chapters", []):
        for c in ch.get("clip_ids", []):
            if c not in inv_ids:
                errs.append(f"章节 {ch.get('id')} 引用了不存在的素材 {c}")
            if c in seen and ch.get("pool") != "all":
                errs.append(f"素材 {c} 出现在多个章节")
            seen.add(c)
        for p in ch.get("pins", []):
            if p.get("clip_id") not in inv_ids:
                errs.append(f"章节 {ch.get('id')} 的 pin 引用了不存在的素材 {p.get('clip_id')}")
        ic = ch.get("intercut")
        if ic:
            for line in ("a", "b"):
                extra = [c for c in ic.get(line, []) if c not in ch.get("clip_ids", [])]
                if extra:
                    errs.append(f"章节 {ch.get('id')} 的 intercut.{line} 含不在本章 clip_ids 里的素材 {extra}")
            if not ic.get("a") or not ic.get("b"):
                errs.append(f"章节 {ch.get('id')} 的 intercut 需要 a、b 两条线都有素材")
            if ic.get("end_on", "a") not in ("a", "b"):
                errs.append(f"章节 {ch.get('id')} 的 intercut.end_on 只能是 a 或 b")
        if ch.get("rhythm") and ch["rhythm"] not in RHYTHMS:
            errs.append(f"章节 {ch.get('id')} 的 rhythm 只能是 {'/'.join(RHYTHMS)}")
        if ch.get("share") is not None and not 0 < float(ch["share"]) < 1:
            errs.append(f"章节 {ch.get('id')} 的 share 必须在 0~1 之间")
    if sum(float(ch.get("share") or 0) for ch in plan.get("chapters", [])) > 1:
        errs.append("各章 share 之和超过 1")
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--default", action="store_true")
    mode.add_argument("--check", action="store_true")
    ap.add_argument("--chapters", type=int, default=5)
    ap.add_argument("--exclude", default="", help="剔除无关素材，如 c059-c062,c024")
    args = ap.parse_args()

    inv, usable = usable_seconds(args.work)
    out_path = os.path.join(args.work, "story_plan.json")
    if args.default:
        plan = {"director_intent": "", "chapters": default_chapters(inv, args.chapters)}
    else:
        with open(out_path, encoding="utf-8") as f:
            plan = json.load(f)

    if args.exclude:
        plan = apply_exclude(plan, args.exclude)
        if args.check:   # --check 本来只读；带了 --exclude 就把剔除结果写回
            args.check = False
    errs = validate(plan, {r["clip_id"] for r in inv})
    if errs:
        sys.exit("story_plan 有问题：\n  " + "\n  ".join(errs))
    if not args.check:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=1)

    if plan.get("director_intent"):
        print(f"导演意图：{plan['director_intent']}")
    print(f"{'章节':<16} {'功能':<10} {'素材':>4} {'可用':>7}  pins")
    for ch in plan["chapters"]:
        s = sum(usable.get(c, 0) for c in ch["clip_ids"])
        print(f"{ch['title'][:16]:<16} {ch.get('function', ''):<10} {len(ch['clip_ids']):>4} {s:>6.0f}s  "
              f"{len(ch.get('pins', []))}" + (f"  share={ch['share']}" if ch.get("share") else ""))
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()

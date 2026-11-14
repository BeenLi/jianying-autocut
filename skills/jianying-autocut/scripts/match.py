# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""第 4c 步 拍摄脚本 + 素材对照表 → story_plan.json（模式 B）

用法:
  uv run --script match.py --work W

读 W/shoot_plan.json（章节、镜头）、W/matches.json（镜头 ↔ 素材对照、计划外素材）、W/inventory.csv，
只认用户在页面上确认过的对照：已确认的对照变成 pins，镜头所属章决定素材进哪章。
有未确认的对照或格式错误就报错退出，不写 story_plan.json。格式见 references/shoot_plan.md。
"""
import argparse
import json
import math
import os
import sys

from common import US, load_json, read_csv
from plan import FUNCTION_RHYTHM, GAP, RHYTHMS
from story import validate as story_validate

MERGE_S = 1.0     # 同章同素材两个 pin 相差不到 1 秒：plan.py 会因窗口已占用跳过第二个，这里先合并并报出来


def load_inputs(work):
    """返回 (shoot_plan, matches, durations)；durations 是 clip_id → 素材时长（秒）。"""
    shoot_plan = load_json(os.path.join(work, "shoot_plan.json"), kind=dict)
    matches = load_json(os.path.join(work, "matches.json"), kind=dict)
    durations = {r["clip_id"]: float(r["duration_s"]) for r in read_csv(os.path.join(work, "inventory.csv"))}
    return shoot_plan, matches, durations


def to_seconds(v):
    """数字、数字字符串、"m:ss" 或 "h:mm:ss" → 秒；解析不了返回 None（页面输入框可能把秒数存成字符串）。
    规则与页面的 num() 一致：每一段都要是非空的数字。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    parts = str(v).strip().split(":")
    if len(parts) > 3 or any(not p.strip() for p in parts):
        return None
    try:
        t = 0.0
        for p in parts:
            t = t * 60 + float(p)
    except ValueError:
        return None
    return t if math.isfinite(t) else None


def _check_at(prefix, cid, at, durations, errs):
    if cid not in durations:
        errs.append(f"{prefix}：素材 {cid} 不在 inventory.csv")
        return None
    t = to_seconds(at)
    if t is None or not 0 <= t <= durations[cid]:
        errs.append(f"{prefix}：秒数 {at} 无效（素材 {cid} 时长 {durations[cid]:g}s）")
        return None
    return t


def _structure_errors(shoot_plan, matches):
    """数据结构本身不对时（页面导出或手写出错），先报出来，免得后面 KeyError。"""
    errs = []
    for key in ("chapters", "shots"):
        v = shoot_plan.get(key, [])
        if not isinstance(v, list):
            errs.append(f"shoot_plan.json 的 {key} 应该是列表")
            continue
        for k, x in enumerate(v, 1):
            if not isinstance(x, dict) or not x.get("id"):
                errs.append(f"shoot_plan.json 的 {key} 第 {k} 项缺 id")
    for key in ("matches", "extras"):
        v = matches.get(key, {})
        if not isinstance(v, dict) or not all(isinstance(x, dict) for x in v.values()):
            errs.append(f"matches.json 的 {key} 应该是 {{id: {{…}}}} 形式的对象")
    return errs


def validate(shoot_plan, matches, durations):
    errs = _structure_errors(shoot_plan, matches)
    if errs:
        return errs
    chapters = {ch["id"]: ch for ch in shoot_plan.get("chapters", [])}
    for ch in chapters.values():
        if ch.get("function") not in FUNCTION_RHYTHM:
            errs.append(f"章 {ch['id']}：function 只能是 {'/'.join(FUNCTION_RHYTHM)}")
        if ch.get("rhythm") and ch["rhythm"] not in RHYTHMS:
            errs.append(f"章 {ch['id']}：rhythm 只能是 {'/'.join(RHYTHMS)}")
    shots = {s["id"]: s for s in shoot_plan.get("shots", [])}
    for s in shots.values():
        if s.get("chapter") not in chapters:
            errs.append(f"镜头 {s['id']}：所属章 {s.get('chapter')} 不存在")

    for sid, m in matches.get("matches", {}).items():
        prefix = f"匹配 {sid}"
        if sid not in shots:
            errs.append(f"{prefix}：没有这个镜头")
        t = _check_at(prefix, m.get("clip_id"), m.get("at"), durations, errs)
        start, end = to_seconds(m.get("start")), to_seconds(m.get("end"))
        if t is not None and (m.get("start") is not None or m.get("end") is not None):
            if start is None or end is None or not start < t < end:
                errs.append(f"{prefix}：口播范围 start/end 不包住 at")
        if m.get("confirmed") is not True:
            errs.append(f"{prefix}：还没确认，请先在页面上确认或删除")

    for cid, x in matches.get("extras", {}).items():
        if x.get("accepted") is not True:      # 还没决定或已拒绝的不进成片，数据有误也不挡生成
            continue
        prefix = f"计划外素材 {cid}"
        if x.get("chapter") not in chapters:
            errs.append(f"{prefix}：章 {x.get('chapter')} 不存在")
        _check_at(prefix, cid, x.get("at"), durations, errs)
    return errs


def build_story_plan(shoot_plan, matches):
    """返回 (story_plan, report)。只用 confirmed 的对照和 accepted 的计划外素材；没有 pin 的章不输出。"""
    shots = sorted(shoot_plan.get("shots", []), key=lambda s: (s.get("order", 0), s["id"]))
    confirmed = {sid: m for sid, m in matches.get("matches", {}).items() if m.get("confirmed") is True}
    extras = matches.get("extras", {})
    report = {"missing": {}, "dropped_chapters": [], "rejected_extras": 0, "merged_pins": [], "long_talk": [],
              "pending_extras": [cid for cid, x in extras.items() if x.get("accepted") is None],
              "odd_extras": [cid for cid, x in extras.items() if x.get("accepted") not in (True, False, None)],
              "cross_pins": []}
    report["rejected_extras"] = sum(1 for x in extras.values() if x.get("accepted") is False)

    out, placed = [], []
    for ch in sorted(shoot_plan.get("chapters", []), key=lambda c: (c.get("order", 0), c["id"])):
        wanted = []
        for s in shots:
            if s.get("chapter") != ch["id"]:
                continue
            if s["id"] in confirmed:
                m = confirmed[s["id"]]
                start, end = to_seconds(m.get("start")), to_seconds(m.get("end"))
                # 口播的整句范围随 pin 传给 plan.py（cover），镜头至少盖住它；整句比本章最长镜头还长时仍会被剪断
                cover = [start, end] if start is not None and end is not None and end > start else None
                wanted.append((m["clip_id"], to_seconds(m["at"]), cover))
                longest = max(hi for _, _, hi in RHYTHMS[ch.get("rhythm") or FUNCTION_RHYTHM[ch["function"]]])
                if start is not None and end is not None and end - start > longest:
                    report["long_talk"].append((s["id"], round(end - start, 1), longest))
            else:
                report["missing"].setdefault(ch["id"], []).append(s["id"])
        wanted += [(cid, to_seconds(x["at"]), None) for cid, x in extras.items()
                   if x.get("chapter") == ch["id"] and x.get("accepted") is True]
        pins = []
        for cid, at, cover in wanted:
            near = next((p for p in pins if p["clip_id"] == cid and abs(p["at"] - at) < MERGE_S), None)
            if near:
                report["merged_pins"].append((cid, near["at"], at))
            else:
                pins.append({"clip_id": cid, "at": at, **({"cover": cover} if cover else {})})
        if not pins:
            report["dropped_chapters"].append(ch["id"])
            continue
        # 跨章同素材：plan.py 按章序放 pin，前一章的镜头以 pin 为中心、最长到本章节奏上限，
        # 加上同素材间隔 GAP，后一章落在这个范围里的 pin 会因为窗口被占而跳过
        reach = max(hi for _, _, hi in RHYTHMS[ch.get("rhythm") or FUNCTION_RHYTHM[ch["function"]]]) / 2 + GAP / US
        for p in pins:
            for prev_ch, q, prev_reach in placed:
                if q["clip_id"] == p["clip_id"] and abs(q["at"] - p["at"]) < prev_reach:
                    report["cross_pins"].append((p["clip_id"], q["at"], prev_ch, p["at"], ch["id"]))
        placed += [(ch["id"], p, reach) for p in pins]
        c = {"id": ch["id"], "title": ch.get("title", ch["id"]), "function": ch["function"]}
        if ch.get("rhythm"):
            c["rhythm"] = ch["rhythm"]
        c.update(clip_ids=list(dict.fromkeys(p["clip_id"] for p in pins)), pool="own", pins=pins)
        out.append(c)
    story = {"director_intent": shoot_plan.get("meta", {}).get("intent", ""), "chapters": out}
    return story, report


def _print_report(shoot_plan, story, report, durations, out_path):
    titles = {ch["id"]: ch.get("title", "") for ch in shoot_plan.get("chapters", [])}
    for ch_id, sids in report["missing"].items():
        print(f"漏拍：{ch_id} {titles.get(ch_id, '')}：{'、'.join(sids)}")
    for ch_id in report["dropped_chapters"]:
        print(f"整章没有素材，已删除：{ch_id} {titles.get(ch_id, '')}")
    if report["pending_extras"]:
        print(f"计划外素材待决定 {len(report['pending_extras'])} 段：{'、'.join(report['pending_extras'])}"
              f"（请在页面上采纳或拒绝）")
    if report["rejected_extras"]:
        print(f"计划外素材已拒绝 {report['rejected_extras']} 段")
    for cid in report["odd_extras"]:
        print(f"⚠ 计划外素材 {cid} 的 accepted 不是 true / false / null，按待决定处理（没进成片）")
    for cid, a, ch_a, b, ch_b in report["cross_pins"]:
        print(f"⚠ {cid} @{a:g}s（{titles.get(ch_a, ch_a)}）和 @{b:g}s（{titles.get(ch_b, ch_b)}）离得太近："
              f"前一章会先拿走这段，后一章的这个 pin 会被跳过。换一段素材，或把其中一个时间点挪开")
    for cid, kept, dropped in report["merged_pins"]:
        print(f"合并了相差不到 {MERGE_S:g} 秒的 pin：{cid} @{kept:g} / {dropped:g}")
    for sid, length, longest in report["long_talk"]:
        print(f"⚠ 口播 {sid} 整句 {length:g}s，超过本章节奏最长镜头 {longest}s，会被剪断：把这章 rhythm 改成 slow，或在页面上缩短口播")
    used = {c for ch in story["chapters"] for c in ch["clip_ids"]}
    unused = sorted(set(durations) - used)
    if unused:
        print(f"未被任何章引用的素材 {len(unused)} 段：{'、'.join(unused)}（不进成片）")
    print(f"→ {out_path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    args = ap.parse_args(argv)

    shoot_plan, matches, durations = load_inputs(args.work)
    errs = validate(shoot_plan, matches, durations)
    if errs:
        print("拍摄脚本或对照表有问题：\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    story, report = build_story_plan(shoot_plan, matches)
    if not story["chapters"]:
        print("没有任何已确认的匹配，没法生成故事", file=sys.stderr)
        return 1
    errs = story_validate(story, set(durations))
    if errs:
        print("生成的 story_plan 有问题：\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    out_path = os.path.join(args.work, "story_plan.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=1)
    _print_report(shoot_plan, story, report, durations, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

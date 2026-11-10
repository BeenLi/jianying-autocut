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
import os
import sys

from common import read_csv
from plan import FUNCTION_RHYTHM, RHYTHMS
from story import validate as story_validate

MERGE_S = 1.0     # 同章同素材两个 pin 相差不到 1 秒：plan.py 会因窗口已占用跳过第二个，这里先合并并报出来


def load_inputs(work):
    """返回 (shoot_plan, matches, durations)；durations 是 clip_id → 素材时长（秒）。"""
    with open(os.path.join(work, "shoot_plan.json"), encoding="utf-8") as f:
        shoot_plan = json.load(f)
    with open(os.path.join(work, "matches.json"), encoding="utf-8") as f:
        matches = json.load(f)
    durations = {r["clip_id"]: float(r["duration_s"]) for r in read_csv(os.path.join(work, "inventory.csv"))}
    return shoot_plan, matches, durations


def to_seconds(v):
    """数字、数字字符串或 "m:ss" → 秒；解析不了返回 None（页面输入框可能把秒数存成字符串）。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return None


def _check_at(prefix, cid, at, durations, errs):
    if cid not in durations:
        errs.append(f"{prefix}：素材 {cid} 不在 inventory.csv")
        return None
    t = to_seconds(at)
    if t is None or not 0 <= t <= durations[cid]:
        errs.append(f"{prefix}：秒数 {at} 无效（素材 {cid} 时长 {durations[cid]:g}s）")
        return None
    return t


def validate(shoot_plan, matches, durations):
    errs = []
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
              "pending_extras": [cid for cid, x in extras.items() if x.get("accepted") is None]}
    report["rejected_extras"] = sum(1 for x in extras.values() if x.get("accepted") is False)

    out = []
    for ch in sorted(shoot_plan.get("chapters", []), key=lambda c: (c.get("order", 0), c["id"])):
        wanted = []
        for s in shots:
            if s.get("chapter") != ch["id"]:
                continue
            if s["id"] in confirmed:
                m = confirmed[s["id"]]
                wanted.append((m["clip_id"], to_seconds(m["at"])))
                # pin 只带一个时间点，镜头长度由节奏决定：整句比本章最长镜头还长，必然被剪断
                start, end = to_seconds(m.get("start")), to_seconds(m.get("end"))
                longest = max(hi for _, _, hi in RHYTHMS[ch.get("rhythm") or FUNCTION_RHYTHM[ch["function"]]])
                if start is not None and end is not None and end - start > longest:
                    report["long_talk"].append((s["id"], round(end - start, 1), longest))
            else:
                report["missing"].setdefault(ch["id"], []).append(s["id"])
        wanted += [(cid, to_seconds(x["at"])) for cid, x in extras.items()
                   if x.get("chapter") == ch["id"] and x.get("accepted") is True]
        pins = []
        for cid, at in wanted:
            near = next((p for p in pins if p["clip_id"] == cid and abs(p["at"] - at) < MERGE_S), None)
            if near:
                report["merged_pins"].append((cid, near["at"], at))
            else:
                pins.append({"clip_id": cid, "at": at})
        if not pins:
            report["dropped_chapters"].append(ch["id"])
            continue
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
    for cid, kept, dropped in report["merged_pins"]:
        print(f"合并了相差不到 {MERGE_S:g} 秒的 pin：{cid} @{kept:g} / {dropped:g}")
    for sid, length, longest in report["long_talk"]:
        print(f"⚠ 口播 {sid} 整句 {length:g}s，超过本章节奏最长镜头 {longest}s，会被剪断：把这章 rhythm 改成 slow，或在页面上缩短口播")
    used = {c for ch in story["chapters"] for c in ch["clip_ids"]}
    print(f"未被任何章引用的素材 {len(set(durations) - used)} 段（不进成片）")
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

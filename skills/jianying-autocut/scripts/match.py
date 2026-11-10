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
import json
import os

from common import read_csv
from plan import FUNCTION_RHYTHM, RHYTHMS


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

"""把 narration_track.json 的 fx 段写进剪映草稿：预检、挂效果、读回自检（build.py 调用）。

库的两个行为决定了写法：
  · 片段上的转场 / 滤镜 / 动画材料只在 script.add_segment() 那一刻收进草稿，所以要先挂效果再入轨；
  · add_animation(OutroType) 用「片段长度 − 动画时长」算起点、不截短，时长已在 narrate 里截好。
"""
from pyJianYingDraft import Timerange, TrackSpec, TrackType

import fx
from fx_catalog import SOURCES

EFFECT_TRACK = "特效"
LIST_KIND = {"transitions": "transition", "effects": "effect", "filters": "filter"}


def member(kind, name, catalog):
    """显示名 → 枚举成员（用目录里的 member，不用库的 from_name）。"""
    e = catalog.get(kind, {}).get(name)
    try:
        return getattr(SOURCES[kind][0], e["member"])
    except (TypeError, KeyError, AttributeError):
        raise KeyError(f"{fx.LABEL[kind]} {name} 不在效果目录里") from None


def _entries(f):
    """[(kind, 条目)]：五类效果拉平。"""
    out = [(LIST_KIND[k], e) for k in LIST_KIND for e in f.get(k, [])]
    return out + [(k, f[k]) for k in ("intro", "outro") if f.get(k)]


def preflight(f, shots, catalog):
    """在删旧草稿之前查：指纹、行号、时间、名字。返回错误列表（空 = 通过）。"""
    errs = []
    if f.get("shots_sig") != fx.shots_sig(shots):
        errs.append("shots.csv 和 narration_track.json 不是同一次 narrate 的结果（shots_sig 对不上）")
    bad_idx = [k for k, r in enumerate(shots, 1) if str(r.get("idx")) != str(k)]
    if bad_idx:
        errs.append(f"shots.csv 的 idx 不是从 1 连续编号（第 {bad_idx[0]} 行的 idx 是 {shots[bad_idx[0] - 1].get('idx')}）")
    total = sum(int(r["dur_us"]) for r in shots)
    for kind, e in _entries(f):
        what = f"{fx.LABEL[kind]} {e.get('type')}"
        try:
            member(kind, e.get("type"), catalog)
        except KeyError as x:
            errs.append(str(x).strip("'\""))
        if kind == "effect":
            if not (0 <= e["start_us"] and e["dur_us"] > 0 and e["start_us"] + e["dur_us"] <= total):
                errs.append(f"{what} 的时间 {e['start_us']}+{e['dur_us']} 超出成片 {total}")
            continue
        n = e.get("shot")
        if not isinstance(n, int) or not 1 <= n <= len(shots):
            errs.append(f"{what} 指向第 {n} 个镜头，shots.csv 只有 {len(shots)} 行")
            continue
        r = shots[n - 1]
        if kind == "transition" and e.get("at_us") != int(r["start_us"]) + int(r["dur_us"]):
            errs.append(f"{what} 的切点 {e.get('at_us')} 和第 {n} 个镜头的终点 {int(r['start_us']) + int(r['dur_us'])} 对不上")
        if "start_us" in e and e["start_us"] != int(r["start_us"]):
            errs.append(f"{what} 的起点 {e['start_us']} 和第 {n} 个镜头的起点 {r['start_us']} 对不上")
    return [x + "（重跑 narrate.py）" for x in errs]


def by_shot(f):
    """行号 → [(kind, 条目)]：建片段时一并挂上的效果（特效走特效轨，不在这里）。"""
    out = {}
    for kind, e in _entries(f):
        if kind != "effect":
            out.setdefault(e["shot"], []).append((kind, e))
    return out


def attach(seg, entries, catalog):
    """在 add_segment 之前调用。"""
    for kind, e in entries:
        m = member(kind, e["type"], catalog)
        if kind == "transition":
            seg.add_transition(m, duration=e["dur_us"])
        elif kind == "filter":
            seg.add_filter(m, e["intensity"])
        else:
            seg.add_animation(m, e["dur_us"])


def add_effects(script, f, catalog):
    effects = f.get("effects", [])
    if effects:
        script.append_track(TrackSpec(TrackType.effect, EFFECT_TRACK))
    for e in effects:
        script.add_effect(member("effect", e["type"], catalog), Timerange(e["start_us"], e["dur_us"]), track_name=EFFECT_TRACK)
    return len(effects)


def summary(f):
    n = {k: len(f.get(k, [])) for k in LIST_KIND}
    anim = sum(bool(f.get(k)) for k in ("intro", "outro"))
    s = f"转场 {n['transitions']} 个、特效 {n['effects']} 个、滤镜 {n['filters']} 个、片头片尾动画 {anim} 个"
    vip = fx.vip_list(f)
    return s + (f"；会员：{'、'.join(vip)}" if vip else "")

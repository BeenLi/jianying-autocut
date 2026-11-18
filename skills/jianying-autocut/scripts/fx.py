# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""旁白片的效果字段：转场、画面特效、滤镜、片头 / 片尾动画（不依赖 pyJianYingDraft）

narration_plan.json 里的写法（都可省，没有时行为不变）：
  item.transition = {type, dur?, reason?}      切进这一项时的转场（秒，省略用目录默认值）
  item.effect     = {type, reason?}            特效轨，覆盖这一项的最终槽
  visuals[i].filter = {type, intensity?, reason?}   这个画面产出的所有镜头（0–100，省略为 100）
  intro / outro   = {type, reason?}            第一个镜头的入场 / 最后一个镜头的出场动画
type 是剪映里的中文显示名，查 assets/fx_catalog.json（fx_catalog.py 生成）。
"""
import difflib
import json
import math
import os

US = 1_000_000
CATALOG_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fx_catalog.json"))
KEYS = {"transition": {"type", "dur", "reason"}, "effect": {"type", "reason"}, "filter": {"type", "intensity", "reason"},
        "intro": {"type", "reason"}, "outro": {"type", "reason"}}
LABEL = {"transition": "转场", "effect": "特效", "filter": "滤镜", "intro": "片头", "outro": "片尾"}
FX_MAX_TRANSITIONS = 8
FX_MAX_EFFECTS = 3
FX_MIN_US = 100_000


def load_catalog(path=None):
    path = path or CATALOG_PATH
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"效果目录 {path} 读不了：重跑 fx_catalog.py（{e}）") from None


def _item_fx(it):
    """一项里的效果字段：[(kind, 值, 位置说明)]，滤镜带画面下标。"""
    out = [(k, it[k], k) for k in ("transition", "effect") if k in it]
    for i, v in enumerate(it.get("visuals") or []):
        if isinstance(v, dict) and "filter" in v:
            out.append(("filter", v["filter"], f"visuals[{i}].filter"))
    return out


def has_fx(plan):
    return "intro" in plan or "outro" in plan or any(
        _item_fx(it) for it in plan.get("items", []) if isinstance(it, dict))


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check(kind, val, where, catalog):
    """一个效果对象的格式错误（列表）。"""
    if not isinstance(val, dict) or not isinstance(val.get("type"), str):
        return [f"{where} 要写成 {{\"type\": \"剪映里的名字\", …}}，现在是 {val!r}"]
    errs = []
    extra = sorted(set(val) - KEYS[kind])
    if extra:
        errs.append(f"{where} 有不认识的键 {'、'.join(extra)}（只能写 {'、'.join(sorted(KEYS[kind]))}）")
    names = catalog.get(kind, {})
    if val["type"] not in names:
        near = difflib.get_close_matches(val["type"], list(names), n=3, cutoff=0.34)   # 中文名短，差一个字相似度就只有 0.5
        errs.append(f"{where}：剪映里没有{LABEL[kind]}「{val['type']}」" + (f"，是不是 {'、'.join(near)}？" if near else ""))
    if "dur" in val:
        d = val["dur"]
        if not _num(d) or d <= 0 or round(d * US) <= 0:
            errs.append(f"{where} 的 dur 要是正的秒数，现在是 {d!r}")
    if "intensity" in val:
        x = val["intensity"]
        if not _num(x) or not 0 <= x <= 100:
            errs.append(f"{where} 的 intensity 要在 0–100 之间，现在是 {x!r}")
    return errs


def validate_fx(plan, catalog):
    """(errs, warns)。只查格式和名字；生效与否要等排完镜头（compute_fx）。"""
    errs, warns = [], []
    for k in ("intro", "outro"):
        if k in plan:
            errs += _check(k, plan[k], k, catalog)
    first = next((it for it in plan.get("items", []) if isinstance(it, dict) and not it.get("skip")), None)
    n_tr = n_fx = 0
    for it in plan.get("items", []):
        if not isinstance(it, dict):
            continue
        iid = it.get("id", "?")
        for kind, val, where in _item_fx(it):
            errs += [f"{iid}：{e}" for e in _check(kind, val, where, catalog)]
            if it.get("skip"):
                warns.append(f"{iid}：这一项被跳过了，{LABEL[kind]}不生效")
                continue
            if kind == "transition":
                n_tr += 1
                if it is first:
                    errs.append(f"{iid}：第一项前面没有镜头，不能写转场；片头动画用顶层的 intro")
            elif kind == "effect":
                n_fx += 1
    if n_tr > FX_MAX_TRANSITIONS:
        warns.append(f"转场 {n_tr} 个，超过建议的 {FX_MAX_TRANSITIONS} 个：只在故事节点用")
    if n_fx > FX_MAX_EFFECTS:
        warns.append(f"特效 {n_fx} 个，超过建议的 {FX_MAX_EFFECTS} 个：只留给高潮瞬间")
    return errs, warns

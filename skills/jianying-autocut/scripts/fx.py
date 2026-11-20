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
import hashlib
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
            cat = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"效果目录 {path} 读不了：重跑 fx_catalog.py（{e}）") from None
    bad = _catalog_problem(cat)
    if bad:
        raise ValueError(f"效果目录 {path} 结构不对（{bad}）：重跑 fx_catalog.py")
    return cat


def _catalog_problem(cat):
    """目录结构的第一个问题；没问题返回 None。结构坏了的目录不能当成「名字不存在」报给用户。"""
    if not isinstance(cat, dict):
        return "顶层不是对象"
    for kind in KEYS:
        if not isinstance(cat.get(kind), dict) or not cat[kind]:
            return f"缺少 {kind}"
        need = ("member", "resource_id", "vip") + (("dur",) if kind in ("transition", "intro", "outro") else ())
        for name, e in cat[kind].items():
            if not isinstance(e, dict) or any(k not in e for k in need):
                return f"{kind}/{name} 缺字段"
    return None


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


# ---------- 排完镜头之后：算出每个效果落在哪 ----------

SIG_VERSION = "v2"


def shots_sig(rows, clip_ids=None):
    """shots 的指纹：idx、kind、clip_id、in_us、start_us、dur_us 按顺序拼起来取 sha1，前面带版本号。
    用 clip_id 而不是素材路径：派生目录把素材换成同名调色副本时 clip_id 不变，指纹也不变；换成另一段素材就变。
    clip_ids 与 rows 一一对应；不给时取每行的 clip_id（build 按 inventory 补上的）。
    narrate 的整数行和 read_csv 读出来的字符串行算出来一样；build 用它确认 track 和 shots.csv 出自同一次 narrate。"""
    ids = clip_ids if clip_ids is not None else [r["clip_id"] for r in rows]
    text = "\n".join(f"{int(r['idx'])}|{r['kind']}|{cid}|{int(r['in_us'])}|{int(r['start_us'])}|{int(r['dur_us'])}"
                     for r, cid in zip(rows, ids, strict=True))
    return f"{SIG_VERSION}:sha1:" + hashlib.sha1(text.encode("utf-8")).hexdigest()


def _s(us):
    return f"{us / US:g}s"


def compute_fx(plan, rows, srcs, slots, catalog):
    """(fx | None, warns, notes)。rows / srcs / slots 是 layout 的最终结果（srcs 与 rows 一一对应）。
    notes：item_id → ["转场 叠化 0.6s", …]，给 dry-run 打印。一个生效的效果都没有时 fx 是 None。"""
    items = {it["id"]: it for it in plan.get("items", [])}
    warns, notes = [], {}
    first = {}
    for r, s in enumerate(srcs):
        first.setdefault(s["item"], r)

    def note(iid, text):
        notes.setdefault(iid, []).append(text)

    out = {"transitions": [], "effects": [], "filters": []}
    for sl in slots:
        iid = sl["item"]
        it = items[iid]
        tr = it.get("transition")
        if tr:
            e = catalog["transition"][tr["type"]]
            r = first.get(iid)
            if not r:      # None：这一项没有自己的镜头；0：它就是全片第一个镜头（校验已拦住，兜底）
                warns.append(f"{iid}：没有自己的镜头（槽太短，被上一句延长吞掉了），转场 {tr['type']} 忽略")
            else:
                d = round(tr["dur"] * US) if "dur" in tr else round(e["dur"] * US)
                lim = min(int(rows[r - 1]["dur_us"]), int(rows[r]["dur_us"])) // 2
                if d > lim:
                    warns.append(f"{iid}：转场 {tr['type']} {_s(d)} 比两侧较短镜头的一半长，截到 {_s(lim)}")
                    d = lim
                if d < FX_MIN_US:
                    warns.append(f"{iid}：转场 {tr['type']} 截短后只有 {_s(d)}，太短，忽略")
                else:
                    out["transitions"].append({"shot": int(rows[r - 1]["idx"]), "at_us": int(rows[r]["start_us"]),
                                               "type": tr["type"], "dur_us": d, "item": iid, "vip": e["vip"]})
                    note(iid, f"转场 {tr['type']} {_s(d)}")
        ef = it.get("effect")
        if ef:
            out["effects"].append({"start_us": sl["start_us"], "dur_us": sl["end_us"] - sl["start_us"], "type": ef["type"],
                                   "item": iid, "vip": catalog["effect"][ef["type"]]["vip"]})
            note(iid, f"特效 {ef['type']}")
        for i, v in enumerate(it.get("visuals") or []):
            fl = v.get("filter") if isinstance(v, dict) else None
            if not fl:
                continue
            mine = [r for r, s in enumerate(srcs) if s["item"] == iid and s["vis"] == i]
            if not mine:
                used = [rows[r]["source"] for r, s in enumerate(srcs) if s["item"] == iid]
                if not used:
                    why = "这句没有自己的镜头（被上一句延长吞掉了）"
                else:
                    names = "、".join(dict.fromkeys(os.path.splitext(os.path.basename(p))[0] for p in used))
                    why = f"第 {i + 1} 个画面 {v.get('clip_id')} 没用上（这句用的是 {names}）"
                warns.append(f"{iid}：{why}，滤镜 {fl['type']} 忽略")
                continue
            x = fl.get("intensity", 100)
            for r in mine:
                out["filters"].append({"shot": int(rows[r]["idx"]), "start_us": int(rows[r]["start_us"]), "type": fl["type"],
                                       "intensity": x, "item": iid, "vip": catalog["filter"][fl["type"]]["vip"]})
            note(iid, f"滤镜 {fl['type']} {x:g}")
    if rows:
        both = len(rows) == 1 and plan.get("intro") and plan.get("outro")
        for kind, r in (("intro", 0), ("outro", len(rows) - 1)):
            a = plan.get(kind)
            if not a:
                continue
            e = catalog[kind][a["type"]]
            d, lim = round(e["dur"] * US), int(rows[r]["dur_us"]) // (2 if both else 1)
            if d > lim:
                warns.append(f"{LABEL[kind]} {a['type']} {_s(d)} 比镜头长，截到 {_s(lim)}")
                d = lim
            if d < FX_MIN_US:
                warns.append(f"{LABEL[kind]} {a['type']} 截短后只有 {_s(d)}，太短，忽略")
                continue
            out[kind] = {"shot": int(rows[r]["idx"]), "type": a["type"], "dur_us": d, "vip": e["vip"]}
            note(srcs[r]["item"], f"{LABEL[kind]} {a['type']} {_s(d)}")
    if not any(out[k] for k in out):
        return None, warns, notes
    return {"shots_sig": shots_sig(rows, [s["clip_id"] for s in srcs]), **out}, warns, notes


def vip_list(fx):
    """会员项：["星光叠化（L11）", "片头 xx"]。"""
    out = [f"{e['type']}（{e['item']}）" for k in ("transitions", "effects", "filters") for e in fx.get(k, []) if e.get("vip")]
    out += [f"{LABEL[k]} {fx[k]['type']}" for k in ("intro", "outro") if fx.get(k, {}).get("vip")]
    return list(dict.fromkeys(out))

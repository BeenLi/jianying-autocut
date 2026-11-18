# /// script
# requires-python = ">=3.10"
# dependencies = ["pyJianYingDraft @ git+https://github.com/aoguai/pyJianYingDraft@69cee12ae3f7442416df16acdf368ae574764811"]
# ///
"""效果目录：把 pyJianYingDraft 的转场 / 特效 / 滤镜 / 入场 / 出场枚举导出成 assets/fx_catalog.json

用法: uv run --script fx_catalog.py      # 升级 pyJianYingDraft 之后重跑一次，把 JSON 一起提交

键是剪映里的中文显示名（「闪白 II」「X-Signal」），member 是 Python 成员名（「闪白_II」「X_Signal」）。
build 用 getattr(枚举, member) 取成员；不用库的 from_name()，它查的是成员名，显示名带特殊字符时查不到。
narrate.py 只读这份 JSON，不依赖 pyJianYingDraft。
"""
import json
import os

from pyJianYingDraft import FilterType, IntroType, OutroType, TransitionType, VideoSceneEffectType

LIB = "pyJianYingDraft@69cee12"
CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fx_catalog.json")
CATALOG_PATH = os.path.normpath(CATALOG_PATH)
SOURCES = {
    "transition": (TransitionType, "name"),
    "effect": (VideoSceneEffectType, "name"),
    "filter": (FilterType, "name"),
    "intro": (IntroType, "title"),
    "outro": (OutroType, "title"),
}


def _dur_s(meta):
    us = getattr(meta, "default_duration", None) or getattr(meta, "duration", None)
    return round(us / 1e6, 6) if us else None


def build_catalog(sources=SOURCES):
    """{"lib": …, 类: {显示名: {member, resource_id, vip[, dur]}}}；显示名重名时 ValueError。"""
    out, dups = {"lib": LIB}, []
    for kind, (enum, field) in sources.items():
        seen, cat = {}, {}
        for m in enum:
            name = getattr(m.value, field)
            if name in seen:
                dups.append(f"{kind}/{name}: {seen[name]}, {m.name}")
                continue
            seen[name] = m.name
            e = {"member": m.name, "resource_id": m.value.resource_id, "vip": bool(m.value.is_vip)}
            d = _dur_s(m.value)
            if d is not None:
                e["dur"] = d
            cat[name] = e
        out[kind] = cat
    if dups:
        raise ValueError("显示名重名，要在 fx_catalog.py 里加消歧规则：\n  " + "\n  ".join(dups))
    return out


def main():
    cat = build_catalog()
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=0, sort_keys=True)
    for kind in SOURCES:
        free = sum(not e["vip"] for e in cat[kind].values())
        print(f"  {kind:<10} {len(cat[kind]):>5} 条（免费 {free}）")
    print(f"→ {CATALOG_PATH}")


if __name__ == "__main__":
    main()

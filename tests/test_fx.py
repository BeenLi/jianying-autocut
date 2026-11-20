import json
import math

import pytest

import fx
from test_narrate import _line, _plan

CAT = {"lib": "test",
       "transition": {"叠化": {"member": "叠化", "resource_id": "1", "vip": False, "dur": 0.5},
                      "闪白": {"member": "闪白", "resource_id": "2", "vip": False, "dur": 0.5},
                      "星光叠化": {"member": "星光叠化", "resource_id": "3", "vip": True, "dur": 0.5}},
       "effect": {"冲击波": {"member": "冲击波", "resource_id": "4", "vip": False}},
       "filter": {"夏日风吟": {"member": "夏日风吟", "resource_id": "5", "vip": False}},
       "intro": {"渐显": {"member": "渐显", "resource_id": "6", "vip": False, "dur": 0.5}},
       "outro": {"渐隐": {"member": "渐隐", "resource_id": "7", "vip": False, "dur": 0.5}}}


def _v(*items, **top):
    p = _plan(*items)
    p.update(top)
    return fx.validate_fx(p, CAT)


def _two(**kw):
    return [_line("L1", 0, 1), _line("L2", 2, 3, **kw)]


# ---------- 校验 ----------

def test_unknown_name_suggests():
    errs, _ = _v(*_two(transition={"type": "叠画"}))
    assert len(errs) == 1 and "L2" in errs[0] and "叠化" in errs[0]


def test_unknown_key():
    errs, _ = _v(*_two(transition={"type": "叠化", "durr": 1}))
    assert len(errs) == 1 and "durr" in errs[0]


@pytest.mark.parametrize("val", ["叠化", {}, {"type": None}])
def test_not_object_or_missing_type(val):
    errs, _ = _v(*_two(transition=val))
    assert len(errs) == 1 and "L2" in errs[0]


@pytest.mark.parametrize("dur", ["1", True, math.nan, math.inf, 0, -1, 1e-7])
def test_dur_bad(dur):
    errs, _ = _v(*_two(transition={"type": "叠化", "dur": dur}))
    assert len(errs) == 1 and "dur" in errs[0]


@pytest.mark.parametrize("val,bad", [(True, True), ("60", True), (math.nan, True), (-1, True), (101, True),
                                     (0, False), (100, False), (60.5, False)])
def test_intensity_bad(val, bad):
    vis = [{"clip_id": "c1", "filter": {"type": "夏日风吟", "intensity": val}}]
    errs, _ = _v(_line("L1", 0, 1, visuals=vis))
    assert bool(errs) == bad, errs


def test_filter_unknown_name_and_key():
    vis = [{"clip_id": "c1", "filter": {"type": "夏日", "strength": 3}}]
    errs, _ = _v(_line("L1", 0, 1, visuals=vis))
    assert len(errs) == 2


def test_top_level_intro_outro():
    errs, _ = _v(_line("L1", 0, 1), intro={"type": "渐显"}, outro={"type": "渐显"})
    assert len(errs) == 1 and "outro" in errs[0]
    errs, _ = _v(_line("L1", 0, 1), intro={"type": "渐显", "dur": 1})
    assert len(errs) == 1 and "dur" in errs[0]


def test_transition_on_first_kept_item():
    errs, _ = _v(_line("L1", 0, 1, transition={"type": "叠化"}), _line("L2", 2, 3))
    assert len(errs) == 1 and "L1" in errs[0] and "intro" in errs[0]
    errs, _ = _v(_line("L0", 0, 1, skip=True), _line("L1", 2, 3, transition={"type": "叠化"}))
    assert len(errs) == 1 and "L1" in errs[0]


def test_skipped_item_fx_warns():
    vis = [{"clip_id": "c1", "filter": {"type": "夏日风吟"}}]
    errs, warns = _v(_line("L1", 0, 1),
                     _line("L2", 2, 3, skip=True, transition={"type": "叠化"}, effect={"type": "冲击波"}, visuals=vis))
    assert errs == [] and len(warns) == 3 and all("L2" in w for w in warns)


def test_limits_warn():
    items = [_line("L0", 0, 1)] + [_line(f"L{k}", k, k + 0.5, transition={"type": "叠化"}, effect={"type": "冲击波"})
                                   for k in range(1, 10)]
    errs, warns = _v(*items)
    assert errs == []
    assert sum("转场" in w for w in warns) == 1 and sum("特效" in w for w in warns) == 1


def test_has_fx():
    assert not fx.has_fx(_plan(_line("L1", 0, 1, visuals=[{"clip_id": "c1"}])))
    assert fx.has_fx(_plan(_line("L1", 0, 1), ), ) is False
    assert fx.has_fx(dict(_plan(_line("L1", 0, 1)), intro={"type": "渐显"}))
    assert fx.has_fx(_plan(_line("L1", 0, 1, visuals=[{"clip_id": "c1", "filter": {"type": "夏日风吟"}}])))


def test_load_catalog_missing(tmp_path):
    with pytest.raises(ValueError, match="重跑 fx_catalog.py"):
        fx.load_catalog(str(tmp_path / "nope.json"))
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(ValueError, match="重跑 fx_catalog.py"):
        fx.load_catalog(str(tmp_path / "bad.json"))


def test_real_catalog_loads():
    cat = fx.load_catalog()
    assert "叠化" in cat["transition"] and json.dumps(cat)


# ---------- 计算 fx（排完镜头之后） ----------

from narrate import Opts, layout                                  # noqa: E402
from test_narrate import _clips, _live, _nudge_clips, _vis, us    # noqa: E402


def _fx(items, clips, top=None, **opts):
    plan = _plan(*items)
    plan.update(top or {})
    rows, track, rep = layout(plan, clips, {}, {}, {"n1": 60.0, "n2": 60.0}, Opts(**opts))
    f, warns, notes = fx.compute_fx(plan, rows, rep["srcs"], rep["slots"], CAT)
    return rows, rep, f, warns, notes


TR = {"type": "叠化", "dur": 0.6}


def _filt(cid, **kw):
    return [{"clip_id": cid, "filter": {"type": "夏日风吟", **kw}}]


def _syn(durs, items=None, vis=None):
    """合成的 rows / srcs / slots：每个镜头一项（或按 items 指定），用于镜头很短、一个画面多个镜头这类排不出来的情况。"""
    rows, srcs, t = [], [], 0
    items = items or [f"L{k}" for k in range(len(durs))]
    for k, d in enumerate(durs):
        rows.append({"idx": k + 1, "kind": "narr", "source": f"/x/c{k}.mp4", "in_us": 0, "start_us": t, "dur_us": d})
        srcs.append({"item": items[k], "vis": (vis or [0] * len(durs))[k], "clip_id": f"c{k}"})
        t += d
    slots, seen = [], {}
    for r, s in zip(rows, srcs):
        if s["item"] in seen:
            seen[s["item"]]["end_us"] = r["start_us"] + r["dur_us"]
        else:
            seen[s["item"]] = {"item": s["item"], "start_us": r["start_us"], "end_us": r["start_us"] + r["dur_us"], "live": False}
            slots.append(seen[s["item"]])
    return rows, srcs, slots


def test_transition_at_cut_plain():
    rows, rep, f, w, notes = _fx([_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c2"), transition=TR)],
                                 _clips(("c1", 60), ("c2", 60)))
    assert f["transitions"] == [{"shot": 1, "at_us": rows[1]["start_us"], "type": "叠化", "dur_us": 600000, "item": "L2", "vip": False}]
    assert w == [] and notes["L2"] == ["转场 叠化 0.6s"]
    assert [s["clip_id"] for s in rep["srcs"]] == ["c1", "c2"]
    assert f["shots_sig"] == fx.shots_sig(rows, ["c1", "c2"])


def test_transition_before_and_after_live():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _live("V1", "c7", 30.0, 35.0, transition=TR),
             _line("L2", 2.0, 4.0, file="n2", visuals=_vis("c2"), transition=TR)]
    rows, _, f, w, _ = _fx(items, _clips(("c1", 40), ("c2", 40), ("c7", 60)))
    assert [(t["item"], t["shot"], t["at_us"]) for t in f["transitions"]] == [
        ("V1", 1, rows[1]["start_us"]), ("L2", 2, rows[2]["start_us"])]


def test_transition_live_to_live():                                      # Review Focus 2
    items = [_live("V1", "c7", 30.0, 35.0), _live("V2", "c8", 10.0, 15.0, transition=TR)]
    rows, _, f, _, _ = _fx(items, _clips(("c7", 60), ("c8", 60)))
    assert [r["kind"] for r in rows] == ["live", "live"]
    assert f["transitions"][0]["shot"] == 1 and f["transitions"][0]["at_us"] == rows[1]["start_us"]


def test_transition_multi_visual_item():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 14.0, visuals=_vis("c2", "c3"), transition=TR)]
    rows, rep, f, _, _ = _fx(items, _clips(("c1", 60), ("c2", 60), ("c3", 60)))
    assert [s["item"] for s in rep["srcs"]] == ["L1", "L2", "L2"]
    assert f["transitions"][0]["shot"] == 1 and f["transitions"][0]["at_us"] == rows[1]["start_us"]


def test_transition_continuation_borrowed_new_shot():
    # L2 没配画面；上一个镜头的素材 c1 紧接着就是原声段，不能延长，只能借画面切一刀：切点真实存在
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, transition=TR),
             _live("V1", "c1", 20.0, 25.0), _line("L3", 2.0, 4.0, file="n2", visuals=_vis("c2"))]
    rows, rep, f, w, _ = _fx(items, _clips(("c1", 60), ("c2", 60)))
    assert rep["srcs"][1]["item"] == "L2"
    assert f["transitions"][0]["item"] == "L2" and f["transitions"][0]["at_us"] == rows[1]["start_us"]


def test_transition_swallowed_warns():
    items = [_line("A", 1.0, 3.0, visuals=_vis("c1")), _line("B", 3.4, 4.0, visuals=_filt("c2"), transition=TR),
             _line("C", 6.0, 9.0, visuals=_vis("c3"))]
    _, _, f, w, _ = _fx(items, _clips(("c1", 60), ("c2", 60), ("c3", 60)))
    assert f is None
    assert any("B" in x and "转场" in x and "吞掉" in x for x in w)
    assert any("B" in x and "滤镜" in x and "吞掉" in x for x in w)


def test_transition_after_nudge():
    items = [_line("A", 1.0, 19.231, visuals=_vis("g")), _line("B", 2.0, 8.0, file="n2", visuals=_vis("c2"), transition=TR)]
    _, _, f, _, _ = _fx(items, _nudge_clips())
    assert f["transitions"][0]["at_us"] == us(21.0)


def test_transition_on_fallback_shot():                                  # Review Focus 3
    # L1 的 c1 全是坏帧；相邻句的 c2 紧挨着不能用；只能 pick_one 从本章素材里拿 c3
    items = [_line("L0", 1.0, 3.0, visuals=_vis("c2")),
             _line("L1", 6.0, 8.0, visuals=_filt("c1"), transition=TR),
             _line("L2", 11.0, 13.0, visuals=_vis("c2")), _line("L3", 16.0, 18.0, visuals=_vis("c3"))]
    rows, rep, f, w, _ = _fx(items, _clips(("c1", 60, True), ("c2", 60), ("c3", 60)))
    assert rows[1]["source"] == "/x/c3.mp4" and rep["srcs"][1] == {"item": "L1", "vis": None, "clip_id": "c3"}
    assert f["transitions"][0]["item"] == "L1" and f["transitions"][0]["shot"] == 1
    assert f["filters"] == []
    assert any("L1" in x and "滤镜" in x and "c3" in x for x in w)


def test_transition_truncated_and_dropped():
    rows, srcs, slots = _syn([3_000_000, 2_000_000])
    plan = _plan(_line("L0", 0, 1), _line("L1", 2, 3, transition={"type": "叠化", "dur": 5}))
    f, w, _ = fx.compute_fx(plan, rows, srcs, slots, CAT)
    assert f["transitions"][0]["dur_us"] == 1_000_000 and any("截" in x for x in w)
    rows, srcs, slots = _syn([150_000, 150_000])
    f, w, _ = fx.compute_fx(plan, rows, srcs, slots, CAT)
    assert f is None and any("L1" in x and "太短" in x for x in w)


def test_effect_covers_final_slot():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c2"), effect={"type": "冲击波"})]
    _, rep, f, _, notes = _fx(items, _clips(("c1", 60), ("c2", 60)))
    s = rep["slots"][1]
    assert f["effects"] == [{"start_us": s["start_us"], "dur_us": s["end_us"] - s["start_us"], "type": "冲击波", "item": "L2", "vip": False}]
    assert notes["L2"] == ["特效 冲击波"]


def test_filter_follows_all_shots_of_visual():
    rows, srcs, slots = _syn([2_000_000, 2_000_000, 2_000_000], items=["L0", "L1", "L1"], vis=[0, 0, 0])
    plan = _plan(_line("L0", 0, 1), _line("L1", 2, 3, visuals=_filt("c1")))
    f, w, notes = fx.compute_fx(plan, rows, srcs, slots, CAT)
    assert f["filters"] == [{"shot": 2, "start_us": 2_000_000, "type": "夏日风吟", "intensity": 100, "item": "L1", "vip": False},
                            {"shot": 3, "start_us": 4_000_000, "type": "夏日风吟", "intensity": 100, "item": "L1", "vip": False}]
    assert w == [] and notes["L1"] == ["滤镜 夏日风吟 100"]


def test_filter_not_on_borrowed():
    rows, srcs, slots = _syn([2_000_000, 2_000_000], items=["L0", "L1"], vis=[0, None])
    plan = _plan(_line("L0", 0, 1), _line("L1", 2, 3, visuals=_filt("c9", intensity=60)))
    f, w, _ = fx.compute_fx(plan, rows, srcs, slots, CAT)
    assert f is None and any("L1" in x and "滤镜" in x for x in w)


def test_filter_extended_shot():
    items = [_line("L1", 1.0, 3.0, visuals=_filt("c1", intensity=60)), _line("L2", 6.0, 8.0)]
    rows, _, f, _, _ = _fx(items, _clips(("c1", 60)))
    assert len(rows) == 1 and f["filters"] == [{"shot": 1, "start_us": 0, "type": "夏日风吟", "intensity": 60, "item": "L1", "vip": False}]


def test_intro_outro_from_layout():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c2"))]
    rows, _, f, w, notes = _fx(items, _clips(("c1", 60), ("c2", 60)), top={"intro": {"type": "渐显"}, "outro": {"type": "渐隐"}})
    assert f["intro"] == {"shot": 1, "type": "渐显", "dur_us": 500000, "vip": False}
    assert f["outro"] == {"shot": 2, "type": "渐隐", "dur_us": 500000, "vip": False}
    assert notes["L1"] == ["片头 渐显 0.5s"] and notes["L2"] == ["片尾 渐隐 0.5s"]


def test_intro_outro_truncated_and_single_shot_halves():
    plan = dict(_plan(_line("L0", 0, 1)), intro={"type": "渐显"}, outro={"type": "渐隐"})
    rows, srcs, slots = _syn([600_000])
    f, w, _ = fx.compute_fx(plan, rows, srcs, slots, CAT)
    assert f["intro"]["dur_us"] == 300000 and f["outro"]["dur_us"] == 300000 and any("截" in x for x in w)
    rows, srcs, slots = _syn([150_000])
    f, w, _ = fx.compute_fx(plan, rows, srcs, slots, CAT)
    assert f is None and sum("太短" in x for x in w) == 2
    rows, srcs, slots = _syn([300_000, 2_000_000], items=["L0", "L0"])
    only_intro = {k: v for k, v in plan.items() if k != "outro"}
    f, w, _ = fx.compute_fx(only_intro, rows, srcs, slots, CAT)       # 两个镜头：片头只截到第一个镜头的长度
    assert f["intro"]["dur_us"] == 300_000


def test_no_fx_returns_none():
    _, _, f, w, notes = _fx([_line("L1", 1.0, 3.0, visuals=_vis("c1"))], _clips(("c1", 60)))
    assert f is None and w == [] and notes == {}


def test_vip_flag_from_catalog():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c2"), transition={"type": "星光叠化"})]
    _, _, f, _, _ = _fx(items, _clips(("c1", 60), ("c2", 60)))
    assert f["transitions"][0]["vip"] is True and f["transitions"][0]["dur_us"] == 500000


_ROWS = [{"idx": 1, "kind": "narr", "source": "/x/a.mp4", "clip_id": "c001", "in_us": 0, "start_us": 0, "dur_us": 5},
         {"idx": 2, "kind": "live", "source": "/x/b.mp4", "clip_id": "c002", "in_us": 7, "start_us": 5, "dur_us": 3}]


@pytest.mark.parametrize("field,val", [("idx", 9), ("kind", "narr"), ("clip_id", "c003"), ("in_us", 8),
                                       ("start_us", 6), ("dur_us", 4)])
def test_shots_sig_sensitive(field, val):
    changed = [dict(_ROWS[0]), dict(_ROWS[1], **{field: val})]
    assert fx.shots_sig(changed) != fx.shots_sig(_ROWS)


def test_shots_sig_csv_strings_equal():
    as_csv = [{k: str(v) for k, v in r.items()} for r in _ROWS]
    assert fx.shots_sig(as_csv) == fx.shots_sig(_ROWS) and fx.shots_sig(_ROWS).startswith("v2:sha1:")


def test_shots_sig_ignores_source_path():
    """派生目录把素材换成同名调色副本（clip_id 不变）：指纹不变；同名但不同 clip_id：指纹变。"""
    moved = [dict(r, source=r["source"].replace("/x/", "/x/调色_CLog3/")) for r in _ROWS]
    assert fx.shots_sig(moved) == fx.shots_sig(_ROWS)
    same_name = [dict(_ROWS[0]), dict(_ROWS[1], source="/y/b.mp4", clip_id="c009")]
    assert fx.shots_sig(same_name) != fx.shots_sig(_ROWS)


def test_shots_sig_explicit_ids():
    bare = [{k: v for k, v in r.items() if k != "clip_id"} for r in _ROWS]
    assert fx.shots_sig(bare, ["c001", "c002"]) == fx.shots_sig(_ROWS)


@pytest.mark.parametrize("content", ["[]", "{}", '{"transition": []}',
                                     json.dumps({**CAT, "transition": {"叠化": {"member": "叠化", "resource_id": "1", "vip": False}}},
                                                ensure_ascii=False)])
def test_load_catalog_bad_structure(tmp_path, content):          # 终审 Important 1
    p = tmp_path / "cat.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="重跑 fx_catalog.py"):
        fx.load_catalog(str(p))

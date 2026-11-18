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

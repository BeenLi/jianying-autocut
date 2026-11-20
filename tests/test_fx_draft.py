"""读回草稿后逐个核对效果（fx_draft.verify_fx）：先真实 build 一份带五类效果的草稿，再在读回的 JSON 上动手脚。"""
import copy

import pytest

import fx
import fx_draft
from test_build_main import _fx_build


@pytest.fixture
def built(tmp_path, monkeypatch):
    d, f, _, _, _ = _fx_build(tmp_path, monkeypatch)
    return d, f, fx.load_catalog()


def _main(d):
    return [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]


def test_verify_clean(built):
    d, f, cat = built
    assert fx_draft.verify_fx(d, f, cat) == []


def test_verify_transition_on_wrong_segment(built):
    d, f, cat = built
    tid = d["materials"]["transitions"][0]["id"]
    v = _main(d)
    v[0]["extra_material_refs"].remove(tid)
    v[1]["extra_material_refs"].append(tid)
    errs = fx_draft.verify_fx(d, f, cat)
    assert any("转场" in e and "第 1" in e for e in errs) and any("第 2" in e for e in errs)


def test_verify_wrong_duration(built):
    d, f, cat = built
    d["materials"]["transitions"][0]["duration"] = 300000
    assert any("转场" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_wrong_name(built):
    d, f, cat = built
    flt = next(e for e in d["materials"]["effects"] if e.get("type") == "filter")
    flt["resource_id"] = "123"
    assert any("滤镜" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_wrong_intensity(built):
    d, f, cat = built
    next(e for e in d["materials"]["effects"] if e.get("type") == "filter")["value"] = 0.61
    assert any("强度" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_intensity_tolerance(built):
    d, f, cat = built
    next(e for e in d["materials"]["effects"] if e.get("type") == "filter")["value"] = 0.6 + 5e-7
    assert fx_draft.verify_fx(d, f, cat) == []


def test_verify_animation_out_of_range(built):
    d, f, cat = built
    out = next(a for ma in d["materials"]["material_animations"] for a in ma["animations"] if a["type"] == "out")
    out["start"] = -100
    assert any("片尾" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_extra_effect(built):
    d, f, cat = built
    eff = next(t for t in d["tracks"] if t["type"] == "effect")
    seg = copy.deepcopy(eff["segments"][0])
    seg["target_timerange"] = {"start": 3000000, "duration": 1000000}
    eff["segments"].append(seg)
    assert any("特效" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_missing_effect(built):
    d, f, cat = built
    d["tracks"] = [t for t in d["tracks"] if t["type"] != "effect"]
    assert any("特效" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_extra_transition_not_expected(built):
    d, f, cat = built
    f = dict(f, transitions=[])
    assert any("转场" in e for e in fx_draft.verify_fx(d, f, cat))



# ---------- 自检：孤立的动画 / 特效材料（第 5 条）----------

def test_verify_orphan_animation_material(built):
    d, f, cat = built
    ma = copy.deepcopy(d["materials"]["material_animations"][0])
    ma["id"] = "orphan-anim"
    d["materials"]["material_animations"].append(ma)
    assert any("动画" in e and "没挂" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_orphan_video_effect_material(built):
    d, f, cat = built
    ve = copy.deepcopy(d["materials"]["video_effects"][0])
    ve["id"] = "orphan-fx"
    d["materials"]["video_effects"].append(ve)
    assert any("特效" in e and "没挂" in e for e in fx_draft.verify_fx(d, f, cat))


def test_verify_unknown_animation_type(built):
    d, f, cat = built
    a = copy.deepcopy(d["materials"]["material_animations"][0]["animations"][0])
    a["type"] = "group"
    d["materials"]["material_animations"][0]["animations"].append(a)
    assert any("group" in e for e in fx_draft.verify_fx(d, f, cat))


# ---------- 预检：效果自身的数值（第 10 条，Codex 审出）----------

_SHOTS = [{"idx": "1", "kind": "narr", "clip_id": "c001", "in_us": "0", "start_us": "0", "dur_us": "5000000"},
          {"idx": "2", "kind": "live", "clip_id": "c002", "in_us": "0", "start_us": "5000000", "dur_us": "3000000"}]


def _pf(patch=None):
    from test_build_main import FULL_FX
    f = copy.deepcopy(FULL_FX)
    f["shots_sig"] = fx.shots_sig(_SHOTS)
    if patch:
        patch(f)
    return fx_draft.preflight(f, _SHOTS, fx.load_catalog())


def test_preflight_clean():
    assert _pf() == []


def test_preflight_transition_on_last_shot():
    def p(f):
        f["transitions"][0].update(shot=2, at_us=8000000)
    assert any("最后一个镜头" in e for e in _pf(p))


@pytest.mark.parametrize("val", [101, -1, "60", float("nan"), True, None])
def test_preflight_filter_intensity(val):
    def p(f):
        f["filters"][0]["intensity"] = val
    assert any("强度" in e for e in _pf(p))


@pytest.mark.parametrize("kind", ["transitions", "effects"])
@pytest.mark.parametrize("val", [0, -5, 1.5, True, "400000"])
def test_preflight_bad_duration(kind, val):
    def p(f):
        f[kind][0]["dur_us"] = val
    assert any("时长" in e for e in _pf(p))


@pytest.mark.parametrize("val", [0, -5, 6000000])
def test_preflight_animation_duration(val):
    def p(f):
        f["intro"]["dur_us"] = val
    assert any("片头" in e and "时长" in e for e in _pf(p))


def test_preflight_intro_outro_overlap_same_shot():
    def p(f):
        f["intro"].update(shot=2, dur_us=2000000)        # 第 2 镜 3s：入场 2s + 出场 0.5s 不重叠
    assert _pf(p) == []

    def q(f):
        f["intro"].update(shot=2, dur_us=2600000)        # 2.6 + 0.5 > 3：重叠
    assert any("重叠" in e for e in _pf(q))


@pytest.mark.parametrize("kind", ["transitions", "filters"])
def test_preflight_duplicate_on_same_shot(kind):
    def p(f):
        f[kind].append(copy.deepcopy(f[kind][0]))
    assert any("重复" in e for e in _pf(p))

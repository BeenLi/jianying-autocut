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

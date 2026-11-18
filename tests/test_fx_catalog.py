import json
from enum import Enum

import pytest

from fx_catalog import CATALOG_PATH, SOURCES, build_catalog


def _cat():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_catalog_file_matches_library():
    cat = _cat()
    assert cat == build_catalog()
    assert [len(cat[k]) for k in ("transition", "effect", "filter", "intro", "outro")] == [453, 1097, 1160, 155, 124]


def test_member_roundtrip():
    cat = _cat()
    for kind, (enum, field) in SOURCES.items():
        items = list(cat[kind].items())
        sample = items[:20] + [x for x in items if x[1]["vip"]][:5]
        for name, e in sample:
            meta = getattr(enum, e["member"]).value
            assert getattr(meta, field) == name
            assert meta.resource_id == e["resource_id"] and meta.is_vip == e["vip"]


def test_special_names():
    cat = _cat()
    assert cat["effect"]["X-Signal"]["member"] == "X_Signal"
    assert cat["transition"]["叠化"]["dur"] == 0.5
    assert cat["intro"]["渐显"]["dur"] == 0.5
    assert "dur" not in cat["filter"]["夏日风吟"]


class _M:
    def __init__(self, name):
        self.name, self.is_vip, self.resource_id = name, False, "1"


def test_duplicate_display_name_fails():
    Fake = Enum("Fake", {"a": _M("同名"), "b": _M("同名")})
    with pytest.raises(ValueError, match="同名"):
        build_catalog({"effect": (Fake, "name")})

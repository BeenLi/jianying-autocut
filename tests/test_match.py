import copy

from match import to_seconds, validate

_SHOOT_PLAN = {
    "meta": {"title": "枸杞岛两日", "intent": "一座岛从雾里慢慢露出来", "place": "枸杞岛", "days": 2, "stage": "editing"},
    "chapters": [{"id": "ch1", "order": 1, "title": "雾里的灯塔", "function": "hook", "rhythm": "fast"},
                 {"id": "ch2", "order": 2, "title": "出发", "function": "setup", "rhythm": "slow"}],
    "shots": [{"id": "S01", "chapter": "ch1", "order": 1, "kind": "visual", "desc": "灯塔在雾里"},
              {"id": "S02", "chapter": "ch2", "order": 1, "kind": "visual", "desc": "码头买票"},
              {"id": "S03", "chapter": "ch2", "order": 2, "kind": "talk", "desc": "船上说话", "talk": "第一次坐船上岛"}],
}
_MATCHES = {
    "matches": {"S01": {"clip_id": "c001", "at": 10, "start": None, "end": None, "confirmed": True, "by": "user"},
                "S02": {"clip_id": "c002", "at": 15, "start": None, "end": None, "confirmed": True, "by": "claude"},
                "S03": {"clip_id": "c002", "at": 80, "start": 78, "end": 83, "confirmed": True, "by": "claude"}},
    "extras": {},
}
_DURATIONS = {"c001": 30.0, "c002": 120.0, "c003": 20.0, "c004": 20.0, "c005": 20.0}


def _inputs():
    return copy.deepcopy(_SHOOT_PLAN), copy.deepcopy(_MATCHES), dict(_DURATIONS)


def test_valid_inputs_have_no_errors():
    assert validate(*_inputs()) == []


def test_unconfirmed_match_is_an_error():
    sp, m, d = _inputs()
    m["matches"]["S02"]["confirmed"] = False
    assert any("S02" in e and "确认" in e for e in validate(sp, m, d))


def test_unknown_shot_and_clip_and_out_of_range():
    sp, m, d = _inputs()
    m["matches"]["S99"] = dict(m["matches"]["S01"])
    m["matches"]["S01"]["clip_id"] = "c404"
    m["matches"]["S02"]["at"] = 999
    errs = validate(sp, m, d)
    assert any("S99" in e for e in errs) and any("c404" in e for e in errs) and any("999" in e for e in errs)


def test_shot_in_unknown_chapter():
    sp, m, d = _inputs()
    sp["shots"][0]["chapter"] = "ch9"
    assert any("S01" in e and "ch9" in e for e in validate(sp, m, d))


def test_talk_range_must_contain_at():
    sp, m, d = _inputs()
    m["matches"]["S03"]["end"] = 79
    assert any("S03" in e and "口播" in e for e in validate(sp, m, d))


def test_at_accepts_numeric_strings_and_mmss():          # Review Focus 3
    assert to_seconds("15") == 15.0 and to_seconds("1:05") == 65.0 and to_seconds(7) == 7.0
    assert to_seconds("abc") is None and to_seconds(None) is None
    sp, m, d = _inputs()
    m["matches"]["S02"]["at"] = "15"
    assert validate(sp, m, d) == []


def test_bad_rhythm_and_function():
    sp, m, d = _inputs()
    sp["chapters"][0]["rhythm"] = "turbo"
    sp["chapters"][1]["function"] = "x"
    errs = validate(sp, m, d)
    assert any("ch1" in e for e in errs) and any("ch2" in e for e in errs)


def test_bad_extras_are_reported():
    sp, m, d = _inputs()
    m["extras"] = {"c404": {"chapter": "ch2", "at": 1, "accepted": True},
                   "c003": {"chapter": "ch9", "at": 1, "accepted": True},
                   "c004": {"chapter": "ch2", "at": "x", "accepted": True}}
    errs = validate(sp, m, d)
    assert all(any(f"计划外素材 {c}" in e for e in errs) for c in ("c404", "c003", "c004"))

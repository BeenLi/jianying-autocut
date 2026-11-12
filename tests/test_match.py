import copy
import json
import os

from common import write_csv
from match import build_story_plan, main, to_seconds, validate

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


def _write_work(tmp_path, sp, m, d):
    with open(os.path.join(tmp_path, "shoot_plan.json"), "w", encoding="utf-8") as f:
        json.dump(sp, f, ensure_ascii=False)
    with open(os.path.join(tmp_path, "matches.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    write_csv(os.path.join(tmp_path, "inventory.csv"),
              [{"clip_id": c, "duration_s": dur} for c, dur in d.items()], ["clip_id", "duration_s"])


def test_build_maps_confirmed_matches_to_pins():
    sp, m, _ = _inputs()
    story, rep = build_story_plan(sp, m)
    ch1, ch2 = story["chapters"]
    assert ch1["pins"] == [{"clip_id": "c001", "at": 10.0}] and ch1["function"] == "hook" and ch1["pool"] == "own"
    assert ch2["clip_ids"] == ["c002"] and [p["at"] for p in ch2["pins"]] == [15.0, 80.0]
    assert story["director_intent"] == sp["meta"]["intent"] and rep["missing"] == {}


def test_chapters_follow_order_field():
    sp, m, _ = _inputs()
    sp["chapters"][0]["order"], sp["chapters"][1]["order"] = 2, 1
    story, _ = build_story_plan(sp, m)
    assert [c["id"] for c in story["chapters"]] == ["ch2", "ch1"]


def test_missing_shot_and_dropped_chapter():
    sp, m, _ = _inputs()
    del m["matches"]["S01"]
    story, rep = build_story_plan(sp, m)
    assert [c["id"] for c in story["chapters"]] == ["ch2"]
    assert rep["dropped_chapters"] == ["ch1"] and rep["missing"] == {"ch1": ["S01"]}


def test_extras_accepted_pending_rejected():                 # Review Focus 5
    sp, m, _ = _inputs()
    m["extras"] = {"c003": {"chapter": "ch2", "at": 5, "accepted": True},
                   "c004": {"chapter": "ch2", "at": 1, "accepted": None},
                   "c005": {"chapter": "ch1", "at": 1, "accepted": False}}
    story, rep = build_story_plan(sp, m)
    assert "c003" in story["chapters"][1]["clip_ids"]
    assert all("c004" not in c["clip_ids"] and "c005" not in c["clip_ids"] for c in story["chapters"])
    assert rep["pending_extras"] == ["c004"] and rep["rejected_extras"] == 1


def test_extra_shared_with_other_chapter_passes_story_validate():   # Review Focus 4
    from story import validate as story_validate
    sp, m, d = _inputs()
    m["extras"] = {"c001": {"chapter": "ch2", "at": 25, "accepted": True}}
    story, _ = build_story_plan(sp, m)
    assert "c001" in story["chapters"][1]["clip_ids"]
    assert story_validate(story, set(d)) == []


def test_near_duplicate_pins_are_merged():                  # Review Focus 1
    sp, m, _ = _inputs()
    m["matches"]["S03"].update(at=15.4, start=None, end=None)
    story, rep = build_story_plan(sp, m)
    assert [p["at"] for p in story["chapters"][1]["pins"]] == [15.0]
    assert rep["merged_pins"] == [("c002", 15.0, 15.4)]


def test_main_writes_story_plan(tmp_path, capsys):
    sp, m, d = _inputs()
    del m["matches"]["S01"]
    _write_work(tmp_path, sp, m, d)
    assert main(["--work", str(tmp_path)]) == 0
    with open(tmp_path / "story_plan.json", encoding="utf-8") as f:
        assert [c["id"] for c in json.load(f)["chapters"]] == ["ch2"]
    out = capsys.readouterr().out
    assert "S01" in out and "ch1" in out and "未被任何章引用的素材 4 段" in out


def test_main_refuses_when_nothing_confirmed(tmp_path):    # Review Focus 2
    sp, m, d = _inputs()
    m["matches"] = {}
    _write_work(tmp_path, sp, m, d)
    assert main(["--work", str(tmp_path)]) == 1 and not (tmp_path / "story_plan.json").exists()


def test_main_refuses_on_validation_errors(tmp_path):
    sp, m, d = _inputs()
    m["matches"]["S02"]["confirmed"] = False
    _write_work(tmp_path, sp, m, d)
    assert main(["--work", str(tmp_path)]) == 1 and not (tmp_path / "story_plan.json").exists()


def test_talk_longer_than_chapter_rhythm_is_reported():     # Final review I3
    sp, m, _ = _inputs()
    sp["chapters"][1]["rhythm"] = "fast"                     # fast 最长镜头 9s
    m["matches"]["S03"].update(start=70, at=75, end=82)      # 整句 12s
    _, rep = build_story_plan(sp, m)
    assert rep["long_talk"] == [("S03", 12.0, 9)]
    sp["chapters"][1]["rhythm"] = "slow"                     # slow 最长 18s，放得下
    _, rep = build_story_plan(sp, m)
    assert rep["long_talk"] == []


# ---------- 小问题修复 ----------

import pytest


def test_to_seconds_hms_and_rejects_empty_parts():          # A3
    assert to_seconds("1:05:00") == 3900 and to_seconds("1:05") == 65 and to_seconds(" 7 ") == 7
    assert to_seconds("1:") is None and to_seconds(":5") is None and to_seconds("") is None
    assert to_seconds("1:2:3:4") is None


def test_cross_chapter_pins_colliding_are_reported():       # A1
    sp, m, d = _inputs()
    m["extras"] = {"c001": {"chapter": "ch2", "at": 12, "reason": "", "accepted": True}}
    _, rep = build_story_plan(sp, m)
    assert rep["cross_pins"] == [("c001", 10.0, "ch1", 12.0, "ch2")]
    m["extras"]["c001"]["at"] = 20                          # ch1 fast 最长 6s → 6/2+1 = 4s 之外不撞
    _, rep = build_story_plan(sp, m)
    assert rep["cross_pins"] == []


def test_undecided_or_rejected_extras_not_validated():      # A2
    sp, m, d = _inputs()
    m["extras"] = {"c003": {"chapter": "chX", "at": 999, "accepted": False},
                   "c004": {"chapter": "chX", "at": "abc", "accepted": None}}
    assert validate(sp, m, d) == []


def test_odd_accepted_value_is_reported():
    sp, m, d = _inputs()
    m["extras"] = {"c003": {"chapter": "ch2", "at": 5, "accepted": "true"}}
    _, rep = build_story_plan(sp, m)
    assert rep["odd_extras"] == ["c003"] and rep["pending_extras"] == []


def test_validate_survives_bad_structure():                 # C2
    sp, m, d = _inputs()
    sp["shots"].append({"chapter": "ch1"})
    sp["chapters"].append({"title": "无 id"})
    errs = validate(sp, m, d)
    assert any("id" in e for e in errs)
    sp, m, d = _inputs()
    m["matches"] = [1, 2]
    assert any("matches" in e for e in validate(sp, m, d))


def test_main_reports_broken_json(tmp_path):                # A4
    _write_work(tmp_path, *_inputs())
    (tmp_path / "matches.json").write_text('{"matches": {,}}')
    with pytest.raises(SystemExit) as e:
        main(["--work", str(tmp_path)])
    assert "matches.json" in str(e.value) and "第 1 行" in str(e.value)

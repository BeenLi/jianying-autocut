from story import default_chapters


def test_default_chapters_split_on_gaps():
    rows = [{"clip_id": "c001", "shot_time": "2026-10-05T01:00:00", "folder": "a"},
            {"clip_id": "c002", "shot_time": "2026-10-05T01:01:00", "folder": "a"},
            {"clip_id": "c003", "shot_time": "2026-10-06T09:00:00", "folder": "a"}]
    ch = default_chapters(rows, 2)
    assert [c["clip_ids"] for c in ch] == [["c001", "c002"], ["c003"]]


def test_exclude_by_id_and_range():
    from story import apply_exclude
    plan = {"chapters": [{"id": "a", "title": "a", "clip_ids": ["c001", "c002", "c003"], "pins": [{"clip_id": "c002", "at": 1}]},
                         {"id": "b", "title": "b", "clip_ids": ["c059", "c060"], "pins": []}]}
    out = apply_exclude(plan, "c002,c059-c060")
    assert [c["clip_ids"] for c in out["chapters"]] == [["c001", "c003"]] and out["chapters"][0]["pins"] == []


def test_validate_intercut_ids_must_be_in_chapter():
    from story import validate
    plan = {"chapters": [{"id": "x", "clip_ids": ["c001", "c002"],
                          "intercut": {"a": ["c001"], "b": ["c009"], "end_on": "a"}}]}
    errs = validate(plan, {"c001", "c002", "c009"})
    assert any("intercut" in e for e in errs)


def test_validate_rejects_unknown_rhythm():
    from story import validate
    errs = validate({"chapters": [{"id": "a", "clip_ids": [], "rhythm": "turbo"}]}, set())
    assert any("rhythm" in e for e in errs)

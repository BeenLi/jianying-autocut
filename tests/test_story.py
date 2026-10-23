from story import beats_to_chapters, default_chapters

PM = [{"clip_id": f"c{i:03d}", "proxy_start": i * 10.0, "proxy_end": i * 10.0 + 10} for i in range(6)]
USE = {f"c{i:03d}": 12.0 for i in range(6)}


def test_majority_membership_and_pins():
    beats = [{"beat_id": "b1", "source_start": 0, "source_end": 24, "function": "hook", "event": "出发",
              "must_keep_moment": "12.5"},
             {"beat_id": "b2", "source_start": 24, "source_end": 60, "function": "payoff", "event": "登顶"}]
    ch, warn = beats_to_chapters(beats, PM, USE)
    assert ch[0]["clip_ids"] == ["c000", "c001"] and "c002" in ch[1]["clip_ids"]   # c002 被 b2 占 6s>4s
    assert ch[0]["pins"] == [{"clip_id": "c001", "at": 2.5}] and ch[0]["function"] == "hook"
    assert ch[1]["title"] == "登顶" and not warn


def test_beat_out_of_range_and_empty():
    beats = [{"beat_id": "b1", "source_start": 0, "source_end": 59, "function": "setup", "event": "a"},
             {"beat_id": "b2", "source_start": 59, "source_end": 70, "function": "payoff", "event": "b"}]
    ch, warn = beats_to_chapters(beats, PM, USE)
    assert len(ch) == 1 and warn


def test_small_beat_merges_into_previous():
    use = {"c000": 30.0, "c001": 5.0, "c002": 30.0}
    pm = PM[:3]
    beats = [{"beat_id": "b1", "source_start": 0, "source_end": 10, "function": "setup", "event": "a"},
             {"beat_id": "b2", "source_start": 10, "source_end": 20, "function": "turn", "event": "b"},
             {"beat_id": "b3", "source_start": 20, "source_end": 30, "function": "payoff", "event": "c"}]
    ch, warn = beats_to_chapters(beats, pm, use)
    assert [c["clip_ids"] for c in ch] == [["c000", "c001"], ["c002"]] and warn


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


def test_short_hook_survives_and_keeps_role():
    pm = PM[:4]
    use = {c["clip_id"]: 30.0 for c in pm}
    beats = [{"beat_id": "h", "source_start": 12, "source_end": 16, "function": "hook", "event": "瀑布",
              "must_keep_moment": "14"},                                   # 落在 c001 里，c001 归 b1
             {"beat_id": "b1", "source_start": 0, "source_end": 40, "function": "setup", "event": "上山"}]
    ch, warn = beats_to_chapters(beats, pm, use)
    hook = [c for c in ch if c["function"] == "hook"]
    assert hook and hook[0]["pool"] == "all" and hook[0]["pins"] == [{"clip_id": "c001", "at": 4.0}]


def test_validate_intercut_ids_must_be_in_chapter():
    from story import validate
    plan = {"chapters": [{"id": "x", "clip_ids": ["c001", "c002"],
                          "intercut": {"a": ["c001"], "b": ["c009"], "end_on": "a"}}]}
    errs = validate(plan, {"c001", "c002", "c009"})
    assert any("intercut" in e for e in errs)

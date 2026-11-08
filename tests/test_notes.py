from notes import check_notes, render_brief

DUR = {"c001": 30.0, "c002": 12.0}


def _n(start, end, text="瀑布"):
    return {"start": start, "end": end, "description": text}


def test_complete_notes_have_no_problems():
    assert check_notes({"c001": [_n(0, 30)], "c002": [_n(0, 12)]}, DUR) == ([], [])


def test_missing_clips_are_listed_for_the_next_batch():
    missing, errors = check_notes({"c001": [_n(0, 30)]}, DUR)
    assert missing == ["c002"] and not errors


def test_empty_note_list_counts_as_missing():
    assert check_notes({"c001": [_n(0, 30)], "c002": []}, DUR)[0] == ["c002"]


def test_bad_times_and_blank_text_and_unknown_clip_are_errors():
    _, errors = check_notes({"c001": [_n(20, 10), _n(0, 99), _n(0, 5, " ")], "c002": [_n(0, 12)], "c999": [_n(0, 1)]}, DUR)
    text = "\n".join(errors)
    assert len(errors) == 4 and "c999" in text and "c001" in text


def test_brief_merges_pictures_and_speech_in_time_order():
    inv = [{"clip_id": "c001", "name": "a.mp4", "duration_s": "30", "shot_time": "2026-10-05T08:00:00"}]
    md = render_brief(inv, {"c001": [_n(0, 10, "上山"), _n(10, 30, "瀑布")]},
                      {"c001": [{"start": 12.0, "end": 14.0, "text": "到了"}]})
    assert "c001" in md and "a.mp4" in md
    assert md.index("上山") < md.index("瀑布") < md.index("到了")


def test_brief_works_without_speech():
    inv = [{"clip_id": "c001", "name": "a.mp4", "duration_s": "30", "shot_time": ""}]
    assert "上山" in render_brief(inv, {"c001": [_n(0, 10, "上山")]}, {})

from probe import parse_silences



def test_parse_silences():
    err = "silence_start: 1.5\nsilence_end: 3.0 | silence_duration: 1.5\nsilence_start: 9.2\n"
    assert parse_silences(err, 10.0) == [(1.5, 3.0), (9.2, 10.0)]


def test_assign_ids_keeps_old_and_appends_new():
    from probe import assign_ids
    rows = [{"path": "/a"}, {"path": "/new"}, {"path": "/b"}]          # 已按拍摄时间排好
    old = {"/a": "c001", "/b": "c002"}
    assign_ids(rows, old)
    assert [r["clip_id"] for r in rows] == ["c001", "c003", "c002"]


def test_assign_ids_fresh():
    from probe import assign_ids
    rows = [{"path": "/x"}, {"path": "/y"}]
    assign_ids(rows, {})
    assert [r["clip_id"] for r in rows] == ["c001", "c002"]

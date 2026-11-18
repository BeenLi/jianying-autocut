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


def _tree(tmp_path):
    """素材目录：一段正常素材，工作目录里一段 LUT 副本（不该被当成素材）。"""
    root = tmp_path / "视频"
    (root / "手机").mkdir(parents=True)
    (root / "手机" / "a.mp4").write_bytes(b"")
    (root / "手机" / "_autocut" / "调色").mkdir(parents=True)
    (root / "手机" / "_autocut" / "调色" / "a.mp4").write_bytes(b"")
    (root / "动画").mkdir()
    return root


def test_scan_skips_work_dir_given_with_dotdot(tmp_path):
    from probe import scan_videos
    root = _tree(tmp_path)
    work = str(root / "动画" / ".." / "手机" / "_autocut")         # 和工作目录是同一个目录，只是写法不同
    assert scan_videos(str(root), work) == [str(root / "手机" / "a.mp4")]


def test_scan_skips_work_dir_given_through_symlink(tmp_path):
    from probe import scan_videos
    root = _tree(tmp_path)
    link = tmp_path / "w"
    link.symlink_to(root / "手机" / "_autocut")
    assert scan_videos(str(root), str(link)) == [str(root / "手机" / "a.mp4")]


def test_scan_keeps_paths_as_given_under_symlinked_root(tmp_path):
    """素材根目录本身是符号链接时，返回的路径照旧用链接写法：inventory 里的 clip_id 按路径认，改写法会重新编号。"""
    from probe import scan_videos
    root = _tree(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    assert scan_videos(str(alias), str(alias / "手机" / "_autocut")) == [str(alias / "手机" / "a.mp4")]

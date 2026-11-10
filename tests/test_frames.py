from frames import judge


def _rows(path, values, brightness=120):
    return [{"path": path, "sharpness": s, "brightness": brightness} for s in values]


def test_judge_relative_blur():
    rows = _rows("a", (100, 110, 120, 20)) + _rows("b", (2000, 2100, 2200))
    out = judge(rows)
    assert [r["bad"] for r in out] == [0, 0, 0, 1, 0, 0, 0]   # 低纹理段不误杀，突降被抓


def test_judge_exposure():
    assert judge(_rows("a", (500,), brightness=5))[0]["bad"] == 1


def test_parse_scene_scores():
    from frames import parse_scene_scores
    out = "frame:0    pts:100  pts_time:3.5\nlavfi.scene_score=0.612\nframe:1    pts:200  pts_time:9\nlavfi.scene_score=0.45\n"
    assert parse_scene_scores(out) == [(3.5, 0.612), (9.0, 0.45)]


def test_merge_adds_scene_cuts_away_from_regular_frames():
    from frames import merge_times
    assert merge_times([4.0, 12.0], [(8.0, 0.9), (4.5, 0.9)], 16.0) == [4.0, 8.5, 12.0]    # 切点后 0.5s 取帧，4.5 太近


def test_merge_keeps_strongest_cuts_when_capped():
    from frames import merge_times
    cuts = [(8.0, 0.5), (20.0, 0.9), (30.0, 0.7), (40.0, 0.4)]
    assert merge_times([], cuts, 60.0, max_extra=2) == [20.5, 30.5]


def test_merge_keeps_short_cuts_apart_and_inside_clip():
    from frames import merge_times
    assert merge_times([], [(5.0, 0.9), (6.0, 0.8), (9.9, 0.7)], 10.0) == [5.5]


def test_short_scene_just_before_regular_frame_is_kept():
    from frames import merge_times
    assert merge_times([4.0, 12.0, 20.0], [(16.67, 0.6)], 30.0) == [4.0, 12.0, 17.17, 20.0]


def test_sample_times_covers_the_tail():
    from frames import sample_times
    assert sample_times(30, 8) == [4, 12, 20, 27]      # 尾部 6s 也要有一帧
    assert sample_times(25, 8) == [4, 12, 20]          # 尾部只有 1s，不补
    assert sample_times(5, 8) == [2.5]                 # 短素材取正中间


def test_snap_to_keyframes_uses_real_times_and_dedupes():
    from frames import snap_to_keyframes
    kf = [0.0, 8.333, 16.667, 18.0, 26.333]
    assert snap_to_keyframes([4.0, 12.0, 17.167, 20.0, 27.0], kf) == [0.0, 8.333, 16.667, 18.0, 26.333]
    assert snap_to_keyframes([1.0, 2.0, 3.0], kf) == [0.0]


def test_snap_without_keyframes_keeps_sample_times():
    from frames import snap_to_keyframes
    assert snap_to_keyframes([4.0, 12.0], []) == [4.0, 12.0]


def test_grab_seeks_just_before_keyframe(monkeypatch):
    # ffmpeg 只解关键帧时取到的是 -ss 之后的下一个关键帧，所以要从目标略早处 seek
    import frames
    calls = []

    class R:
        stdout = bytes(9)
    monkeypatch.setattr(frames.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    frames.grab("a.mp4", 16.667, 3, 3, "t.jpg")
    assert float(calls[0][calls[0].index("-ss") + 1]) < 16.667
    calls.clear()
    frames.grab("a.mp4", 0.0, 3, 3, "t.jpg")
    assert float(calls[0][calls[0].index("-ss") + 1]) == 0.0

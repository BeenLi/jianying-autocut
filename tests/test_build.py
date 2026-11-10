from build import bgm_segments, duck_keyframes, parse_bgm, place_subs
from common import US


def test_bgm_segments_loop_and_trim():
    assert bgm_segments(100 * US, 0, 250 * US) == [(0, 0, 100 * US), (100 * US, 0, 100 * US), (200 * US, 0, 50 * US)]
    assert bgm_segments(400 * US, 0, 250 * US) == [(0, 0, 250 * US)]


def test_bgm_segments_drop_tiny_tail():
    # 循环后剩下 <1s 的尾巴并不好听：并进上一段的空间里截掉，最后一段补到终点
    segs = bgm_segments(100 * US, 0, 200 * US + US // 2)
    assert segs[-1][0] + segs[-1][2] == 200 * US + US // 2 and all(d >= US for _, _, d in segs)


def test_parse_bgm():
    assert parse_bgm("/a/b.mp3") == {"path": "/a/b.mp3", "gain": 0.2, "fade": 1.5}
    assert parse_bgm("/a/b.mp3:0.5:2") == {"path": "/a/b.mp3", "gain": 0.5, "fade": 2.0}


def _shot(cid, in_s, dur_s, start_s):
    return {"clip_id": cid, "in_us": round(in_s * US), "dur_us": round(dur_s * US), "start_us": round(start_s * US)}


def test_place_subs_maps_clip_time_to_timeline():
    shots = [_shot("c1", 0.5, 9, 0), _shot("c2", 4, 6, 9)]
    subs = {"c1": [{"start": 1, "end": 8, "text": "多住几天"}], "c2": [{"start": 5, "end": 7, "text": "格桑"}]}
    placed, warns = place_subs(subs, shots)
    assert placed == [(round(0.5 * US), 7 * US, "多住几天"), (10 * US, 2 * US, "格桑")] and warns == []


def test_place_subs_clips_to_shot_and_warns_when_cut():
    placed, warns = place_subs({"c1": [{"start": 1, "end": 9, "text": "长句"}]}, [_shot("c1", 4, 3, 10)])
    assert placed == [(10 * US, 3 * US, "长句")]
    assert warns and "长句" in warns[0]


def test_place_subs_skips_lines_outside_cut():
    placed, warns = place_subs({"c1": [{"start": 20, "end": 22, "text": "没用上"}]}, [_shot("c1", 0, 5, 0)])
    assert placed == [] and "没用上" in warns[0]


def test_duck_keyframes_ramp_around_speech_and_merge_close_lines():
    r = US // 4
    kf = duck_keyframes([(10 * US, 2 * US), (12 * US + US // 10, US)], 5 * US, 60 * US, 0.2, 0.05, ramp=r)
    # 两句只隔 0.1s：合并成一段，不在中间把音乐拉起来又压下
    assert kf == [(5 * US - r, 0.2), (5 * US, 0.05), (8 * US + US // 10, 0.05), (8 * US + US // 10 + r, 0.2)]


def test_duck_keyframes_clamped_to_segment():
    kf = duck_keyframes([(0, 2 * US)], 0, 10 * US, 0.2, 0.05, ramp=US // 4)
    assert kf[0] == (0, 0.05) and all(0 <= t <= 10 * US for t, _ in kf)

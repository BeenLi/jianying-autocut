import math
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


# ---------- 旁白模式：BGM 稳定曲线 ----------

from build import bgm_curve


def _val(kf, off):
    """关键帧折线在 off 处的值。"""
    kf = sorted(kf)
    if off <= kf[0][0]:
        return kf[0][1]
    for (a, va), (b, vb) in zip(kf, kf[1:]):
        if a <= off <= b:
            return va if b == a else va + (vb - va) * (off - a) / (b - a)
    return kf[-1][1]


def test_bgm_curve_stays_ducked_through_short_gaps():
    kf = bgm_curve([(1 * US, 3 * US), (6 * US, 3 * US)], [], [], 0, 12 * US, 0.5, 0.25, total_us=12 * US)
    assert all(abs(v - 0.125) < 1e-9 for _, v in kf)


def test_bgm_curve_rises_on_long_gap_with_asymmetric_ramps():
    kf = bgm_curve([(1 * US, 3 * US), (10 * US, 2 * US)], [], [], 0, 13 * US, 0.5, 0.25, total_us=13 * US)
    assert _val(kf, 4 * US) == 0.125 and _val(kf, round(4.8 * US)) == 0.5      # 升起 0.8s
    assert _val(kf, round(9.7 * US)) == 0.5 and _val(kf, 10 * US) == 0.125     # 压低 0.3s，开口前压好
    assert _val(kf, 11 * US) == 0.125


def test_bgm_curve_drop_and_up():
    speech = [(1 * US, 3 * US), (6 * US, 3 * US)]
    kf = bgm_curve(speech, [(4 * US, 2 * US)], [], 0, 12 * US, 0.5, 0.25, total_us=12 * US)
    assert _val(kf, 5 * US) == 0.5 and _val(kf, 7 * US) == 0.125
    kf = bgm_curve(speech, [], [(4 * US, 2 * US)], 0, 12 * US, 0.5, 0.25, total_us=12 * US)
    assert _val(kf, 5 * US) == 0 and _val(kf, 7 * US) == 0.125


def test_bgm_curve_offsets_are_segment_relative():
    kf = bgm_curve([(1 * US, 3 * US), (10 * US, 2 * US)], [], [], 5 * US, 4 * US, 0.5, 0.25, total_us=13 * US)
    # 片段覆盖成片 5–9s：5s 处已升到 0.5，9.7s 才开始压，所以整段都是 0.5
    assert kf[0][0] == 0 and kf[-1][0] == 4 * US
    assert all(v == 0.5 for _, v in kf)


def test_duck_keyframes_merge_gap():
    speech = [(1 * US, 2 * US), (round(4.5 * US), 2 * US)]     # 间隔 1.5s
    assert len(duck_keyframes(speech, 0, 10 * US, 0.2, 0.05)) == 8
    assert len(duck_keyframes(speech, 0, 10 * US, 0.2, 0.05, merge_gap=2 * US)) == 4


# ---------- 小问题修复 ----------

from build import bgm_plan_mix, talk_voice_levels


class _FakeCache:
    def __init__(self):
        self.calls = []

    def measure(self, path, start=None, end=None):
        self.calls.append((path, start, end))
        return {"i": -20.0, "tp": -3.0, "short": [(t / 10, -20.0 if t < 50 else -40.0) for t in range(0, 200)]}


def test_talk_voice_levels_measure_each_source_once():            # B7
    shots = [{"source": "/a.mp4", "in_us": 0, "dur_us": 10 * US, "start_us": 0},
             {"source": "/b.mp4", "in_us": 2 * US, "dur_us": 5 * US, "start_us": 10 * US}]
    subs = [(1 * US, 2 * US, "x"), (6 * US, 2 * US, "y"), (11 * US, 1 * US, "z")]
    cache = _FakeCache()
    levels = talk_voice_levels(cache, subs, shots)
    assert sorted(p for p, _, _ in cache.calls) == ["/a.mp4", "/b.mp4"]
    assert levels[0] == -20.0 and levels[1] == -40.0            # 每句按自己区间的短时响度取值，不是整段最大


def test_bgm_plan_mix_shapes_segments():                           # C3
    cache = _FakeCache()
    plan = [{"path": "/s.mp3", "start_us": 0, "dur_us": 5 * US, "src_us": US, "gain": 0.3, "fade": 1.0},
            {"path": "/s.mp3", "start_us": 5 * US, "dur_us": 5 * US, "src_us": 9 * US, "gain": 0.3, "fade": 1.0}]
    plans = bgm_plan_mix(cache, plan)
    assert len(cache.calls) == 1
    assert [segs for segs, _, _ in plans] == [[(0, US, 5 * US)], [(5 * US, 9 * US, 5 * US)]]
    assert all(base == 0.3 for _, base, _ in plans)


def test_margin_hint_points_to_bgm_plan_when_beat_synced():      # 问题 6：--bgm-plan 时 --bgm 会被拒绝
    from build import margin_hint
    assert "bgm_plan.json" in margin_hint(bgm_plan=[{"path": "x"}]) and "--bgm" not in margin_hint(bgm_plan=[{"path": "x"}])
    assert "--bgm" in margin_hint(bgm_plan=None)


def test_bgm_mix_ducks_by_actual_voice_and_ignores_drops():      # 问题 13
    from types import SimpleNamespace
    from build import bgm_mix
    song = SimpleNamespace(duration=20 * US)
    bgms = [{"path": "/s.mp3", "gain": 1.0, "fade": 1.0}]
    speech = [(1 * US, 2 * US), (6 * US, 2 * US)]                # 第一句时歌 -20，第二句时 -40
    _, duck = bgm_mix(_FakeCache(), bgms, [song], 10 * US, speech, voice_of=lambda t: -26.0)
    assert abs(20 * math.log10(duck) - (-26 - 12 + 20)) < 1e-6  # 按实际人声 -26 算：-18 dB
    _, duck = bgm_mix(_FakeCache(), bgms, [song], 10 * US, speech, voice_of=lambda t: -26.0, skip=[(0, 5 * US)])
    assert duck == 0.25                                          # 第一句在 drop 里（BGM 已淡出），不参与


def test_bgm_level_respects_drops_and_ups():                     # 问题 14：drop 里 BGM 已淡出，不该报音量差
    from build import bgm_level_fn
    plans = [([(0, 0, 20 * US)], 1.0, {"short": [(t / 10, -20.0) for t in range(200)]})]
    f = bgm_level_fn(plans, 0.25, drops=[(5 * US, 5 * US)], ups=[(12 * US, 3 * US)])
    assert f(6 * US, 8 * US) is None                             # 整句在 drop 里：没有 BGM
    assert abs(f(1 * US, 2 * US) - (-20 + 20 * math.log10(0.25))) < 1e-6   # 平时：压低档
    assert abs(f(12.5 * US, 13 * US) - (-20.0)) < 1e-6           # up：不压低

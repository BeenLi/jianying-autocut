import pytest

from beatsync import energy_sections, music_len, retime, snap_cuts
from common import US


def _song(dur_s, first_s=1.0, step_s=0.5):
    n = int((dur_s - first_s) / step_s) + 1
    return {"path": "/m/a.mp3", "tempo": 120.0, "dur": round(dur_s * US),
            "beats": [round((first_s + i * step_s) * US) for i in range(n)]}


def _rows(chapters):
    """chapters: 每项是该章各镜头的秒数。"""
    rows, t = [], 0
    for no, shots in enumerate(chapters, 1):
        for sec in shots:
            d = round(sec * US)
            rows.append({"chapter_no": no, "chapter": no, "source": "/x/a.mp4", "name": "a.mp4",
                         "in_us": 10 * US, "dur_us": d, "start_us": t})
            t += d
    return rows


CLIP = {"/x/a.mp4": 3600 * US}


def _ends(rows):
    return [r["start_us"] + r["dur_us"] for r in rows]


def test_long_song_does_not_stretch_short_film():
    rows, bgm = retime(_rows([[5, 5], [5, 5]]), [_song(200)], [1], CLIP, {})
    total = _ends(rows)[-1]
    assert abs(total - 20 * US) <= 1 * US          # 落在最近的小节线，不拉伸到整首歌
    assert bgm[0]["dur_us"] == total


def test_song_plays_to_natural_end_when_length_is_close():
    rows, bgm = retime(_rows([[10, 9]]), [_song(21)], [1], CLIP, {})
    assert _ends(rows)[-1] == 20 * US and bgm[0]["src_us"] == 1 * US


def test_song_too_short_is_an_error():
    with pytest.raises(ValueError, match="歌"):
        retime(_rows([[60, 60]]), [_song(30)], [1], CLIP, {})


def test_cuts_land_on_beats_and_stay_gapless():
    rows, _ = retime(_rows([[3.2, 4.1, 2.7, 6.3]]), [_song(200)], [1], CLIP, {})
    for e in _ends(rows):
        assert e % (US // 2) == 0
    for prev, r in zip(rows, rows[1:]):
        assert prev["start_us"] + prev["dur_us"] == r["start_us"]


def test_chapter_change_lands_on_bar():
    rows, _ = retime(_rows([[3.3, 4.4], [3.1, 5.2]]), [_song(200)], [1], CLIP, {})
    first_of_ch2 = next(r for r in rows if r["chapter_no"] == 2)
    assert first_of_ch2["start_us"] % (2 * US) == 0   # 4 拍 × 0.5s = 一小节 2s


def test_anchor_puts_chapter_on_music_moment():
    # 第 2 章要落在歌的第 21 秒（首拍 1s，对应成片第 20 秒）
    rows, bgm = retime(_rows([[5, 5, 5], [5, 5]]), [_song(200)], [1], CLIP, {2: 21 * US})
    first_of_ch2 = next(r for r in rows if r["chapter_no"] == 2)
    assert first_of_ch2["start_us"] == 20 * US and bgm[0]["src_us"] == 1 * US


def test_anchor_on_first_chapter_skips_song_intro():
    rows, bgm = retime(_rows([[5, 5]]), [_song(200)], [1], CLIP, {1: 41 * US})
    assert rows[0]["start_us"] == 0 and bgm[0]["src_us"] == 41 * US


def test_anchor_before_previous_section_is_an_error():
    with pytest.raises(ValueError, match="--anchor"):
        retime(_rows([[5], [5], [5]]), [_song(200)], [1], CLIP, {2: 41 * US, 3: 21 * US})


def test_music_len_nearest_bar():
    bars = [2 * US * i for i in range(1, 50)]
    assert music_len(5 * US, bars, 100 * US, last=False) == 6 * US or music_len(5 * US, bars, 100 * US, last=False) == 4 * US


def test_energy_sections_find_the_rise():
    bars = [2 * US * i for i in range(12)]
    rms = [1, 1, 1, 1, 1, 1, 1, 1, 9, 9, 9, 9]
    assert [(s["start_us"], s["level"]) for s in energy_sections(bars, rms, 24 * US)] == [(0, "low"), (16 * US, "high")]


def test_energy_sections_absorb_one_bar_blips():
    bars = [2 * US * i for i in range(9)]
    rms = [1, 1, 1, 1, 9, 1, 1, 1, 1]
    assert len(energy_sections(bars, rms, 18 * US)) == 1


def test_snap_cuts_strong_uses_bar_grid():
    grid = [US * i // 2 for i in range(1, 40)]
    bars = [2 * US * i for i in range(1, 10)]
    assert snap_cuts([5 * US, 9 * US], grid, 0, 20 * US, strong={1}, bars=bars) == [5 * US, 8 * US]


def test_energy_sections_flat_song_has_no_fake_contrast():
    bars = [2 * US * i for i in range(12)]
    rms = [1.00, 1.02, 0.98, 1.01, 0.99, 1.03, 0.97, 1.00, 1.02, 0.98, 1.01, 0.99]
    assert [s["level"] for s in energy_sections(bars, rms, 24 * US)] == ["mid"]


def test_energy_sections_small_jitter_inside_loud_part_does_not_flap():
    bars = [2 * US * i for i in range(16)]
    rms = [1.0] * 6 + [3.0, 3.1, 2.9, 3.05, 2.95, 3.1, 2.9, 3.0, 3.05, 2.95]
    assert [s["level"] for s in energy_sections(bars, rms, 32 * US)] == ["low", "high"]


def test_anchor_before_first_beat_explains_itself():
    with pytest.raises(ValueError, match="首拍"):
        retime(_rows([[5], [5]]), [_song(200, first_s=40.0)], [1], CLIP, {2: 20 * US})


def test_missed_anchor_warns_with_offset(capsys):
    rows = _rows([[10], [5]])
    clip = {"/x/a.mp4": 3600 * US, "/x/short.mp4": 12 * US}
    rows[0]["source"] = "/x/short.mp4"
    rows[0]["in_us"] = 1 * US
    out, _ = retime(rows, [_song(200)], [1], clip, {2: 41 * US})      # 第 1 章要撑到 40s，素材只有 12s
    assert next(r for r in out if r["chapter_no"] == 2)["start_us"] < 40 * US
    assert "没对上 anchor" in capsys.readouterr().out


def test_cut_moves_to_nearby_beat_to_finish_a_sentence():
    # 第一个镜头取素材 10s 起；素材 13–16s 有一句话。最近的拍点 5.0s（素材 15s）会切在话中间，挪到 6.0s（素材 16s，话说完）
    speech = {"/x/a.mp4": [(13 * US, 16 * US)]}
    rows, _ = retime(_rows([[5.2, 5.0]]), [_song(200)], [1], CLIP, {}, speech=speech)
    assert _ends(rows)[0] == 6 * US


def test_cut_stays_on_nearest_beat_when_no_clean_beat_is_close():
    speech = {"/x/a.mp4": [(0, 60 * US)]}          # 一直在说话：避不开就按原规则
    rows, _ = retime(_rows([[5.2, 5.0]]), [_song(200)], [1], CLIP, {}, speech=speech)
    assert _ends(rows)[0] == 5 * US


def test_beatsync_refuses_narration_work(tmp_path, monkeypatch):
    import sys

    import beatsync
    (tmp_path / "narration_track.json").write_text("{}")
    monkeypatch.setattr(sys, "argv", ["beatsync.py", "--work", str(tmp_path), "--song", "/m/a.mp3"])
    with pytest.raises(SystemExit, match="旁白"):
        beatsync.main()

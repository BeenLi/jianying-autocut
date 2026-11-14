import math
import os

from common import US
from loudness import Cache, bed_gain, bgm_duck, margin_warnings, max_short, parse_ebur128, voice_gain

SAMPLE = """[Parsed_ebur128_0 @ 0x1] t: 0.0999773  TARGET:-23 LUFS    M:-120.7 S:-120.7     I: -70.0 LUFS       LRA:   0.0 LU  FTPK: -18.1 dBFS  TPK: -18.1 dBFS
[Parsed_ebur128_0 @ 0x1] t: 2.999977   TARGET:-23 LUFS    M: -21.8 S: -21.8     I: -21.8 LUFS       LRA:  20.0 LU  FTPK: -18.1 dBFS  TPK: -18.1 dBFS
[Parsed_ebur128_0 @ 0x1] t: 3.099977   TARGET:-23 LUFS    M: -19.0 S: -20.5     I: -21.8 LUFS       LRA:  20.0 LU  FTPK: -18.1 dBFS  TPK: -18.1 dBFS
[Parsed_ebur128_0 @ 0x1] Summary:
  Integrated loudness:
    I:         -21.8 LUFS
    Threshold: -31.8 LUFS
  True peak:
    Peak:      -18.1 dBFS
"""


def db(g):
    return 20 * math.log10(g)


def test_parse_ebur128():
    r = parse_ebur128(SAMPLE)
    assert r["i"] == -21.8 and r["tp"] == -18.1
    assert r["short"] == [(0.1, -120.7), (3.0, -21.8), (3.1, -20.5)]


def test_max_short_in_range():
    short = [(0.1, -120.7), (3.0, -21.8), (3.1, -20.5)]
    assert max_short(short, 2.9, 3.2) == -20.5
    assert max_short(short, 5.0, 6.0) is None


def test_voice_gain_reaches_target():
    g, short = voice_gain(-22.0, -10.0)
    assert round(db(g), 6) == 6.0 and short == 0


def test_voice_gain_capped_at_plus_12():
    g, short = voice_gain(-32.0, -30.0)
    assert round(db(g), 6) == 12.0 and round(short, 6) == 4.0


def test_voice_gain_capped_by_true_peak():
    g, short = voice_gain(-22.0, -4.0)            # 想提 6dB，但峰值只容得下 3dB
    assert round(db(g), 6) == 3.0 and round(short, 6) == 3.0


def test_voice_gain_attenuates_loud_voice():
    g, short = voice_gain(-10.0, -1.0)
    assert round(db(g), 6) == -6.0 and short == 0


def test_bed_gain_capped():
    assert bed_gain(-40.0) == 0.15                   # 很小声的素材：要提，但最多 0.15
    assert round(db(bed_gain(-14.0)), 6) == -20.0    # -16-18-(-14) = -20 dB


def test_bgm_duck_most_conservative_and_capped():
    assert bgm_duck([]) == 0.25
    assert bgm_duck([(-14.0, -20.0)]) == 0.25        # 歌本身很小：默认压低就够
    d = bgm_duck([(-6.0, -8.0), (-6.0, -12.0)])      # 需要 -8-6+x ≤ -28 → x ≤ -14 dB
    assert round(db(d), 6) == -14.0


def test_margin_warnings_threshold():
    spans = [(0, 2 * US), (10 * US, 2 * US)]
    levels = [-16.0, -16.0]
    bgm = lambda a_us, b_us: -27.9 if a_us < 5 * US else -28.0
    w = margin_warnings(spans, bgm, levels)
    assert len(w) == 1 and "0:00.0" in w[0] and "11.9" in w[0]


def test_margin_warnings_no_bgm():
    assert margin_warnings([(0, US)], lambda a, b: None, [-16.0]) == []


def test_cache_invalidates_on_mtime(tmp_path):          # Review Focus 5
    f = tmp_path / "vo.m4a"
    f.write_bytes(b"abc")
    c = Cache(str(tmp_path))
    c.put(str(f), {"i": -20.0, "tp": -3.0})
    assert Cache(str(tmp_path)).get(str(f)) == {"i": -20.0, "tp": -3.0}
    st = os.stat(f)
    os.utime(f, (st.st_atime, st.st_mtime + 10))
    assert Cache(str(tmp_path)).get(str(f)) is None


def test_cache_key_extra_separates_ranges(tmp_path):
    f = tmp_path / "c.mp4"
    f.write_bytes(b"x")
    c = Cache(str(tmp_path))
    c.put(str(f), {"i": -30.0, "tp": -9.0}, key_extra="1.0-3.0")
    assert c.get(str(f)) is None and c.get(str(f), key_extra="1.0-3.0")["i"] == -30.0


# ---------- 小问题修复 ----------

import subprocess

import pytest

import loudness
from loudness import mean_short


def test_measure_raises_when_ffmpeg_fails(monkeypatch):         # B6
    monkeypatch.setattr(loudness.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "No such file"))
    with pytest.raises(subprocess.CalledProcessError):
        loudness.measure("/nope.m4a")


def test_cached_empty_measurement_is_remeasured(tmp_path, monkeypatch):
    f = tmp_path / "vo.m4a"
    f.write_bytes(b"x")
    c = Cache(str(tmp_path))
    c.put(str(f), {"i": -70.0, "tp": -70.0, "short": []})      # 旧版本缓存下的失败结果
    monkeypatch.setattr(loudness, "measure", lambda p, a=None, b=None: {"i": -20.0, "tp": -3.0, "short": [(0.1, -20.0)]})
    assert c.measure(str(f))["i"] == -20.0


def test_cache_prunes_stale_keys_of_same_path(tmp_path):        # B10
    f = tmp_path / "vo.m4a"
    f.write_bytes(b"x")
    c = Cache(str(tmp_path))
    c.put(str(f), {"i": -1.0}, key_extra="1-2")
    c.put(str(f), {"i": -2.0})
    st = os.stat(f)
    os.utime(f, (st.st_atime, st.st_mtime + 10))
    c.put(str(f), {"i": -3.0})
    assert len(c.data) == 1 and list(c.data.values()) == [{"i": -3.0}]


def test_cache_corrupt_file_starts_fresh(tmp_path):
    (tmp_path / "loudness.json").write_text("{bad")
    assert Cache(str(tmp_path)).data == {}


def test_mean_short_is_energy_mean():                           # B7
    v = mean_short([(0.1, -20.0), (0.2, -30.0), (5.0, 0.0)], 0.0, 1.0)
    assert abs(v - 10 * math.log10((10 ** -2 + 10 ** -3) / 2)) < 1e-9
    assert mean_short([(0.1, -20.0)], 3.0, 4.0) is None


def test_margin_warnings_custom_hint():                          # 问题 6
    w = margin_warnings([(0, US)], lambda a, b: -20.0, [-16.0], hint="调低 bgm_plan.json 里的 gain")
    assert len(w) == 1 and w[0].endswith("调低 bgm_plan.json 里的 gain") and "--bgm" not in w[0]


def test_bgm_duck_uses_actual_voice_level():                     # 问题 13：人声没提到 -16 时 BGM 要压得更低
    d = bgm_duck([(-6.0, -8.0, -22.0)])                          # -22-12-(-8)-(-6) = -20 dB
    assert round(db(d), 6) == -20.0

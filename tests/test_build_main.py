import shutil
import json
import os
import sys

import pytest

import build

FIELDS = ["clip_id", "path", "name", "folder", "duration_s", "width", "height", "fps",
          "has_audio", "rotation", "shot_time", "size_mb", "speech_score"]


def _setup(tmp_path):
    from common import write_csv
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [{"draft_name": "x", "draft_new_version": "164.0.0", "tm_draft_modified": 1}]}))
    old = drafts / "旧草稿"
    old.mkdir()
    (old / "keep.txt").write_text("user work")
    work = tmp_path / "work"
    work.mkdir()
    media = tmp_path / "a.mp4"
    media.write_bytes(b"0")
    write_csv(str(work / "inventory.csv"), [{"clip_id": "c001", "path": str(media), "name": "a.mp4", "folder": "w",
              "duration_s": 20, "width": 1920, "height": 1080, "fps": 30, "has_audio": "True", "rotation": 0,
              "shot_time": "2026", "size_mb": 1, "speech_score": 0}], FIELDS)
    write_csv(str(work / "shots.csv"), [{"idx": 1, "chapter": 1, "chapter_title": "开场", "chapter_function": "hook",
              "kind": "long", "name": "a.mp4", "source": str(media), "in_s": 1, "dur_s": 5, "start_s": 0,
              "in_us": 1000000, "dur_us": 5000000, "start_us": 0, "score": 0.5}],
              ["idx", "chapter", "chapter_title", "chapter_function", "kind", "name", "source", "in_s", "dur_s",
               "start_s", "in_us", "dur_us", "start_us", "score"])
    return drafts, work, old


def _run(monkeypatch, *argv):
    monkeypatch.setattr(build, "jianying_running", lambda: False)
    monkeypatch.setattr(sys, "argv", ["build.py", *argv])
    build.main()


@pytest.mark.parametrize("name", ["", ".", "..", "a/b"])
def test_bad_names_rejected(tmp_path, monkeypatch, name):
    drafts, work, old = _setup(tmp_path)
    with pytest.raises(SystemExit):
        _run(monkeypatch, "--work", str(work), "--name", name, "--drafts-dir", str(drafts), "--replace")
    assert (old / "keep.txt").exists()


def test_replace_keeps_old_draft_when_inputs_missing(tmp_path, monkeypatch):
    drafts, work, old = _setup(tmp_path)
    with pytest.raises((SystemExit, FileNotFoundError)):
        _run(monkeypatch, "--work", str(tmp_path / "nope"), "--name", "旧草稿", "--drafts-dir", str(drafts), "--replace")
    assert (old / "keep.txt").exists()


def test_build_happy_path_verifies(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    _run(monkeypatch, "--work", str(work), "--name", "新草稿", "--drafts-dir", str(drafts), "--titles")
    d = json.load(open(drafts / "新草稿" / "draft_info.json"))
    assert d["new_version"] == "164.0.0" and d["duration"] == 5000000


def test_canvas_ignores_unused_clips(tmp_path, monkeypatch):
    from common import read_csv, write_csv
    drafts, work, _ = _setup(tmp_path)
    rows = read_csv(str(work / "inventory.csv"))
    big = tmp_path / "big.mp4"
    big.write_bytes(b"0")
    rows.append(dict(rows[0], clip_id="c002", path=str(big), name="big.mp4", width=3840, height=2160))
    write_csv(str(work / "inventory.csv"), rows, FIELDS)
    _run(monkeypatch, "--work", str(work), "--name", "画布", "--drafts-dir", str(drafts))
    d = json.load(open(drafts / "画布" / "draft_info.json"))
    assert d["canvas_config"]["width"] == 1920


def test_rotated_clip_gets_180(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    (work / "orientation.json").write_text(json.dumps({"clips": {"c001": {"rotate": 180, "bad": []}}}))
    _run(monkeypatch, "--work", str(work), "--name", "转正", "--drafts-dir", str(drafts))
    d = json.load(open(drafts / "转正" / "draft_info.json"))
    seg = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"][0]
    assert seg["clip"]["rotation"] == 180


# ---------- 旁白模式 ----------

import loudness


def _narration(tmp_path, work, live=True, bgm_marks=()):
    from common import write_csv
    media2 = tmp_path / "b.mp4"
    media2.write_bytes(b"0")
    vo = tmp_path / "vo.m4a"
    vo.write_bytes(b"0")
    from common import read_csv
    inv = read_csv(str(work / "inventory.csv"))
    inv.append(dict(inv[0], clip_id="c002", path=str(media2), name="b.mp4"))
    write_csv(str(work / "inventory.csv"), inv, FIELDS)
    cols = ["idx", "chapter", "chapter_title", "chapter_function", "kind", "name", "source", "in_s", "dur_s",
            "start_s", "in_us", "dur_us", "start_us", "score"]
    rows = [{"idx": 1, "chapter": 1, "chapter_title": "出发", "chapter_function": "", "kind": "narr", "name": "a.mp4",
             "source": str(tmp_path / "a.mp4"), "in_s": 1, "dur_s": 5, "start_s": 0, "in_us": 1000000,
             "dur_us": 5000000, "start_us": 0, "score": 0.5}]
    if live:
        rows.append({"idx": 2, "chapter": 1, "chapter_title": "出发", "chapter_function": "", "kind": "live",
                     "name": "b.mp4", "source": str(media2), "in_s": 2, "dur_s": 3, "start_s": 5, "in_us": 2000000,
                     "dur_us": 3000000, "start_us": 5000000, "score": 0.5})
    write_csv(str(work / "shots.csv"), rows, cols)
    total = 8000000 if live else 5000000
    track = {"audio": [{"fid": "n1", "file": str(vo), "src_us": 300000, "start_us": 700000, "dur_us": 4000000,
                        "fade_in_us": 15000, "fade_out_us": 15000}],
             "subs": [{"start_us": 1000000, "dur_us": 3500000, "text": "出发"}],
             "speech": [[1000000, 3500000]] + ([[5500000, 1000000]] if live else []),
             "live": [{"start_us": 5000000, "dur_us": 3000000, "clip_id": "c002", "src_us": 2000000}] if live else [],
             "bgm": list(bgm_marks), "total_us": total}
    (work / "narration_track.json").write_text(json.dumps(track, ensure_ascii=False))
    (work / "narration_speech.json").write_text(json.dumps(
        {"files": {"n1": str(vo)}, "durations": {"n1": 30.0}, "lines": {}, "silences": {}}))
    (work / "speech.json").write_text(json.dumps({"c002": [{"start": 2.5, "end": 3.5, "text": "哇"}]}))
    return vo


def _fake_measure(monkeypatch, levels, norm_fail=None):
    """假测量 + 假归一化：副本 <名>.wav 的响度默认 -16 / -1.6（levels 里可单独给）。"""
    import normalize
    levels = {"vo.wav": (-16.0, -1.6), **levels}

    def m(path, start=None, end=None):
        i, tp = levels[os.path.basename(path)]
        return {"i": i, "tp": tp, "short": [(t / 10, i if t % 10 else i - 25) for t in range(0, 600)]}

    def norm(path, out_dir, cache, short_s=3.0, name=None):
        if norm_fail:
            raise norm_fail
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, (name or os.path.splitext(os.path.basename(path))[0]) + ".wav")
        open(out, "wb").write(b"0")
        return out, {"type": "dynamic", "short": False}
    monkeypatch.setattr(loudness, "measure", m)
    monkeypatch.setattr(normalize, "normalize", norm)


def _segs(d, name):
    return [s for t in d["tracks"] if t.get("name") == name for s in t["segments"]]


def test_build_main_narration(tmp_path, monkeypatch, capsys):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work)
    _fake_measure(monkeypatch, {"vo.m4a": (-22.0, -10.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "旁白片", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"))
    d = json.load(open(drafts / "旁白片" / "draft_info.json"))
    vo = _segs(d, "旁白")
    assert len(vo) == 1 and vo[0]["volume"] == 1.0          # 副本已归一化到 -16 LUFS，剪映里不再放大
    assert vo[0]["target_timerange"] == {"start": 700000, "duration": 4000000}
    mat = next(a for a in d["materials"]["audios"] if a["id"] == vo[0]["material_id"])
    assert mat["path"] == str(work / "旁白_归一化" / "vo.wav") and mat["duration"] == 30000000
    video = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]
    assert abs(video[0]["volume"] - loudness.bed_gain(-30.0)) < 1e-6
    assert abs(video[1]["volume"] - loudness.voice_gain(-30.0, -10.0)[0]) < 1e-6
    texts = json.dumps(d["materials"].get("texts", []), ensure_ascii=False)
    assert "出发" in texts
    out = capsys.readouterr().out
    assert "✓" in out and "待真机验证" not in out      # 剪映 11.8.0 实测认 >100% 的音量（2026-11-17）
    assert "vo.m4a -22.0 → -16.0 LUFS（限幅）" in out and str(work / "旁白_归一化") in out


def test_narration_copy_short_of_target_reports_too_quiet(tmp_path, monkeypatch, capsys):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    _fake_measure(monkeypatch, {"vo.m4a": (-30.0, -2.0), "vo.wav": (-25.7, -1.5), "a.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "短", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"))
    out = capsys.readouterr().out
    assert "太小声" in out and "9.7 dB" in out


def test_narration_normalize_failure_exits(tmp_path, monkeypatch):           # Review Focus 3
    import subprocess
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    for err in (subprocess.CalledProcessError(1, ["ffmpeg"]), FileNotFoundError("ffmpeg")):
        _fake_measure(monkeypatch, {"vo.m4a": (-30.0, -2.0), "a.mp4": (-30.0, -10.0)}, norm_fail=err)
        with pytest.raises(SystemExit, match="归一化失败.*vo.m4a"):
            _run(monkeypatch, "--work", str(work), "--name", "坏", "--drafts-dir", str(drafts),
                 "--narration", str(work / "narration_track.json"))
        assert not (drafts / "坏").exists()


def test_build_main_narration_without_bgm_or_live(tmp_path, monkeypatch):      # Review Focus 4
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -6.0), "a.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "纯旁白", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"))
    d = json.load(open(drafts / "纯旁白" / "draft_info.json"))
    assert len(_segs(d, "旁白")) == 1 and _segs(d, "BGM") == []


def test_build_rejects_narration_with_bgm_plan(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work)
    (work / "bgm_plan.json").write_text("[]")
    with pytest.raises(SystemExit, match="卡点"):
        _run(monkeypatch, "--work", str(work), "--name", "x", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"), "--bgm-plan", str(work / "bgm_plan.json"))


def test_narration_subs_only_on_live_shots(tmp_path, monkeypatch):            # Important 7
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work)
    (work / "subtitles.json").write_text(json.dumps(
        {"c001": [{"start": 2.0, "end": 4.0, "text": "垫底里的话"}], "c002": [{"start": 2.2, "end": 3.0, "text": "哇哦"}]},
        ensure_ascii=False))
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -6.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "字幕", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"), "--subs", str(work / "subtitles.json"))
    texts = json.dumps(json.load(open(drafts / "字幕" / "draft_info.json"))["materials"].get("texts", []), ensure_ascii=False)
    assert "哇哦" in texts and "垫底里的话" not in texts


def test_build_rejects_bgm_plan_with_bgm(tmp_path, monkeypatch):   # B7
    drafts, work, _ = _setup(tmp_path)
    (work / "bgm_plan.json").write_text("[]")
    with pytest.raises(SystemExit, match="--bgm-plan"):
        _run(monkeypatch, "--work", str(work), "--name", "x", "--drafts-dir", str(drafts),
             "--bgm-plan", str(work / "bgm_plan.json"), "--bgm", str(tmp_path / "a.mp4"))


def test_broken_orientation_json_keeps_old_draft(tmp_path, monkeypatch):   # A4
    drafts, work, old = _setup(tmp_path)
    (work / "orientation.json").write_text("{bad")
    with pytest.raises(SystemExit, match="orientation.json"):
        _run(monkeypatch, "--work", str(work), "--name", "旧草稿", "--drafts-dir", str(drafts), "--replace")
    assert (old / "keep.txt").exists()


def _mute_shots(work, tmp_path):
    """两个垫底镜头：a.mp4 标了 mute，b.mp4 没标（总长和 live=False 的轨道一致）。"""
    from common import write_csv
    import plan
    rows = [{"idx": 1, "chapter": 1, "chapter_title": "出发", "chapter_function": "", "kind": "narr", "name": "a.mp4",
             "source": str(tmp_path / "a.mp4"), "in_s": 1, "dur_s": 2.5, "start_s": 0, "in_us": 1000000,
             "dur_us": 2500000, "start_us": 0, "score": 0.5, "mute": "1"},
            {"idx": 2, "chapter": 1, "chapter_title": "出发", "chapter_function": "", "kind": "narr", "name": "b.mp4",
             "source": str(tmp_path / "b.mp4"), "in_s": 1, "dur_s": 2.5, "start_s": 2.5, "in_us": 1000000,
             "dur_us": 2500000, "start_us": 2500000, "score": 0.5, "mute": ""}]
    write_csv(str(work / "shots.csv"), rows, plan.FIELDS)


def test_muted_narr_shot_volume_zero_even_with_volume_flag(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    _mute_shots(work, tmp_path)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -6.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "消音", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"), "--volume", "0.3")
    d = json.load(open(drafts / "消音" / "draft_info.json"))
    video = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]
    assert [v["volume"] for v in video] == [0.0, 0.3]


def test_muted_only_clip_bed_is_not_measured(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    _mute_shots(work, tmp_path)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -6.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    seen = []
    m0 = loudness.measure
    monkeypatch.setattr(loudness, "measure", lambda p, *a: seen.append(os.path.basename(p)) or m0(p, *a))
    _run(monkeypatch, "--work", str(work), "--name", "消音2", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"))
    d = json.load(open(drafts / "消音2" / "draft_info.json"))
    video = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]
    assert video[0]["volume"] == 0.0 and abs(video[1]["volume"] - loudness.bed_gain(-30.0)) < 1e-6
    assert "a.mp4" not in seen


def test_old_shots_csv_without_mute_column_builds(tmp_path, monkeypatch):      # Review Focus 1
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)          # _narration 写的 shots.csv 没有 mute 列
    assert "mute" not in (work / "shots.csv").read_text().splitlines()[0]
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -6.0), "a.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "旧表", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"), "--volume", "0.3")
    d = json.load(open(drafts / "旧表" / "draft_info.json"))
    assert [t for t in d["tracks"] if t["type"] == "video"][0]["segments"][0]["volume"] == 0.3


class _LiveCache:
    """narration_mix 的原声段只用 cache.measure(path, a, b)：返回固定的人声响度、真峰值和短时响度（定底噪）。"""
    def __init__(self, i, tp, floor):
        self.m = {"i": i, "tp": tp, "short": [(0, floor), (1, i)]}

    def measure(self, path, a=None, b=None):
        return self.m


def _live_mix(i, tp, floor):
    narr = {"audio": [], "live": [{"clip_id": "c001", "src_us": 0, "dur_us": 8_000_000, "start_us": 0}]}
    inv = {"c001": {"clip_id": "c001", "path": "/x/a.mp4", "has_audio": "True"}}
    speech = {"c001": [{"start": 0.5, "end": 7.5, "text": "x"}]}
    _, live_gain, _, level, notes, _ = build.narration_mix(_LiveCache(i, tp, floor), narr, [], inv, speech, "/x/n")
    return live_gain["c001"], level["live:c001"], notes


def test_live_segments_target_minus_19():
    g, lv, notes = _live_mix(-25.0, -10.0, -60.0)
    assert lv == pytest.approx(-19.0) and g == pytest.approx(10 ** (6 / 20))
    g, lv, _ = _live_mix(-18.0, -1.2, -60.0)       # 偏响的也拉到 -19，几段原声一样响
    assert lv == pytest.approx(-19.0) and g < 1


def test_noisy_live_is_still_boosted_with_warning():
    g, lv, notes = _live_mix(-30.8, -11.4, -35.0)   # 人声只比底噪高 4.2 dB
    assert g > 1 and lv == pytest.approx(-20.4)      # 被真峰值 -1 dBTP 卡在 +10.4 dB
    assert any("c001" in n and "底噪" in n for n in notes)
    assert any("c001" in n and "还差 1.4 dB" in n for n in notes)


def test_normalize_failure_message_names_the_real_cause(tmp_path, monkeypatch):
    import subprocess
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    bad = subprocess.CalledProcessError(1, ["ffmpeg"], "", "...\nvo.m4a: Invalid data found when processing input\n")
    _fake_measure(monkeypatch, {"vo.m4a": (-30.0, -2.0), "a.mp4": (-30.0, -10.0)}, norm_fail=bad)
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, "--work", str(work), "--name", "坏", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"))
    assert "Invalid data found" in str(e.value) and "需要 ffmpeg" not in str(e.value)
    _fake_measure(monkeypatch, {"vo.m4a": (-30.0, -2.0), "a.mp4": (-30.0, -10.0)}, norm_fail=FileNotFoundError("ffmpeg"))
    with pytest.raises(SystemExit, match="没找到 ffmpeg"):
        _run(monkeypatch, "--work", str(work), "--name", "坏", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"))


def test_replace_keeps_old_draft_when_normalize_fails(tmp_path, monkeypatch):
    import subprocess
    drafts, work, old = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    _fake_measure(monkeypatch, {"vo.m4a": (-30.0, -2.0), "a.mp4": (-30.0, -10.0)},
                  norm_fail=subprocess.CalledProcessError(1, ["ffmpeg"]))
    with pytest.raises(SystemExit):
        _run(monkeypatch, "--work", str(work), "--name", "旧草稿", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"), "--replace")
    assert (old / "keep.txt").exists()


def test_missing_narration_file_is_reported_as_missing_not_ffmpeg(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work, live=False)
    _fake_measure(monkeypatch, {"vo.m4a": (-30.0, -2.0), "a.mp4": (-30.0, -10.0)}, norm_fail=FileNotFoundError("vo.m4a"))
    (tmp_path / "vo.m4a").unlink()
    with pytest.raises(SystemExit, match="旁白文件不存在.*vo.m4a"):
        _run(monkeypatch, "--work", str(work), "--name", "坏", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"))


# ---------- 效果（fx） ----------

import fx  # noqa: E402

FULL_FX = {
    "transitions": [{"shot": 1, "at_us": 5000000, "type": "叠化", "dur_us": 400000, "item": "L1", "vip": False}],
    "effects": [{"start_us": 1000000, "dur_us": 1000000, "type": "丁达尔光线", "item": "L1", "vip": False}],
    "filters": [{"shot": 2, "start_us": 5000000, "type": "夏日风吟", "intensity": 60, "item": "V1", "vip": False}],
    "intro": {"shot": 1, "type": "渐显", "dur_us": 500000, "vip": False},
    "outro": {"shot": 2, "type": "渐隐", "dur_us": 500000, "vip": False},
}


def _with_fx(work, fx_patch=None):
    """往 _narration() 写出的 track 里加 fx 段，shots_sig 按真实的 shots.csv 算。"""
    from common import read_csv
    track = json.loads((work / "narration_track.json").read_text())
    inv = {r["path"]: r["clip_id"] for r in read_csv(str(work / "inventory.csv"))}
    rows = read_csv(str(work / "shots.csv"))
    f = {"shots_sig": fx.shots_sig(rows, [inv[r["source"]] for r in rows]), "transitions": [], "effects": [], "filters": []}
    f.update(json.loads(json.dumps(FULL_FX if fx_patch is None else fx_patch)))
    track["fx"] = f
    (work / "narration_track.json").write_text(json.dumps(track, ensure_ascii=False))
    return f


def _fx_build(tmp_path, monkeypatch, fx_patch=None, name="旁白片", extra=()):
    drafts, work, old = _setup(tmp_path)
    _narration(tmp_path, work)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -3.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    f = _with_fx(work, fx_patch)
    _run(monkeypatch, "--work", str(work), "--name", name, "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"), *extra)
    return json.load(open(drafts / name / "draft_info.json")), f, drafts, work, old


def test_fx_attached_before_add_segment(tmp_path, monkeypatch, capsys):
    d, _, _, _, _ = _fx_build(tmp_path, monkeypatch)
    video = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]
    m = d["materials"]
    assert len(m["transitions"]) == 1 and m["transitions"][0]["id"] in video[0]["extra_material_refs"]
    assert m["transitions"][0]["duration"] == 400000
    flt = [e for e in m["effects"] if e.get("type") == "filter"]
    assert len(flt) == 1 and flt[0]["id"] in video[1]["extra_material_refs"] and abs(flt[0]["value"] - 0.6) < 1e-6
    anims = {a["type"]: a for ma in m["material_animations"] for a in ma["animations"]}
    assert anims["in"]["name"] == "渐显" and anims["out"]["name"] == "渐隐"
    assert anims["out"]["start"] == 3000000 - 500000
    eff = _segs(d, "特效")
    assert len(eff) == 1 and eff[0]["target_timerange"] == {"start": 1000000, "duration": 1000000}
    assert "✓" in capsys.readouterr().out


@pytest.mark.parametrize("breakit", ["sig", "oldsig", "shot", "at", "name"])
def test_preflight_fails_and_keeps_old_draft(tmp_path, monkeypatch, breakit):
    drafts, work, old = _setup(tmp_path)
    _narration(tmp_path, work)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -3.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    f = _with_fx(work)
    if breakit == "sig":
        f["shots_sig"] = f["shots_sig"][:-1] + ("0" if f["shots_sig"][-1] != "0" else "1")
    elif breakit == "oldsig":                                   # 按路径算的 v1 指纹
        f["shots_sig"] = f["shots_sig"].removeprefix("v2:")
    elif breakit == "shot":
        f["filters"][0]["shot"] = 9
    elif breakit == "at":
        f["transitions"][0]["at_us"] += 1
    else:
        f["intro"]["type"] = "不存在的动画"
    track = json.loads((work / "narration_track.json").read_text())
    track["fx"] = f
    (work / "narration_track.json").write_text(json.dumps(track, ensure_ascii=False))
    with pytest.raises(SystemExit, match="旧格式" if breakit == "oldsig" else "重跑 narrate.py"):
        _run(monkeypatch, "--work", str(work), "--name", "旧草稿", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"), "--replace")
    assert (old / "keep.txt").exists()


def _relocate(work, old, new):
    """派生目录的做法：把 shots.csv 和 inventory.csv 里的素材路径换成另一个位置的同名文件（clip_id 不变）。"""
    for f in ("shots.csv", "inventory.csv"):
        p = work / f
        p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_fx_survives_relocated_sources(tmp_path, monkeypatch):
    """在 W 跑 narrate 后复制到派生目录、换成调色副本的路径：指纹按 clip_id 算，build 照常通过。"""
    drafts, work, old = _setup(tmp_path)
    _narration(tmp_path, work)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -3.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    _with_fx(work)
    from common import read_csv
    src = read_csv(str(work / "shots.csv"))[0]["source"]
    graded = tmp_path / "调色" / os.path.basename(src)
    graded.parent.mkdir()
    shutil.copy(src, graded)
    _relocate(work, src, str(graded))
    _run(monkeypatch, "--work", str(work), "--name", "派生", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"))
    assert (drafts / "派生" / "draft_info.json").exists()


def test_inventory_duplicate_path_rejected(tmp_path, monkeypatch):
    """两段不同的素材被换成了同一个路径：拒绝，旧草稿还在。"""
    drafts, work, old = _setup(tmp_path)
    _narration(tmp_path, work)
    from common import read_csv
    inv = read_csv(str(work / "inventory.csv"))
    _relocate(work, inv[1]["path"], inv[0]["path"])
    with pytest.raises(SystemExit, match="inventory.csv 里有重复路径"):
        _run(monkeypatch, "--work", str(work), "--name", "旧草稿", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"), "--replace")
    assert (old / "keep.txt").exists()


def test_preflight_idx_not_position(tmp_path, monkeypatch):                     # Review Focus 4
    from common import read_csv, write_csv
    drafts, work, old = _setup(tmp_path)
    _narration(tmp_path, work)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -3.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    rows = read_csv(str(work / "shots.csv"))
    rows[1]["idx"] = "3"
    write_csv(str(work / "shots.csv"), rows, list(rows[0]))
    _with_fx(work, {"filters": [{"shot": 2, "start_us": 5000000, "type": "夏日风吟", "intensity": 60, "item": "V1", "vip": False}]})
    with pytest.raises(SystemExit, match="idx"):
        _run(monkeypatch, "--work", str(work), "--name", "旧草稿", "--drafts-dir", str(drafts),
             "--narration", str(work / "narration_track.json"), "--replace")
    assert (old / "keep.txt").exists()


def test_no_fx_no_effect_track(tmp_path, monkeypatch):
    drafts, work, _ = _setup(tmp_path)
    _narration(tmp_path, work)
    _fake_measure(monkeypatch, {"vo.m4a": (-16.0, -3.0), "a.mp4": (-30.0, -10.0), "b.mp4": (-30.0, -10.0)})
    _run(monkeypatch, "--work", str(work), "--name", "无效果", "--drafts-dir", str(drafts),
         "--narration", str(work / "narration_track.json"))
    d = json.load(open(drafts / "无效果" / "draft_info.json"))
    m = d["materials"]
    assert not _segs(d, "特效") and not any(t["type"] == "effect" for t in d["tracks"])
    assert m["transitions"] == [] and m["video_effects"] == [] and m["material_animations"] == []
    assert [e for e in m["effects"] if e.get("type") == "filter"] == []


def test_effect_segment_dangling_material_id(tmp_path, monkeypatch):
    from common import detect_versions, read_csv
    _, _, drafts, work, _ = _fx_build(tmp_path, monkeypatch)
    p = drafts / "旁白片" / "draft_info.json"
    d = json.loads(p.read_text())
    next(t for t in d["tracks"] if t["type"] == "effect")["segments"][0]["material_id"] = "nope"
    p.write_text(json.dumps(d, ensure_ascii=False))
    errs, _ = build.verify(str(drafts / "旁白片"), read_csv(str(work / "shots.csv")), detect_versions(str(drafts)), 0, 1)
    assert any("悬空" in e and "nope" in e for e in errs)


def test_build_reports_fx_summary(tmp_path, monkeypatch, capsys):
    _fx_build(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "✓ 效果逐个对上" in out and "转场 1 个、特效 1 个、滤镜 1 个、片头片尾动画 2 个" in out

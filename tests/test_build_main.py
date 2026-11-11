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


def _fake_measure(monkeypatch, levels):
    def m(path, start=None, end=None):
        i, tp = levels[os.path.basename(path)]
        return {"i": i, "tp": tp, "short": [(t / 10, i if t % 10 else i - 25) for t in range(0, 600)]}
    monkeypatch.setattr(loudness, "measure", m)


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
    assert len(vo) == 1 and abs(vo[0]["volume"] - 10 ** (6 / 20)) < 1e-6
    assert vo[0]["target_timerange"] == {"start": 700000, "duration": 4000000}
    video = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]
    assert abs(video[0]["volume"] - loudness.bed_gain(-30.0)) < 1e-6
    assert abs(video[1]["volume"] - loudness.voice_gain(-30.0, -10.0)[0]) < 1e-6
    texts = json.dumps(d["materials"].get("texts", []), ensure_ascii=False)
    assert "出发" in texts
    out = capsys.readouterr().out
    assert "✓" in out and "待真机验证" in out


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

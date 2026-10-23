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

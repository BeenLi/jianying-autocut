import json
import os

import pytest

from common import write_csv
from orient import build_orientation
from plan import load_clips

FIELDS = ["clip_id", "path", "t", "sharpness", "brightness", "score", "bad"]
INV = ["clip_id", "path", "name", "folder", "duration_s", "width", "height", "fps",
       "has_audio", "rotation", "shot_time", "size_mb", "speech_score"]
FRAMES = {"c001": [4.0, 12.0, 20.0], "c002": [3.217], "c003": [4.0, 12.0]}


def test_flip_rotates_whole_clip():
    assert build_orientation(FRAMES, flip=["c001"])["clips"]["c001"] == {"rotate": 180, "bad": []}


def test_unusable_marks_all_frames_bad():
    c = build_orientation(FRAMES, unusable=["c003"])["clips"]["c003"]
    assert c == {"rotate": 0, "bad": [4.0, 12.0], "unusable": True}


def test_bad_uses_exact_frame_time_from_rounded_label():
    # 联系表上显示 @3s，真实抽帧时间是 3.217：必须换回精确时间，plan.py 才对得上
    assert build_orientation(FRAMES, bad=["c002@3"])["clips"]["c002"]["bad"] == [3.217]


def test_flip_and_bad_on_same_clip_combine():
    c = build_orientation(FRAMES, flip=["c001"], bad=["c001@12"])["clips"]["c001"]
    assert c == {"rotate": 180, "bad": [12.0]}


def test_unknown_clip_is_an_error():
    with pytest.raises(ValueError, match="c999"):
        build_orientation(FRAMES, flip=["c999"])


def test_time_far_from_any_frame_is_an_error():
    with pytest.raises(ValueError, match="c001@99"):
        build_orientation(FRAMES, bad=["c001@99"])


def test_plan_sees_bad_frames_written_by_orient(tmp_path):
    w = str(tmp_path)
    write_csv(os.path.join(w, "inventory.csv"),
              [{"clip_id": "c002", "path": "/x/c002.mp4", "name": "c002.mp4", "folder": "x", "duration_s": 10,
                "width": 1, "height": 1, "fps": 30, "has_audio": "True", "rotation": 0,
                "shot_time": "2026-10-05T00:00:00", "size_mb": 1, "speech_score": 0}], INV)
    write_csv(os.path.join(w, "frames.csv"),
              [{"clip_id": "c002", "path": "/x/c002.mp4", "t": 3.217, "sharpness": 1, "brightness": 1,
                "score": 0.5, "bad": 0}], FIELDS)
    with open(os.path.join(w, "orientation.json"), "w", encoding="utf-8") as f:
        json.dump(build_orientation(FRAMES, bad=["c002@3"]), f)
    clips, _ = load_clips(w)
    assert clips["c002"].frames[0][2] == 1

import pytest

from common import load_json


def test_load_json_reports_file_and_position(tmp_path):
    p = tmp_path / "matches.json"
    p.write_text('{\n  "a": 1,\n  "b": \n}', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        load_json(str(p))
    msg = str(e.value)
    assert "matches.json" in msg and "第 4 行" in msg


def test_load_json_missing_file_default(tmp_path):
    assert load_json(str(tmp_path / "nope.json"), default={}) == {}
    with pytest.raises(SystemExit, match="不存在"):
        load_json(str(tmp_path / "nope.json"))


def test_load_json_wrong_top_level_type(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("[1, 2]")
    with pytest.raises(SystemExit, match="x.json"):
        load_json(str(p), kind=dict)

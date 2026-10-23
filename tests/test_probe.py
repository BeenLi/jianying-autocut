from common import classify_mimo_error
from probe import parse_silences



def test_parse_silences():
    err = "silence_start: 1.5\nsilence_end: 3.0 | silence_duration: 1.5\nsilence_start: 9.2\n"
    assert parse_silences(err, 10.0) == [(1.5, 3.0), (9.2, 10.0)]


def test_classify_mimo_errors():
    assert classify_mimo_error("Insufficient balance", 402) == "recharge"
    assert classify_mimo_error("账户余额不足", 400) == "recharge"
    assert classify_mimo_error("API 认证失败 (401)", 401) == "bad_key"
    assert classify_mimo_error("Too Many Requests", 429) == "rate_limit"
    assert classify_mimo_error("connection reset", None) == "other"


def test_classify_unsupported_model():
    assert classify_mimo_error('{"message": "Unsupported model mimo-v2.5"}', 400) == "bad_model"


def test_401_only_when_it_is_an_http_status():
    assert classify_mimo_error("场景 401: 描述完成；line 401 in vlm.py", None) == "other"
    assert classify_mimo_error("HTTP Error 401: Unauthorized", None) == "bad_key"


def test_assign_ids_keeps_old_and_appends_new():
    from probe import assign_ids
    rows = [{"path": "/a"}, {"path": "/new"}, {"path": "/b"}]          # 已按拍摄时间排好
    old = {"/a": "c001", "/b": "c002"}
    assign_ids(rows, old)
    assert [r["clip_id"] for r in rows] == ["c001", "c003", "c002"]


def test_assign_ids_fresh():
    from probe import assign_ids
    rows = [{"path": "/x"}, {"path": "/y"}]
    assign_ids(rows, {})
    assert [r["clip_id"] for r in rows] == ["c001", "c002"]

from frames import judge


def _rows(path, values, brightness=120):
    return [{"path": path, "sharpness": s, "brightness": brightness} for s in values]


def test_judge_relative_blur():
    rows = _rows("a", (100, 110, 120, 20)) + _rows("b", (2000, 2100, 2200))
    out = judge(rows)
    assert [r["bad"] for r in out] == [0, 0, 0, 1, 0, 0, 0]   # 低纹理段不误杀，突降被抓


def test_judge_exposure():
    assert judge(_rows("a", (500,), brightness=5))[0]["bad"] == 1

from common import US
from narrate import Opts, align_to_script, draft_plan, mark_retakes, timeline, validate


def us(s):
    return round(s * US)


def _line(iid, start, end, file="n1", **kw):
    return {"id": iid, "type": "line", "chapter": "ch1", "file": file, "start": start, "end": end,
            "text": kw.pop("text", iid), "visuals": kw.pop("visuals", []), **kw}


def _plan(*items, files=("n1", "n2")):
    return {"files": {f: f"/v/{f}.m4a" for f in files}, "chapters": [{"id": "ch1", "title": "出发"}],
            "items": list(items)}


def _tl(*items, silences=None, durs=None, **opts):
    durs = durs or {"n1": 60.0, "n2": 60.0}
    return timeline(_plan(*items), silences or {}, durs, Opts(**opts))


def _segs(tl):
    return [(a["src_us"], a["src_us"] + a["dur_us"], a["start_us"]) for a in tl["audio"]]


def _mark(tl, iid):
    return next(m for m in tl["marks"] if m["item"] == iid)


# ---------- 校验 ----------

def test_validate_reports_all_errors():
    plan = _plan(
        _line("L1", 0, 1, file="n9"),
        _line("L2", 3, 2),
        _line("L3", 50, 99),
        _line("L4", 0, 1, visuals=[{"clip_id": "c999"}]),
        _line("L5", 0, 1, visuals=[{"clip_id": "c001", "at": 500}]),
        {"id": "V1", "type": "live", "chapter": "ch1", "clip_id": "c001", "start": 90, "end": 120},
        dict(_line("L6", 0, 1), chapter="chX"),
        _line("L7", 0, 1, bgm="loud"),
        _line("L1", 2, 3),
    )
    errs, _ = validate(plan, {"c001": 100.0}, {"n1": 60.0, "n2": 60.0})
    assert len(errs) == 9, errs
    for iid in ("L1", "L2", "L3", "L4", "L5", "V1", "L6", "L7"):
        assert any(iid in e for e in errs), iid


def test_validate_missing_file_on_disk():
    errs, _ = validate(_plan(_line("L1", 0, 1, file="n2")), {}, {"n1": 60.0})
    assert len(errs) == 1 and "L1" in errs[0]


def test_validate_warns_bgm_up_on_line():
    errs, warns = validate(_plan(_line("L1", 0, 1, bgm="up")), {}, {"n1": 60.0})
    assert errs == [] and len(warns) == 1 and "L1" in warns[0]


# ---------- 重录与稿子对齐 ----------

def test_mark_retakes_keeps_last_take():
    lines = [_line("L1", 0, 2, text="凌晨四点我们出发"), _line("L2", 3, 5, text="凌晨四点，我们出发了"),
             _line("L3", 6, 7, text="山很高")]
    out = mark_retakes(lines)
    assert [bool(l.get("skip")) for l in out] == [True, False, False]
    assert "重录" in out[0]["skip_reason"]
    assert "skip" not in lines[0]          # 不改入参


def test_mark_retakes_restart_keyword():
    out = mark_retakes([_line("L1", 0, 2, text="不对不对，重来"), _line("L2", 3, 5, text="山很高")])
    assert out[0]["skip"] and out[0]["skip_reason"] == "口头重来" and not out[1].get("skip")


def test_mark_retakes_only_within_same_file():
    out = mark_retakes([_line("L1", 0, 2, text="凌晨四点我们出发"),
                        _line("L2", 0, 2, file="n2", text="凌晨四点我们出发")])
    assert not any(l.get("skip") for l in out)


def test_align_to_script_last_take_offscript_missing():
    script = [{"id": "A", "text": "凌晨四点我们从山脚出发"}, {"id": "B", "text": "山顶的风特别大"},
              {"id": "C", "text": "下山的时候天已经黑了"}]
    lines = [_line("L1", 0, 2, text="凌晨四点我们从山"), _line("L2", 3, 6, text="凌晨四点，我们从山脚出发。"),
             _line("L3", 7, 8, text="哎这个录上了吗"), _line("L4", 9, 11, text="山顶的风特别大啊")]
    out, missing = align_to_script(lines, script)
    assert out[0]["skip"] and out[0]["skip_reason"] == "重录"
    assert out[1]["script_id"] == "A" and not out[1].get("skip")
    assert out[2]["skip"] and out[2]["skip_reason"].startswith("稿外")
    assert out[3]["script_id"] == "B" and not out[3].get("skip")
    assert missing == ["C"]


def test_draft_plan_builds_line_items_in_file_order():
    speech = {"files": {"n1": "/v/a.m4a", "n2": "/v/b.m4a"}, "durations": {"n1": 9.0, "n2": 9.0},
              "lines": {"n2": [{"start": 0.5, "end": 2.0, "text": "第二个文件"}],
                        "n1": [{"start": 0.5, "end": 2.0, "text": "第一句"}, {"start": 3.0, "end": 4.0, "text": "第二句"}]},
              "silences": {}}
    plan = draft_plan(speech)
    assert [i["id"] for i in plan["items"]] == ["L01", "L02", "L03"]
    assert [i["text"] for i in plan["items"]] == ["第一句", "第二句", "第二个文件"]
    assert all(i["type"] == "line" and i["visuals"] == [] and i["chapter"] == "ch1" for i in plan["items"])
    assert plan["chapters"] == [{"id": "ch1", "title": "旁白"}] and plan["files"] == speech["files"]


# ---------- 时间线 ----------

def test_timeline_continuous_block_keeps_short_pause():
    tl = _tl(_line("A", 1.0, 3.0), _line("B", 3.4, 5.0))
    # 停顿 0.4 → ×0.6=0.24 → 夹到 0.3 → 剪掉 0.1，剪口在停顿中间两侧各留 0.15
    assert _segs(tl) == [(us(0.7), us(3.15), us(1.0)), (us(3.25), us(5.3), us(3.45))]
    assert _mark(tl, "A")["mouth_us"] == us(1.3) and _mark(tl, "B")["mouth_us"] == us(3.6)
    assert _mark(tl, "B")["close_us"] == us(5.2)
    assert tl["total_us"] == us(3.45 + 2.05 + 1.5)
    assert all(a["fade_in_us"] == us(0.015) and a["fade_out_us"] == us(0.015) for a in tl["audio"])


def test_timeline_pause_within_limits_stays_one_segment():
    tl = _tl(_line("A", 1.0, 3.0), _line("B", 3.3, 5.0))
    assert _segs(tl) == [(us(0.7), us(5.3), us(1.0))]


def test_timeline_skip_inside_block_cut_out():
    tl = _tl(_line("A", 1.0, 3.0), _line("R", 3.5, 5.0, skip=True), _line("B", 5.6, 7.0))
    (a0, a1, _), (b0, b1, _) = _segs(tl)
    assert a1 < us(3.5) and b0 > us(5.0)
    assert (a1, b0) == (us(3.15), us(5.45))


def test_timeline_out_of_order_breaks_block():
    tl = _tl(_line("A", 20.0, 22.0), _line("B", 10.0, 12.0))
    assert _segs(tl) == [(us(19.7), us(22.3), us(1.0)), (us(9.7), us(12.3), us(1.0 + 2.6 + 1.2))]
    assert all(a["dur_us"] > 0 for a in tl["audio"])


def test_timeline_edge_expand_to_silence_never_shrink():
    first = lambda sil: _segs(_tl(_line("A", 1.0, 3.0), silences={"n1": sil}))[0]
    assert first([[0.0, 0.85]])[0] == us(0.85)
    assert first([[0.0, 0.5]])[0] == us(0.7)
    assert first([[0.9, 1.2]])[0] <= us(1.0)
    assert first([[3.1, 4.0]])[1] == us(3.1)
    assert first([[2.8, 4.0]])[1] >= us(3.0)


def test_timeline_end_clamped_to_file_length():
    tl = _tl(_line("A", 1.0, 3.0), durs={"n1": 3.1})
    assert _segs(tl)[0][1] == us(3.1)


def test_timeline_live_and_file_gap_and_head_tail():
    live = {"id": "V1", "type": "live", "chapter": "ch1", "clip_id": "c007", "start": 30.0, "end": 35.0}
    tl = _tl(_line("L1", 1.0, 3.0), live, _line("L2", 2.0, 4.0, file="n2"))
    assert _segs(tl) == [(us(0.7), us(3.3), us(1.0)), (us(1.7), us(4.3), us(8.6))]
    v = _mark(tl, "V1")
    assert v["live"] and (v["start_us"], v["end_us"]) == (us(3.6), us(8.6))
    assert _mark(tl, "L2")["mouth_us"] == us(8.9)
    assert tl["total_us"] == us(11.2 + 1.5)


def test_timeline_file_gap_between_files():
    tl = _tl(_line("L1", 1.0, 3.0), _line("L2", 2.0, 4.0, file="n2"))
    assert _segs(tl)[1][2] == us(3.6 + 1.2)


def test_timeline_pause_after_override():
    tl = _tl(_line("A", 1.0, 3.0, pause_after=0.5), _line("B", 4.0, 5.0))
    assert [(s0, s1) for s0, s1, _ in _segs(tl)] == [(us(0.7), us(3.25)), (us(3.75), us(5.3))]


def test_timeline_skipped_items_have_no_marks():
    tl = _tl(_line("A", 1.0, 3.0), _line("R", 10.0, 12.0, skip=True))
    assert [m["item"] for m in tl["marks"]] == ["A"]


def test_mark_retakes_restart_word_inside_normal_sentence_kept():
    out = mark_retakes([_line("L1", 0, 2, text="我们走着走着发现方向好像不对劲了")])
    assert not out[0].get("skip")

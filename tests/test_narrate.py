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


# ---------- 铺画面（Task 3） ----------

import json
import os

import pytest

from common import write_csv
from narrate import layout, main, slots, split_sub
from plan import Clip


def _clip(cid, dur, bad=False, score=0.8):
    row = {"clip_id": cid, "path": f"/x/{cid}.mp4", "name": f"{cid}.mp4", "shot_time": "2026-10-05T00:00:00",
           "duration_s": dur}
    frames = [(t * US, score, int(bad)) for t in range(int(dur))]
    return Clip(row, frames, [])


def _clips(*specs):
    return {s[0]: _clip(*s) for s in specs}


def _vis(*cids):
    return [{"clip_id": c} for c in cids]


def _live(iid, cid, start, end, **kw):
    return {"id": iid, "type": "live", "chapter": "ch1", "clip_id": cid, "start": start, "end": end, **kw}


def _lay(items, clips, speech=None, **opts):
    return layout(_plan(*items), clips, speech or {}, {}, {"n1": 60.0, "n2": 60.0}, Opts(**opts))


def _rows_ok(rows, total):
    t = 0
    for r in rows:
        assert r["start_us"] == t and r["dur_us"] > 0
        t += r["dur_us"]
    assert t == total


def test_slots_cover_timeline_without_gaps():
    items = [_line("L1", 1.0, 3.0), _live("V1", "c7", 30.0, 35.0), _line("L2", 2.0, 4.0, file="n2")]
    plan = _plan(*items)
    tl = timeline(plan, {}, {"n1": 60.0, "n2": 60.0}, Opts())
    sl = slots(tl, plan, Opts())
    assert [(s["item"], s["start_us"], s["end_us"]) for s in sl] == \
        [("L1", 0, us(3.6)), ("V1", us(3.6), us(8.6)), ("L2", us(8.6), us(12.7))]


def test_slot_jcut_start_is_mouth_minus_lead():
    plan = _plan(_line("A", 1.0, 3.0), _line("B", 5.0, 7.0))
    tl = timeline(plan, {}, {"n1": 60.0}, Opts())
    sl = slots(tl, plan, Opts())
    assert sl[1]["start_us"] == _mark(tl, "B")["mouth_us"] - us(0.3) == us(4.2)


def test_slot_after_live_clamped_to_live_end():          # Review Focus 3
    plan = _plan(_line("L1", 1.0, 3.0), _live("V1", "c7", 30.0, 35.0), _line("L2", 2.0, 4.0, file="n2"))
    sl = slots(timeline(plan, {}, {"n1": 60.0, "n2": 60.0}, Opts(lead=0.5)), plan, Opts(lead=0.5))
    assert sl[2]["start_us"] == sl[1]["end_us"] == us(8.6)


def test_live_shot_exact_range():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _live("V1", "c7", 30.0, 35.0),
             _line("L2", 2.0, 4.0, file="n2", visuals=_vis("c2"))]
    rows, track, _ = _lay(items, _clips(("c1", 40), ("c2", 40), ("c7", 60)))
    v = rows[1]
    assert (v["kind"], v["in_us"], v["dur_us"]) == ("live", us(30.0), us(5.0))
    assert track["live"] == [{"start_us": us(3.6), "dur_us": us(5.0), "clip_id": "c7", "src_us": us(30.0)}]
    _rows_ok(rows, track["total_us"])


def test_line_visual_respects_at_and_marks_used():
    clips = _clips(("c1", 40))
    rows, _, _ = _lay([_line("L1", 1.0, 3.0, visuals=[{"clip_id": "c1", "at": 20.0}])], clips)
    r = rows[0]
    assert r["in_us"] <= us(20.0) < r["in_us"] + r["dur_us"]
    assert (r["in_us"], r["in_us"] + r["dur_us"]) in clips["c1"].used


def test_live_reserved_before_lines():
    # L1 和用同一素材的原声段之间隔着一句，才允许 L1 用 c1（紧挨着会被换掉，见 B2）
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L0", 6.0, 8.0, visuals=_vis("c2")),
             _live("V1", "c1", 18.0, 23.0), _line("L2", 2.0, 4.0, file="n2", visuals=_vis("c2"))]
    rows, _, _ = _lay(items, _clips(("c1", 40), ("c2", 40)))
    assert rows[0]["source"] == "/x/c1.mp4"
    a, d = rows[0]["in_us"], rows[0]["dur_us"]
    assert a + d <= us(18.0) or a >= us(23.0)


def test_fallback_order_and_report():
    items = [_line("L0", 1.0, 3.0, visuals=_vis("c3")), _line("L1", 6.0, 8.0, visuals=_vis("c1")),
             _line("L2", 11.0, 13.0, visuals=_vis("c2"))]
    rows, _, rep = _lay(items, _clips(("c1", 40, True), ("c2", 40), ("c3", 40)))
    assert rows[1]["source"] == "/x/c2.mp4"
    assert ("L1", "c2") in rep["fallback"]


def test_same_clip_never_adjacent():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c1")),
             _line("L3", 11.0, 13.0, visuals=_vis("c2"))]
    rows, _, _ = _lay(items, _clips(("c1", 60), ("c2", 60)))
    srcs = [r["source"] for r in rows]
    assert all(a != b for a, b in zip(srcs, srcs[1:]))


def test_short_slot_merged_into_previous():
    items = [_line("A", 1.0, 3.0, visuals=_vis("c1")), _line("B", 3.4, 4.0, visuals=_vis("c2")),
             _line("C", 6.0, 9.0, visuals=_vis("c3"))]
    rows, track, _ = _lay(items, _clips(("c1", 60), ("c2", 60), ("c3", 60)))
    assert [r["source"] for r in rows] == ["/x/c1.mp4", "/x/c3.mp4"]
    _rows_ok(rows, track["total_us"])


def test_kind_is_narr_after_pick_one():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c1")),
             _line("L3", 11.0, 13.0, visuals=_vis("c2", "c3"))]
    rows, _, rep = _lay(items, _clips(("c1", 40, True), ("c2", 60), ("c3", 60)))
    assert rows[0]["kind"] == "narr" and rows[0]["source"] in ("/x/c2.mp4", "/x/c3.mp4")
    assert any(f[0] == "L1" for f in rep["fallback"])
    assert all(r["kind"] in ("narr", "live") for r in rows)


def test_talking_window_deprioritized():
    speech = {"c1": [{"start": 0.0, "end": 20.0, "text": "你好"}]}
    clips = _clips(("c1", 40))
    rows, _, _ = _lay([_line("L1", 1.0, 3.0, visuals=_vis("c1"))], clips, speech)
    assert rows[0]["in_us"] >= us(20.0)
    assert all(s == 0.8 for _, s, _ in clips["c1"].frames)    # 降权是临时的


def test_chapter_without_clips_errors():
    with pytest.raises(ValueError, match="ch1"):
        _lay([_line("L1", 1.0, 3.0, visuals=_vis("c1"))], _clips(("c1", 40, True)))


def test_empty_visuals_continue_previous_shot():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0)]
    rows, track, rep = _lay(items, _clips(("c1", 60)))
    assert len(rows) == 1 and rep["unpaired"] == ["L2"]
    _rows_ok(rows, track["total_us"])


def test_track_subs_split_long_line():
    text = "凌晨四点我们从山脚出发，天还没有亮，路上只有头灯和星星。"
    parts = split_sub(text, 0, us(10.0))
    assert len(parts) >= 2 and all(len(t) <= 16 for _, _, t in parts)
    assert sum(d for _, d, _ in parts) == us(10.0) and parts[0][0] == 0
    assert all(parts[k][0] + parts[k][1] == parts[k + 1][0] for k in range(len(parts) - 1))
    assert "".join(t for _, _, t in parts) == text


def test_track_speech_and_bgm_marks():
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _live("V1", "c2", 30.0, 35.0, bgm="drop"),
             _line("L2", 2.0, 4.0, file="n2", visuals=_vis("c3"))]
    speech = {"c2": [{"start": 31.0, "end": 33.0, "text": "哇"}]}
    _, track, _ = _lay(items, _clips(("c1", 60), ("c2", 60), ("c3", 60)), speech)
    assert track["bgm"] == [{"start_us": us(3.6), "dur_us": us(5.0), "mode": "drop"}]
    assert [us(1.3), us(2.0)] in track["speech"] and [us(4.6), us(2.0)] in track["speech"]
    assert track["subs"][0] == {"start_us": us(1.3), "dur_us": us(2.0), "text": "L1"}


# ---------- CLI ----------

INV = ["clip_id", "path", "name", "folder", "duration_s", "width", "height", "fps", "has_audio", "rotation",
       "shot_time", "size_mb", "speech_score"]


def _work(tmp_path, plan=True):
    rows = [{"clip_id": c, "path": f"/x/{c}.mp4", "name": f"{c}.mp4", "folder": "x", "duration_s": 60,
             "width": 1920, "height": 1080, "fps": 30, "has_audio": "True", "rotation": 0,
             "shot_time": f"2026-10-05T0{i}:00:00", "size_mb": 1, "speech_score": 0} for i, c in enumerate(("c1", "c2"))]
    write_csv(str(tmp_path / "inventory.csv"), rows, INV)
    vo = tmp_path / "vo.m4a"
    vo.write_bytes(b"")
    speech = {"files": {"n1": str(vo)}, "durations": {"n1": 30.0},
              "lines": {"n1": [{"start": 1.0, "end": 3.0, "text": "出发"}, {"start": 6.0, "end": 8.0, "text": "到了"}]},
              "silences": {"n1": []}}
    (tmp_path / "narration_speech.json").write_text(json.dumps(speech, ensure_ascii=False))
    if plan:
        p = {"files": {"n1": str(vo)}, "chapters": [{"id": "ch1", "title": "出发"}],
             "items": [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0, visuals=_vis("c2"))]}
        (tmp_path / "narration_plan.json").write_text(json.dumps(p, ensure_ascii=False))
    return str(tmp_path)


def test_main_dry_run_writes_nothing(tmp_path, capsys):
    w = _work(tmp_path)
    assert main(["--work", w, "--dry-run"]) == 0
    assert not os.path.exists(os.path.join(w, "shots.csv")) and not os.path.exists(os.path.join(w, "narration_track.json"))
    assert "L1" in capsys.readouterr().out


def test_main_writes_shots_and_track(tmp_path):
    w = _work(tmp_path)
    (tmp_path / "shots.prebeat.csv").write_text("x")
    assert main(["--work", w]) == 0
    assert os.path.exists(os.path.join(w, "shots.csv")) and not os.path.exists(os.path.join(w, "shots.prebeat.csv"))
    track = json.loads((tmp_path / "narration_track.json").read_text())
    assert len(track["audio"]) == 2 and track["audio"][0]["file"].endswith("vo.m4a")


def test_main_refuses_on_validation_errors(tmp_path, capsys):
    w = _work(tmp_path)
    p = json.loads((tmp_path / "narration_plan.json").read_text())
    p["items"][0]["visuals"] = _vis("c999")
    (tmp_path / "narration_plan.json").write_text(json.dumps(p))
    assert main(["--work", w]) == 1 and "c999" in capsys.readouterr().err


def test_main_draft_refuses_overwrite(tmp_path):
    w = _work(tmp_path)
    assert main(["--work", w, "--draft"]) == 1
    assert main(["--work", w, "--draft", "--force"]) == 0
    p = json.loads((tmp_path / "narration_plan.json").read_text())
    assert [i["text"] for i in p["items"]] == ["出发", "到了"]


# ---------- 终审修复 ----------

def test_timeline_skip_out_of_order_ignored():                 # Critical 1
    tl = _tl(_line("A", 20.0, 22.0), _line("R", 10.0, 12.0, skip=True), _line("B", 24.0, 26.0))
    assert all(a["dur_us"] > 0 for a in tl["audio"])
    assert _segs(tl)[0][1] == us(22.6)                        # 停顿 2.0 → 1.2，剪口在中间


def test_timeline_small_overlap_stays_in_block():              # Important 3
    tl = _tl(_line("A", 1.0, 5.0), _line("B", 4.95, 8.0))
    assert _segs(tl) == [(us(0.7), us(8.3), us(1.0))]


def test_empty_visuals_after_live_does_not_extend_live():      # Important 2
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _live("V1", "c2", 30.0, 34.0),
             _line("L2", 2.0, 4.0, file="n2")]
    rows, track, rep = _lay(items, _clips(("c1", 60), ("c2", 60)))
    live = [r for r in rows if r["kind"] == "live"]
    assert len(live) == 1 and live[0]["dur_us"] == us(4.0)
    assert rows[-1]["kind"] == "narr" and "L2" in rep["unpaired"]
    _rows_ok(rows, track["total_us"])


def test_no_crumb_shots_shorter_than_min_shot():               # Important 6
    rows, track, _ = _lay([_line("L1", 1.0, 5.6, visuals=_vis("c1", "c2"))], _clips(("c1", 3), ("c2", 60)))
    assert all(r["dur_us"] >= 2 * US for r in rows), [(r["source"], r["dur_s"]) for r in rows]
    _rows_ok(rows, track["total_us"])


def test_align_keeps_both_halves_of_split_sentence():          # Important 4
    script = [{"id": "A", "text": "凌晨四点我们从山脚出发，天还没有亮，只有头灯照着脚下的石阶"}]
    lines = [_line("L1", 0, 4, text="凌晨四点我们从山脚出发，天还没有亮，"), _line("L2", 4.2, 7, text="只有头灯照着脚下的石阶。")]
    out, missing = align_to_script(lines, script)
    assert not any(l.get("skip") for l in out) and [l["script_id"] for l in out] == ["A", "A"] and missing == []


def test_align_split_sentence_retaken_drops_whole_first_take():
    script = [{"id": "A", "text": "凌晨四点我们从山脚出发，天还没有亮，只有头灯照着脚下的石阶"}]
    lines = [_line("L1", 0, 4, text="凌晨四点我们从山脚出发，天还没有亮，"), _line("L2", 4.2, 7, text="只有头灯照着脚下的石阶。"),
             _line("L3", 8, 14, text="凌晨四点我们从山脚出发，天还没有亮，只有头灯照着脚下的石阶。")]
    out, _ = align_to_script(lines, script)
    assert [bool(l.get("skip")) for l in out] == [True, True, False]


# ---------- 小问题修复（第二轮） ----------

def test_restart_also_skips_abandoned_half_sentence():          # B1
    out = mark_retakes([_line("L1", 0, 2, text="凌晨四点我们从"), _line("L2", 2.2, 2.6, text="不对"),
                        _line("L3", 3, 6, text="凌晨四点我们从山脚出发")])
    assert [bool(l.get("skip")) for l in out] == [True, True, False]
    assert "一半" in out[0]["skip_reason"]


def test_restart_keeps_complete_previous_sentence():
    for prev in ("山很高。", "凌晨四点出发了"):
        out = mark_retakes([_line("L1", 0, 2, text=prev), _line("L2", 2.2, 2.6, text="不对"),
                            _line("L3", 3, 6, text="山顶的风特别大，是雾很大")])
        assert not out[0].get("skip"), prev


def test_restart_prefix_merged_into_retake_is_trimmed_not_dropped():   # C1
    words = [{"start": 0.0, "end": 0.5, "word": "重来"}, {"start": 0.8, "end": 1.2, "word": "凌晨"},
             {"start": 1.2, "end": 1.6, "word": "四点"}, {"start": 1.6, "end": 3.0, "word": "我们从山脚出发"}]
    out = mark_retakes([_line("L1", 0.0, 3.0, text="重来，凌晨四点我们从山脚出发", words=words)])
    assert not out[0].get("skip") and out[0]["start"] == 0.8 and out[0]["text"] == "凌晨四点我们从山脚出发"
    out = mark_retakes([_line("L1", 0.0, 3.0, text="重来，凌晨四点我们从山脚出发")])   # 没有逐字时间
    assert not out[0].get("skip") and "重来" in out[0].get("note", "")


def test_draft_plan_drops_word_timings():
    speech = {"files": {"n1": "/v/a.m4a"}, "durations": {"n1": 9.0}, "silences": {},
              "lines": {"n1": [{"start": 0.5, "end": 2.0, "text": "第一句", "words": [{"start": 0.5, "end": 2.0, "word": "第一句"}]}]}}
    assert "words" not in draft_plan(speech)["items"][0]


def test_validate_survives_bad_structure_and_requires_text():  # B3 / C2
    plan = _plan(dict(_line("L1", 0, 1), text=""), _line("L2", "abc", 1), {"type": "line"},
                 dict(_line("L3", 0, 1, skip=True), text=""))
    plan["chapters"].append({"title": "无 id"})
    errs, _ = validate(plan, {}, {"n1": 60.0})
    assert any("L1" in e and "text" in e for e in errs)
    assert any("L2" in e and "start" in e for e in errs)
    assert any("缺 id" in e for e in errs)
    assert not any("L3" in e for e in errs)                  # 跳过的句子不要求 text
    errs, _ = validate({"files": {}, "chapters": [], "items": "x"}, {}, {})
    assert errs and "items" in errs[0]


def test_line_before_live_avoids_live_clip():                  # B2
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _live("V1", "c1", 30.0, 34.0),
             _line("L2", 2.0, 4.0, file="n2", visuals=_vis("c2"))]
    rows, track, _ = _lay(items, _clips(("c1", 60), ("c2", 60)))
    srcs = [r["source"] for r in rows]
    assert all(a != b for a, b in zip(srcs, srcs[1:])), srcs
    _rows_ok(rows, track["total_us"])


def test_live_too_short_for_head_suggests_value():             # B4
    with pytest.raises(ValueError, match="--head"):
        _lay([_live("V1", "c1", 0.5, 5.0), _line("L1", 1.0, 3.0, visuals=_vis("c2"))], _clips(("c1", 40), ("c2", 40)))
    with pytest.raises(ValueError, match="--tail"):
        _lay([_line("L1", 1.0, 3.0, visuals=_vis("c2")), _live("V1", "c1", 30.0, 39.5)], _clips(("c1", 40), ("c2", 40)))


def test_bgm_up_on_live_with_speech_ignored():                 # B5
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _live("V1", "c2", 30.0, 35.0, bgm="up"),
             _line("L2", 2.0, 4.0, file="n2", visuals=_vis("c3"))]
    speech = {"c2": [{"start": 31.0, "end": 33.0, "text": "哇"}]}
    _, track, rep = _lay(items, _clips(("c1", 60), ("c2", 60), ("c3", 60)), speech)
    assert track["bgm"] == [] and any("V1" in w for w in rep["warns"])
    _, track, _ = _lay(items, _clips(("c1", 60), ("c2", 60), ("c3", 60)), {})
    assert track["bgm"] == [{"start_us": us(3.6), "dur_us": us(5.0), "mode": "up"}]


def test_dry_run_marks_continued_sentence(capsys):              # B9
    from narrate import _print_report
    items = [_line("L1", 1.0, 3.0, visuals=_vis("c1")), _line("L2", 6.0, 8.0)]
    plan = _plan(*items)
    rows, track, rep = layout(plan, _clips(("c1", 60)), {}, {}, {"n1": 60.0, "n2": 60.0}, Opts())
    _print_report(plan, rows, track, rep, {})
    out = capsys.readouterr().out.splitlines()
    k = next(i for i, l in enumerate(out) if " L2 " in l)
    assert "延续上一镜头" in out[k + 1]


def test_main_reports_broken_plan_json(tmp_path):              # A4
    w = _work(tmp_path)
    (tmp_path / "narration_plan.json").write_text("{\n oops\n}")
    with pytest.raises(SystemExit) as e:
        main(["--work", w])
    assert "narration_plan.json" in str(e.value) and "第 2 行" in str(e.value)


# ---------- 端到端发现：画面素材比这句旁白短 ----------

def test_line_longer_than_each_visual_is_covered_by_several():
    # 8s 的句子加片头片尾约 10.6s，均分成两块各 5.3s；c1 只有 5s 可用、c2 有 7s（整槽约 11.1s）：
    # 应该先用满 c1、零头并给下一块的 c2，而不是把 c2 挪到第一块、第二块没得放而报"没有可用的素材"
    clips = _clips(("c1", 6), ("c2", 8))
    rows, track, report = _lay([_line("L1", 1.0, 9.0, visuals=_vis("c1", "c2"))], clips)
    _rows_ok(rows, track["total_us"])
    assert {r["name"] for r in rows} == {"c1.mp4", "c2.mp4"}
    dur = {"c1.mp4": 6.0, "c2.mp4": 8.0}
    for r in rows:
        assert r["in_us"] >= us(0.5) and r["in_us"] + r["dur_us"] <= us(dur[r["name"]] - 0.5)   # 不越过素材首尾 0.5s
    assert all(a["name"] != b["name"] for a, b in zip(rows, rows[1:]))           # 同一素材不相邻


def test_short_single_visual_is_supplemented_from_neighbour():
    # A 只配了一个 6s 的素材，不够铺满：先用你指定的 c1，剩下的从相邻句的画面补，并报告回退
    # （旧行为：整个跳过 c1，直接换成别的素材）
    clips = _clips(("c1", 6), ("c2", 60), ("c3", 60))
    items = [_line("Z", 1.0, 3.0, visuals=_vis("c3")), _line("A", 4.0, 12.0, visuals=_vis("c1")),
             _line("B", 13.0, 15.0, visuals=_vis("c2"))]
    rows, track, report = _lay(items, clips)
    _rows_ok(rows, track["total_us"])
    a_shots = next(i for i in report["items"] if i["item"] == "A")["shots"]
    assert a_shots[0][0] == "c1" and len(a_shots) >= 2
    assert any(f[0] == "A" and f[1] != "c1" for f in report["fallback"])


def test_partial_fill_uses_off_grid_free_segment():
    # 素材前面被占到 3.85s（加 1s 间隔，空闲段从 4.85s 起，不在 0.5s 网格上）：放得下多少就放多少，
    # 应该能把剩下的整段空闲用上，而不是因为网格对不上而放弃
    from narrate import _place_any
    clips = _clips(("c1", 10.8))
    clips["c1"].used.append((us(0.5), us(3.85)))
    shot = _place_any([{"clip_id": "c1", "at": 2.0}], clips, set(), us(8.0), {}, True)
    assert shot is not None and shot["in_us"] == us(4.85) and shot["dur_us"] == us(10.3) - us(4.85)


def test_last_piece_leaves_no_sliver_and_borrowed_visual_ignores_its_at():
    # A 的槽比 c1 的可用长度只多一点：不能用满 c1 后剩一个不到 2s、放不下也并不进去的零头，
    # 要给借来的画面留够 2s；借来的 c3 带着 Z 的 at=2.0（Z 自己已经用掉那一段），借用时不受它约束
    clips = _clips(("c1", 9), ("c2", 30), ("c3", 30))
    items = [_line("Z", 1.0, 3.0, visuals=[{"clip_id": "c3", "at": 2.0}]),
             _line("A", 4.0, 12.5, visuals=_vis("c1")),
             _line("B", 13.5, 15.5, visuals=_vis("c2"))]
    rows, track, report = _lay(items, clips)
    _rows_ok(rows, track["total_us"])
    assert all(r["dur_us"] >= us(2.0) for r in rows)
    a_shots = next(i for i in report["items"] if i["item"] == "A")["shots"]
    assert [s[0] for s in a_shots] == ["c1", "c3"]


# ---------- 端到端发现：有稿子时的初稿（问题 7–10） ----------

def _words(text, t0, gaps=None, step=0.2):
    """逐字时间：每个字 step 秒；gaps={字下标: 额外停顿秒}（加在这个字之前）。"""
    out, t = [], t0
    for k, ch in enumerate(text):
        t += (gaps or {}).get(k, 0)
        out.append({"start": round(t, 3), "end": round(t + step, 3), "word": ch})
        t += step
    return out


def test_draft_with_script_splits_fluent_file_and_uses_script_ids_text_chapters():
    heard = "这是我到枸杞岛的第一个半晚可就在几个小时前我还以为这趟旅行要泡汤了"   # 一整段，同音错字「半晚」
    w = _words(heard, 0.5, gaps={13: 0.6})                                      # 两句之间停 0.6s
    speech = {"files": {"n1": "/v/a.m4a"}, "durations": {"n1": 20.0}, "silences": {},
              "lines": {"n1": [{"start": w[0]["start"], "end": w[-1]["end"], "text": heard, "words": w}]}}
    script = [{"id": "L02", "text": "这是我到枸杞岛的第一个傍晚。", "chapter": "ch1", "chapter_title": "想多住几天"},
              {"id": "L03", "text": "可就在几个小时前，我还以为这趟旅行要泡汤了。", "chapter": "ch1"}]
    plan = draft_plan(speech, script)
    items = plan["items"]
    assert [i["id"] for i in items] == ["L02", "L03"]                                   # 问题 9：用稿子的 id
    assert [i["text"] for i in items] == [s["text"] for s in script]                   # 问题 8：用稿子的字
    assert all(i["chapter"] == "ch1" for i in items) and plan["chapters"] == [{"id": "ch1", "title": "想多住几天"}]
    assert items[0]["end"] == w[12]["end"] and items[1]["start"] == w[13]["start"]     # 问题 7：切在停顿上


def test_draft_with_script_offscript_keeps_previous_chapter_and_unique_id():
    speech = {"files": {"n1": "/v/a.m4a"}, "durations": {"n1": 20.0}, "silences": {},
              "lines": {"n1": [{"start": 0.5, "end": 2.0, "text": "山顶的风特别大"},
                               {"start": 3.0, "end": 4.0, "text": "哎这个录上了吗"}]}}
    script = [{"id": "B", "text": "山顶的风特别大。", "chapter": "c2"}]
    items = draft_plan(speech, script)["items"]
    assert items[0]["id"] == "B" and items[1]["chapter"] == "c2" and items[1]["skip"]
    assert items[1]["id"] not in {"B"} and len({i["id"] for i in items}) == 2

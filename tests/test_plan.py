import json
import os

from common import US, write_csv
from plan import allocate_quota, plan, snap_to_silence

INV_FIELDS = ["clip_id", "path", "name", "folder", "duration_s", "width", "height", "fps",
              "has_audio", "rotation", "shot_time", "size_mb", "speech_score"]


def _work(tmp_path, clips, chapters, silences=None):
    rows = [{"clip_id": cid, "path": f"/x/{cid}.mp4", "name": f"{cid}.mp4", "folder": "x",
             "duration_s": dur, "width": 3840, "height": 2160, "fps": 29.97, "has_audio": "True",
             "rotation": 0, "shot_time": f"2026-10-05T0{i}:00:00", "size_mb": 1, "speech_score": sp}
            for i, (cid, dur, sp) in enumerate(clips)]
    write_csv(os.path.join(tmp_path, "inventory.csv"), rows, INV_FIELDS)
    with open(os.path.join(tmp_path, "story_plan.json"), "w") as f:
        json.dump({"director_intent": "", "chapters": chapters}, f)
    if silences is not None:
        with open(os.path.join(tmp_path, "silences.json"), "w") as f:
            json.dump(silences, f)
    return str(tmp_path)


def _ch(cid, clip_ids, function="setup", pins=()):
    return {"id": cid, "title": cid, "function": function, "clip_ids": list(clip_ids),
            "pool": "own", "pins": list(pins)}


def test_quota_share_exact():
    chs = [{"good_us": 600 * US, "share": 0.5}, {"good_us": 300 * US}, {"good_us": 300 * US}]
    q = allocate_quota(chs, 600 * US)
    assert sum(q) == 600 * US and q[0] == 300 * US


def test_quota_without_share_still_exact():
    chs = [{"good_us": 11 * US}, {"good_us": 500 * US}, {"good_us": 90 * US}]
    q = allocate_quota(chs, 200 * US)
    assert sum(q) == 200 * US and q[0] == 11 * US and all(a <= c["good_us"] for a, c in zip(q, chs))


def test_pins_included(tmp_path):
    w = _work(tmp_path, [("c001", 60, 0), ("c002", 60, 0)],
              [_ch("a", ["c001", "c002"], pins=[{"clip_id": "c002", "at": 30.0}])])
    rows, _, short = plan(w, 40 * US, seed=1)
    assert short == 0
    assert any(r["name"] == "c002.mp4" and r["in_us"] <= 30 * US < r["in_us"] + r["dur_us"] for r in rows)


def test_hook_first_and_total_exact(tmp_path):
    w = _work(tmp_path, [("c001", 60, 0), ("c002", 60, 0)],
              [_ch("a", ["c001"]), _ch("b", ["c002"], function="hook")])
    rows, _, short = plan(w, 30 * US, seed=1)
    assert rows[0]["chapter_function"] == "hook"
    assert sum(r["dur_us"] for r in rows) == 30 * US and short == 0
    t = 0
    for r in rows:
        assert r["start_us"] == t
        t += r["dur_us"]


def test_snap_to_silence():
    assert snap_to_silence(10 * US, 5 * US, [(int(9.2 * US), int(9.8 * US))], 60 * US) == int(9.5 * US)
    assert snap_to_silence(10 * US, 5 * US, [(30 * US, 31 * US)], 60 * US) == 10 * US   # 太远不动


def test_unlisted_clips_unused(tmp_path):
    w = _work(tmp_path, [("c001", 60, 0), ("c002", 60, 0)], [_ch("a", ["c001"])])
    rows, _, _ = plan(w, 20 * US, seed=1)
    assert {r["name"] for r in rows} == {"c001.mp4"}


def _frames(tmp_path, rows):
    write_csv(os.path.join(tmp_path, "frames.csv"),
              [{"clip_id": c, "path": f"/x/{c}.mp4", "t": t, "sharpness": 100, "brightness": 120,
                "score": 0.5, "bad": b} for c, t, b in rows],
              ["clip_id", "path", "t", "sharpness", "brightness", "score", "bad"])


def test_blurry_longest_clip_does_not_empty_chapter(tmp_path):
    clips = [(f"c00{i}", 8, 0) for i in range(1, 7)] + [("c007", 10, 0)]
    w = _work(tmp_path, clips, [_ch("a", [c for c, _, _ in clips])])
    _frames(tmp_path, [("c007", 5.0, 1)] + [(f"c00{i}", 4.0, 0) for i in range(1, 7)])
    rows, _, short = plan(w, 30 * US, seed=1)
    assert short == 0 and sum(r["dur_us"] for r in rows) == 30 * US


def test_pin_dropped_for_quota_warns(tmp_path, capsys):
    w = _work(tmp_path, [("c001", 60, 0), ("c002", 60, 0)],
              [dict(_ch("h", ["c001"], function="hook", pins=[{"clip_id": "c001", "at": 10.0},
                                                               {"clip_id": "c001", "at": 40.0}]), share=0.1),
               _ch("b", ["c002"])])
    plan(w, 60 * US, seed=1)
    assert "pin" in capsys.readouterr().out


def test_pool_all_only_uses_story_clips(tmp_path):
    w = _work(tmp_path, [("c003", 60, 0), ("c001", 60, 0), ("c002", 60, 0)],      # c003 排最前、最容易被挑中
              [dict(_ch("h", [], function="hook"), pool="all"), _ch("a", ["c001", "c002"])])   # c003 被剔除
    rows, _, _ = plan(w, 40 * US, seed=1)
    assert "c003.mp4" not in {r["name"] for r in rows}


def test_hook_default_quota_is_short():
    chs = [{"good_us": 3000 * US, "function": "hook"}, {"good_us": 200 * US}, {"good_us": 200 * US}]
    q = allocate_quota(chs, 300 * US)
    assert q[0] <= 20 * US and sum(q) == 300 * US


def test_pins_win_over_earlier_pool_all_chapter(tmp_path):
    w = _work(tmp_path, [("c001", 30, 0)],
              [dict(_ch("h", [], function="hook"), pool="all"),
               _ch("a", ["c001"], function="payoff", pins=[{"clip_id": "c001", "at": 15.0}])])
    rows, _, _ = plan(w, 20 * US, seed=1)
    assert any(r["chapter_title"] == "a" and r["in_us"] <= 15 * US < r["in_us"] + r["dur_us"] for r in rows)


def test_spill_prefers_non_hook_chapters():
    from plan import spill_order

    class C:
        def __init__(self, free):
            self.f = free

        def longest_free(self):
            return self.f
    chs = [{"function": "hook", "pool": {"x": C(900)}}, {"function": "setup", "pool": {"y": C(10)}},
           {"function": "payoff", "pool": {"z": C(50)}}]
    assert spill_order(chs) == [2, 1, 0]


def test_snaps_even_without_speech_score(tmp_path):
    # 人声分已取消：只要入点 1.5s 内有静音段，就把镜头整体挪过去
    w = _work(tmp_path, [("c001", 13, 0)], [_ch("a", ["c001"])], silences={"c001": [[2.0, 2.4]]})
    rows, _, _ = plan(w, 6 * US, seed=3)
    assert rows[0]["in_us"] == int(2.2 * US)


def test_orientation_bad_frames_avoided(tmp_path):
    w = _work(tmp_path, [("c001", 30, 0)], [_ch("a", ["c001"])])
    _frames(tmp_path, [("c001", t, 0) for t in (4.0, 12.0, 20.0, 28.0)])
    with open(os.path.join(w, "orientation.json"), "w") as f:
        json.dump({"clips": {"c001": {"rotate": 0, "bad": [12.0, 20.0]}}}, f)
    rows, _, _ = plan(w, 9 * US, seed=1)
    assert rows and all(not (r["in_us"] <= t * US < r["in_us"] + r["dur_us"]) for r in rows for t in (12.0, 20.0))


def test_rhythm_reorder_breaks_runs_with_small_moves():
    from plan import rhythm_reorder
    kinds = ["long", "long", "short", "short", "short", "mid", "long", "long"]
    shots = [{"kind": k, "i": i} for i, k in enumerate(kinds)]
    out = rhythm_reorder(shots)
    ks = [s["kind"] for s in out]
    assert sorted(s["i"] for s in out) == list(range(len(kinds)))               # 一个不少
    assert all(abs(p - s["i"]) <= 2 for p, s in enumerate(out))                  # 每个最多挪 2 位
    assert not any(a == b == "long" for a, b in zip(ks, ks[1:]))
    assert not any(a == b == c == "short" for a, b, c in zip(ks, ks[1:], ks[2:]))


def test_rhythm_reorder_keeps_good_order():
    from plan import rhythm_reorder
    shots = [{"kind": k, "i": i} for i, k in enumerate(["long", "short", "short", "mid", "long"])]
    assert [s["i"] for s in rhythm_reorder(shots)] == [0, 1, 2, 3, 4]


def _thread(rows):
    return ["a" if r["name"] in ("c001.mp4", "c003.mp4") else "b" for r in rows]


def test_intercut_alternates_threads(tmp_path):
    ch = dict(_ch("x", ["c001", "c002", "c003", "c004"]),
              intercut={"a": ["c001", "c003"], "b": ["c002", "c004"], "end_on": "a"})
    w = _work(tmp_path, [("c001", 90, 0), ("c002", 90, 0), ("c003", 90, 0), ("c004", 90, 0)], [ch])
    rows, _, short = plan(w, 80 * US, seed=2)
    th = _thread(rows)
    assert short == 0 and sum(r["dur_us"] for r in rows) == 80 * US
    assert all(x != y for x, y in zip(th, th[1:]))          # 两条线严格交替
    assert th[-1] == "a"                                     # 落在指定的线上


def test_intercut_end_on_b(tmp_path):
    ch = dict(_ch("x", ["c001", "c002", "c003", "c004"]),
              intercut={"a": ["c002", "c004"], "b": ["c001", "c003"], "end_on": "b"})   # 最晚的素材在 a 线
    w = _work(tmp_path, [("c001", 90, 0), ("c002", 90, 0), ("c003", 90, 0), ("c004", 90, 0)], [ch])
    rows, _, _ = plan(w, 80 * US, seed=2)
    assert rows[-1]["name"] in ("c001.mp4", "c003.mp4")

from understand import build_map, proxy_cmd, split_to_clips


def test_proxy_cmd_pads_not_crops():
    c = " ".join(proxy_cmd({"path": "x.mp4", "has_audio": "True"}, "o.mp4"))
    assert "force_original_aspect_ratio=decrease" in c and "pad=1280:720" in c
    assert "crop" not in c and "fps=15" in c


def test_proxy_cmd_adds_silence_for_mute_clip():
    c = " ".join(proxy_cmd({"path": "x.mp4", "has_audio": "False"}, "o.mp4"))
    assert "anullsrc" in c and "-shortest" in c


def test_build_map_accumulates_real_durations():
    rows = [{"clip_id": "c001", "path": "/a.mp4"}, {"clip_id": "c002", "path": "/b.mp4"}]
    pm = build_map(rows, [10.0, 20.5])
    assert pm[1] == {"clip_id": "c002", "source_path": "/b.mp4", "proxy_start": 10.0, "proxy_end": 30.5}


def test_split_to_clips():
    pm = [{"clip_id": "c001", "proxy_start": 0, "proxy_end": 10},
          {"clip_id": "c002", "proxy_start": 10, "proxy_end": 30}]
    vlm = [{"start": 2, "end": 12, "description": "山路", "frame_facts": {}},   # 8s 在 c001 → 归 c001
           {"start": 12, "end": 30, "description": "瀑布", "frame_facts": {}}]
    asr = [{"start": 8, "end": 13, "text": "到了"}]                           # 中点 10.5 → c002
    out = split_to_clips(pm, vlm, asr)
    assert out["c001"]["scenes"][0]["description"] == "山路"
    assert out["c002"]["scenes"][0] == {"start": 2.0, "end": 20.0, "description": "瀑布", "frame_facts": {}}
    assert out["c002"]["speech"][0]["text"] == "到了" and out["c002"]["speech"][0]["start"] == 0.0


def test_pick_vision_model():
    from understand import pick_vision_model
    avail = ["mimo-v2.5-asr", "mimo-v2.5-tts", "mimo-v2.6-flash", "mimo-v2.6-pro"]
    assert pick_vision_model(avail, None) == "mimo-v2.6-flash"          # 上游默认 v2.5 已下线
    assert pick_vision_model(avail + ["mimo-v2.5"], None) == "mimo-v2.5"
    assert pick_vision_model(avail, "mimo-v2.6-pro") == "mimo-v2.6-pro"   # 用户指定优先
    assert pick_vision_model(avail, "mimo-v9") is None                    # 指定了不存在的
    assert pick_vision_model(["mimo-v2.5-asr", "mimo-v2.5-tts"], None) is None


def test_should_retry_resumable_network_failure():
    from understand import should_retry
    tail = "RuntimeError: VLM 分析失败 2/68 个场景。其余已缓存到 vlm_scene_cache.json，重跑可断点续传。<urlopen error TLS/SSL connection has been closed (EOF)>"
    assert should_retry(tail, "other")
    assert not should_retry(tail, "recharge")              # 余额问题重试也没用
    assert not should_retry("ValueError: bad scenes.json", "other")


def test_normalize_orientation():
    from understand import normalize_orientation as n
    assert [n("正常"), n("上下颠倒"), n("向右倒。"), n("向左倒"), n("无法判断"), n("嗯")] == \
           ["ok", "flip", "tilt", "tilt", "unknown", "unknown"]


def test_decide_orientation_rotates_when_mostly_flipped():
    from understand import decide_orientation
    labels = {f"{t}.0": "flip" for t in range(8)} | {"8.0": "ok", "9.0": "unknown"}
    d = decide_orientation(labels)
    assert d["rotate"] == 180 and d["bad"] == [8.0]          # 转正后原本「正常」的那帧反而倒了


def test_decide_orientation_marks_tilted_frames_bad():
    from understand import decide_orientation
    labels = {"4.0": "ok", "12.0": "tilt", "20.0": "flip", "28.0": "ok"}
    d = decide_orientation(labels)
    assert d["rotate"] == 0 and d["bad"] == [12.0, 20.0]


def test_decide_orientation_needs_three_frames_to_rotate():
    from understand import decide_orientation
    d = decide_orientation({"4.00": "flip", "12.00": "unknown"})     # 实测：c040 正常画面被单帧误判
    assert d == {"rotate": 0, "bad": [4.0]}


def test_mostly_tilted_clip_is_unusable():
    from understand import decide_orientation
    labels = {"4.00": "tilt", "12.00": "unknown", "20.00": "flip", "28.00": "tilt", "36.00": "tilt", "44.00": "ok"}
    d = decide_orientation(labels)   # 4/6 歪倒（c024 这种挂着晃的）：缝隙里的画面也不可信，整段不用
    assert d["rotate"] == 0 and d["bad"] == [4.0, 12.0, 20.0, 28.0, 36.0, 44.0] and d.get("unusable")

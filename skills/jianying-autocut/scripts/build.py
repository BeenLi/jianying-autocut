# /// script
# requires-python = ">=3.10"
# dependencies = ["pyJianYingDraft @ git+https://github.com/aoguai/pyJianYingDraft@69cee12ae3f7442416df16acdf368ae574764811", "pymediainfo"]
# ///
"""第 6 步 生成剪映草稿：shots.csv → 剪映专业版 11.6 能直接打开的草稿

用法: uv run --script build.py --work W --name 庐山粗剪 [--titles] [--bgm 歌.mp3[:音量[:淡入淡出秒]]] [--subs W/subtitles.json] [--replace]
      旁白片：… --narration W/narration_track.json [--bgm 歌.mp3] [--titles]

  · 版本号：new_version / app_version 每次从本机剪映读（root_meta_info.json + Info.plist），不硬编码
  · 素材零复制：只引用绝对路径；时长 / 宽高取自 inventory.csv 直接注入，不再逐个解析文件
  · 时间：一律整数微秒 Timerange(起点, 时长)，下一段起点 = 上一段终点
  · 清场：剪映在跑就拒绝；同名草稿默认拒绝，--replace 才整目录删掉再生成
  · BGM：可多次 --bgm，按歌长比例依次铺满成片；歌比成片短就循环，比成片长就截断；首尾淡入淡出
  · 画面方向：orientation.json 判定整段倒装的素材，片段旋转 180°
  · 字幕：--subs 给出有意义的人声（{clip_id: [{start, end, text}]}，素材内秒），生成底部带底色的字幕；
    说话时 BGM 压到 25%，有字幕的镜头原声开到 100%
  · 旁白片（--narration，narrate.py 的输出）：多一条「旁白」音轨；人声按来源归一化到 -16 LUFS（最多 +12dB、
    真峰值 ≤ -1dBTP）；旁白下的原声垫底，原声段（live）按人声归一化；BGM 默认停在压低档、全片一个值，
    只在长空隙 / bgm: up 处升起，bgm: drop 处淡出；逐句校验人声比 BGM 高 ≥ 12 LU（只报告）
  · 写完重新读回来自检：零缝隙零重叠、时长精确、无悬空引用、素材零复制、版本号对齐、BGM 不越界
只生成草稿，不导出成片——导出请在剪映里手动点。
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter

import pyJianYingDraft as jy
from pyJianYingDraft import Timerange, TrackSpec, TrackType

import loudness
from common import DRAFTS_DIR, US, detect_versions, jianying_running, read_csv

TITLE_US = 3 * US
MIN_BGM_TAIL = 1 * US
MIN_SUB = US // 2          # 字幕落进镜头不到 0.5s 就不显示，闪一下看不清
SUB_CUT_WARN = 0.8         # 一句话只剩不到 80% 在镜头里：提醒这句被剪断了
DUCK = 0.25                # 有人说话时 BGM 压到原音量的这个比例
DUCK_RAMP = int(0.3 * US)  # 压低 / 恢复的过渡时长
SPEECH_VOLUME = 1.0        # 有字幕的镜头原声音量
NARR_TRACK = "旁白"
RAMP_UP = int(0.8 * US)    # 旁白片：BGM 升起用的过渡（比压低慢，听着不突兀）
LOUD_GAP = 4 * US          # 旁白片：没有人声的空隙至少这么长，BGM 才升起来
NOISE_MIN_DB = 15.0        # 原声段：人声比底噪高不到这么多 dB 就不提升（越提越吵）


def place_subs(subs, shots):
    """subs：{clip_id: [{start, end, text}]}（素材内秒）；shots：带 clip_id 的镜头行。
    返回 ([(成片起点, 时长, 文字)], 警告)。每句只显示落在镜头里的部分。"""
    placed, shown = [], {}
    for s in shots:
        cid, a0, d = s["clip_id"], int(s["in_us"]), int(s["dur_us"])
        for i, line in enumerate(subs.get(cid, [])):
            a, b = round(line["start"] * US), round(line["end"] * US)
            lo, hi = max(a, a0), min(b, a0 + d)
            if hi - lo >= MIN_SUB:
                placed.append((int(s["start_us"]) + lo - a0, hi - lo, line["text"]))
                shown[(cid, i)] = shown.get((cid, i), 0) + hi - lo
    warns = []
    for cid, lines in subs.items():
        for i, line in enumerate(lines):
            got, want = shown.get((cid, i), 0), round((line["end"] - line["start"]) * US)
            if not got:
                warns.append(f"{cid}「{line['text']}」不在成片里（镜头没取到这段），没加字幕")
            elif got < want * SUB_CUT_WARN:
                warns.append(f"{cid}「{line['text']}」只有 {got / want:.0%} 在镜头里，这句话被剪断了")
    return sorted(placed), warns


def duck_keyframes(speech, seg_start, seg_dur, base, duck, ramp=DUCK_RAMP, merge_gap=None):
    """speech：[(成片起点, 时长)]。返回 BGM 片段内的音量关键帧 [(片段内偏移, 音量)]：
    说话时压到 duck，前后各用 ramp 过渡；间隔不到 2 个 ramp 的两句合并，不在中间把音乐拉起来。"""
    spans = []
    for t, d in sorted(speech):
        a, b = max(t, seg_start) - seg_start, min(t + d, seg_start + seg_dur) - seg_start
        if b <= a:
            continue
        if spans and a - spans[-1][1] < (2 * ramp if merge_gap is None else merge_gap):
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    kf = []
    for a, b in spans:
        if a - ramp >= 0:
            kf.append((a - ramp, base))
        kf += [(a, duck), (b, duck)]
        if b + ramp <= seg_dur:
            kf.append((b + ramp, base))
    return kf


def bgm_curve(speech, ups, drops, seg_start, seg_dur, base, duck, ramp_down=DUCK_RAMP, ramp_up=RAMP_UP,
              min_gap=LOUD_GAP, total_us=None):
    """旁白片的 BGM 音量曲线（片段内关键帧）：默认停在压低档 base*duck；没有人声的空隙 ≥ min_gap、
    或 ups 区间升到 base；drops 区间降到 0。压低在边界前完成（开口时已压好），升起在边界后开始。"""
    total = total_us if total_us is not None else seg_start + seg_dur
    low = base * duck
    loud, prev = [], 0
    for a, d in sorted(speech):
        if a - prev >= min_gap:
            loud.append((prev, a))
        prev = max(prev, a + d)
    if total - prev >= min_gap:
        loud.append((prev, total))
    loud += [(a, a + d) for a, d in ups]
    drop = [(a, a + d) for a, d in drops]

    def level(t):
        if any(a <= t < b for a, b in drop):
            return 0.0
        return base if any(a <= t < b for a, b in loud) else low

    xs = sorted({x for a, b in loud + drop for x in (a, b) if 0 < x < total})
    bps = [(0, level(0))]
    for k, x in enumerate(xs):
        A, B = level(x - 1), level(x)
        if A == B:
            continue
        if B < A:
            bps += [(max(x - ramp_down, bps[-1][0]), A), (x, B)]
        else:
            nxt = xs[k + 1] if k + 1 < len(xs) else total
            bps += [(x, A), (min(x + ramp_up, nxt), B)]
    bps.append((total, level(total - 1)))

    def at(t):
        for (a, va), (b, vb) in zip(bps, bps[1:]):
            if a <= t <= b:
                return va if b == a else va + (vb - va) * (t - a) / (b - a)
        return bps[-1][1]

    offs = sorted({0, seg_dur} | {t - seg_start for t, _ in bps if seg_start < t < seg_start + seg_dur})
    return [(o, at(seg_start + o)) for o in offs]


def injected_audio(path, duration_us):
    """不走 AudioMaterial.__init__（它要 pymediainfo 解析文件）：时长取自 transcribe.py --narration 的记录。"""
    m = jy.AudioMaterial.__new__(jy.AudioMaterial)
    m.path = os.path.abspath(path)
    m.material_name = os.path.basename(path)
    m.material_id = uuid.uuid4().hex
    m.duration = duration_us
    return m


def narration_mix(cache, narr, shots, inv, speech_json):
    """旁白片的音量：返回 (旁白文件增益 {path: g}, 原声段增益 {clip_id: g}, 垫底 {clip_id: g}, 人声电平 {key: LUFS}, 报告)。
    人声电平的 key：旁白文件路径，或 "live:<clip_id>"。"""
    notes, vo_gain, live_gain, bed, level = [], {}, {}, {}, {}
    for path in sorted({a["file"] for a in narr["audio"]}):
        m = cache.measure(path)
        g, short = loudness.voice_gain(m["i"], m["tp"])
        vo_gain[path], level[path] = g, m["i"] + loudness.db(g)
        if short > 0.05:
            notes.append(f"{os.path.basename(path)} 太小声，提到 +{loudness.db(g):.1f} dB 还差 {short:.1f} dB："
                         "建议重录，或在剪映里降噪后再提")
    by_cid = {r["clip_id"]: r for r in inv.values()}
    for lv in narr["live"]:
        cid = lv["clip_id"]
        path = by_cid[cid]["path"]
        a, b = lv["src_us"] / US, (lv["src_us"] + lv["dur_us"]) / US
        lines = [l for l in speech_json.get(cid, []) if l["end"] > a and l["start"] < b]
        whole = cache.measure(path, round(a, 3), round(b, 3))
        m = cache.measure(path, round(max(a, min(l["start"] for l in lines)), 3),
                          round(min(b, max(l["end"] for l in lines)), 3)) if lines else whole
        g, short = loudness.voice_gain(m["i"], m["tp"])
        floor = min((v for _, v in whole["short"] if v > -70), default=m["i"])
        if g > 1 and m["i"] - floor < NOISE_MIN_DB:
            g = 1.0
            notes.append(f"原声段 {cid} 现场太吵（人声只比底噪高 {m['i'] - floor:.1f} dB），没有提升音量")
        live_gain[cid], level["live:" + cid] = g, m["i"] + loudness.db(g)
    for s in shots:
        cid = s["clip_id"]
        if s["kind"] == "narr" and cid not in bed:
            row = by_cid[cid]
            bed[cid] = loudness.bed_gain(cache.measure(row["path"])["i"]) if str(row.get("has_audio")) == "True" else 0.0
    return vo_gain, live_gain, bed, level, notes


def bgm_mix(cache, bgms, songs, total, speech):
    """每首歌按实测拉到同一响度（只衰减），再算全片统一的压低比例。
    返回 ([(歌内铺法 segs, 基础增益, 实测)], 压低比例)。"""
    meas = [cache.measure(b["path"]) for b in bgms]
    quiet = min(m["i"] for m in meas)
    cum = [0]
    for m in songs:
        cum.append(cum[-1] + m.duration)
    plans, levels = [], []
    for k, (b, mat, m) in enumerate(zip(bgms, songs, meas)):
        start, end = total * cum[k] // cum[-1], total * cum[k + 1] // cum[-1]
        segs = bgm_segments(mat.duration, start, end)
        base = b["gain"] * min(1.0, 10 ** ((quiet - m["i"]) / 20))
        s_max = None
        for t0, s0, d in segs:
            for a, dd in speech:
                lo, hi = max(a, t0), min(a + dd, t0 + d)
                if hi > lo:
                    v = loudness.max_short(m["short"], (s0 + lo - t0) / US, (s0 + hi - t0) / US)
                    if v is not None:
                        s_max = v if s_max is None else max(s_max, v)
        if s_max is not None:
            levels.append((loudness.db(base), s_max))
        plans.append((segs, base, m))
    return plans, loudness.bgm_duck(levels)


def bgm_level_fn(plans, duck):
    """(a_us, b_us) → 这段时间里 BGM 的实际最大短时响度（已含增益和压低）；没有 BGM 返回 None。"""
    def f(a, b):
        best = None
        for segs, base, m in plans:
            for t0, s0, d in segs:
                lo, hi = max(a, t0), min(b, t0 + d)
                if hi > lo:
                    v = loudness.max_short(m["short"], (s0 + lo - t0) / US, (s0 + hi - t0) / US)
                    if v is not None:
                        v += loudness.db(base * duck)
                        best = v if best is None else max(best, v)
        return best
    return f


def parse_bgm(arg):
    """'路径[:音量[:淡入淡出秒]]'；只把末尾的数字段当参数，路径里的冒号不受影响。"""
    path, gain, fade = arg, 0.2, 1.5
    nums = []
    while True:
        m = re.match(r"^(.*):(\d+(?:\.\d+)?)$", path)
        if not m or len(nums) == 2:
            break
        path, n = m.group(1), float(m.group(2))
        nums.insert(0, n)
    if nums:
        gain = nums[0]
    if len(nums) > 1:
        fade = nums[1]
    return {"path": os.path.expanduser(path), "gain": gain, "fade": fade}


def bgm_segments(song_us, start_us, end_us):
    """在 [start, end) 上铺一首长 song_us 的歌：返回 [(轨道起点, 歌内起点, 时长)]。
    歌短就从头循环；循环后剩下不足 1s 的尾巴，从上一段借时间补成 1s，避免最后闪一下。"""
    segs, t = [], start_us
    while t < end_us:
        d = min(song_us, end_us - t)
        segs.append([t, 0, d])
        t += d
    if len(segs) > 1 and segs[-1][2] < MIN_BGM_TAIL:
        borrow = MIN_BGM_TAIL - segs[-1][2]
        segs[-2][2] -= borrow
        segs[-1][0] -= borrow
        segs[-1][2] += borrow
    return [tuple(s) for s in segs]


def injected_material(row):
    """不走 VideoMaterial.__init__（它会用 pymediainfo 再解析一遍文件），
    直接把第 1 步盘点出的真实时长 / 宽高写进去。字段与 pyJianYingDraft 0.3.0 的 __init__ 一致。"""
    m = jy.VideoMaterial.__new__(jy.VideoMaterial)
    m.path = os.path.abspath(row["path"])
    m.material_name = row["name"]
    m.material_id = uuid.uuid4().hex
    m.crop_settings = jy.CropSettings()
    m.local_material_id = ""
    m.check_flag = jy.local_materials.DEFAULT_VIDEO_CHECK_FLAG
    m.beauty_face_auto_preset_infos = []
    m.beauty_face_preset_infos = []
    m.beauty_body_preset_id = ""
    m.beauty_body_auto_preset = None
    m.beauty_face_auto_preset = jy.VideoMaterial._default_beauty_face_auto_preset()
    m.is_unified_beauty_mode = False
    m.material_type = "video"
    m.duration = round(float(row["duration_s"]) * US)
    m.width, m.height = int(row["width"]), int(row["height"])
    return m


def stamp_versions(script, meta_path, v):
    """正文和元数据都写成本机剪映的真实版本，避免剪映按旧版草稿走「升级」流程。"""
    script.content["new_version"] = v["new_version"]
    plat = {"app_id": 3704, "app_source": "lv", "app_version": v["app_version"],
            "device_id": "", "hard_disk_id": "", "mac_address": "",
            "os": "mac", "os_version": platform.mac_ver()[0]}
    script.content["platform"] = dict(plat)
    script.content["last_modified_platform"] = dict(plat)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["draft_new_version"] = v["new_version"]  # 库保存时会保留这个值
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def verify(draft_dir, shots, versions, bgm_expected, narr_expected=0):
    """落盘后重新读回来校验，任何一条不过都算失败。"""
    with open(os.path.join(draft_dir, "draft_info.json"), encoding="utf-8") as f:
        d = json.load(f)
    with open(os.path.join(draft_dir, "draft_meta_info.json"), encoding="utf-8") as f:
        meta = json.load(f)
    errs = []
    expect = sum(int(s["dur_us"]) for s in shots)
    if d["duration"] != expect:
        errs.append(f"总时长 {d['duration']} ≠ 计划 {expect}")
    video = [t for t in d["tracks"] if t["type"] == "video"][0]["segments"]
    if len(video) != len(shots):
        errs.append(f"主轨 {len(video)} 段 ≠ 计划 {len(shots)} 段")
    cursor = 0
    for i, seg in enumerate(video, 1):
        tr = seg["target_timerange"]
        if tr["start"] != cursor:
            errs.append(f"第 {i} 段起点 {tr['start']} ≠ 上一段终点 {cursor}（{'缝隙' if tr['start'] > cursor else '重叠'}）")
        cursor = tr["start"] + tr["duration"]
    audio = [s for t in d["tracks"] if t["type"] == "audio" and t.get("name") != NARR_TRACK for s in t["segments"]]
    narr = [s for t in d["tracks"] if t["type"] == "audio" and t.get("name") == NARR_TRACK for s in t["segments"]]
    if len(narr) != narr_expected:
        errs.append(f"旁白段数 {len(narr)} ≠ 预期 {narr_expected}")
    for s in narr:
        tr = s["target_timerange"]
        if tr["start"] + tr["duration"] > expect:
            errs.append(f"旁白段 {tr['start']} 超出成片终点 {expect}")
    if len(audio) != bgm_expected:
        errs.append(f"BGM 段数 {len(audio)} ≠ 预期 {bgm_expected}")
    end = 0
    for s in sorted(audio, key=lambda s: s["target_timerange"]["start"]):
        tr = s["target_timerange"]
        if tr["start"] < end:
            errs.append(f"BGM 段重叠于 {tr['start']}")
        end = tr["start"] + tr["duration"]
    if audio and end != expect:
        errs.append(f"BGM 终点 {end} ≠ 成片时长 {expect}")
    mats = d["materials"]
    ids = {m.get("id") for lst in mats.values() if isinstance(lst, list) for m in lst if isinstance(m, dict)}
    for t in d["tracks"]:
        for seg in t["segments"]:
            for ref in seg.get("extra_material_refs", []):
                if ref not in ids:
                    errs.append(f"{t['type']} 轨片段有悬空引用 {ref}")
    for m in mats["videos"] + mats.get("audios", []):
        if not os.path.exists(m["path"]):
            errs.append(f"素材不存在 {m['path']}")
        elif os.path.abspath(m["path"]).startswith(os.path.abspath(draft_dir) + os.sep):
            errs.append(f"素材被复制进了草稿目录 {m['path']}")
    if d["new_version"] != versions["new_version"] or meta.get("draft_new_version") != versions["new_version"]:
        errs.append(f"版本号未对齐：正文 {d['new_version']} / 元数据 {meta.get('draft_new_version')}")
    return errs, d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--name", required=True, help="草稿名（剪映首页显示的名字）")
    ap.add_argument("--drafts-dir", default=DRAFTS_DIR, help="剪映「全局设置 → 草稿位置」")
    ap.add_argument("--volume", type=float, help="原声音量，0 = 静音；默认 1，有 BGM 时 0.6")
    ap.add_argument("--bgm", action="append", default=[], help="歌曲路径[:音量[:淡入淡出秒]]，可多次")
    ap.add_argument("--bgm-plan", help="beatsync.py 生成的 bgm_plan.json（卡点）；给了就不用 --bgm")
    ap.add_argument("--titles", action="store_true", help="每章开头加 3 秒章节标题（文字轨）")
    ap.add_argument("--subs", help="字幕文件（有意义的人声），见 references/pitfalls.md「字幕」")
    ap.add_argument("--replace", action="store_true", help="同名草稿已存在时整目录删除后重建")
    ap.add_argument("--narration", help="旁白片：narrate.py 生成的 narration_track.json")
    args = ap.parse_args()
    if args.narration and args.bgm_plan:
        sys.exit("旁白片不卡点：镜头时长由旁白决定，用 --bgm 铺 BGM，不要用 --bgm-plan")

    if jianying_running():
        sys.exit("剪映正在运行。请 ⌘Q 完全退出剪映后再跑（它退出时会把打开过的草稿重新加密覆盖）。")
    bgms = [parse_bgm(b) for b in args.bgm]
    for b in bgms:
        if not os.path.exists(b["path"]):
            sys.exit(f"找不到 BGM 文件 {b['path']}")
        if b["path"].lower().endswith(".ncm"):
            sys.exit(f"{b['path']} 是网易云加密格式，剪映放不了；换 mp3 / flac / m4a")
    # 草稿名只能是草稿目录下的一级子目录名：防止 "" / "." / ".." / "a/b" 指到草稿库本身或库外
    if args.name in ("", ".", "..") or os.path.basename(args.name) != args.name or "/" in args.name:
        sys.exit(f"草稿名「{args.name}」不合法：不能为空、不能是 . / ..，不能含 /")
    draft_dir = os.path.join(args.drafts_dir, args.name)
    if os.path.exists(draft_dir) and not args.replace:
        sys.exit(f"草稿「{args.name}」已存在。换个 --name，或加 --replace 删掉旧草稿重建。")

    # 先把所有输入读齐、校验完，再动用户的旧草稿
    for f in ("shots.csv", "inventory.csv"):
        if not os.path.exists(os.path.join(args.work, f)):
            sys.exit(f"{os.path.join(args.work, f)} 不存在：先跑前面几步，或检查 --work")
    shots = read_csv(os.path.join(args.work, "shots.csv"))
    inv = {r["path"]: r for r in read_csv(os.path.join(args.work, "inventory.csv"))}
    missing = [s["source"] for s in shots if s["source"] not in inv]
    if missing:
        sys.exit(f"shots.csv 引用了 inventory.csv 里没有的素材：{missing[:3]}")
    for s in shots:
        s["clip_id"] = inv[s["source"]]["clip_id"]
    subs, sub_warns = [], []
    narr = None
    if args.narration:
        with open(args.narration, encoding="utf-8") as f:
            narr = json.load(f)
        with open(os.path.join(args.work, "narration_speech.json"), encoding="utf-8") as f:
            vo = json.load(f)
        vo_durs = {p: round(vo["durations"][fid] * US) for fid, p in vo["files"].items() if fid in vo["durations"]}
        missing_vo = [a["file"] for a in narr["audio"] if a["file"] not in vo_durs or not os.path.exists(a["file"])]
        if missing_vo:
            sys.exit(f"旁白文件不存在或没转写过：{missing_vo[:3]}")
        sp = os.path.join(args.work, "speech.json")
        speech_json = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
        cache = loudness.Cache(args.work)
        try:
            vo_gain, live_gain, bed, voice_level, mix_notes = narration_mix(cache, narr, shots, inv, speech_json)
        except (OSError, subprocess.SubprocessError) as e:
            sys.exit(f"测响度失败（需要 ffmpeg）：{e}")
    if args.subs:
        with open(args.subs, encoding="utf-8") as f:
            subs, sub_warns = place_subs(json.load(f), shots)
    versions = detect_versions(args.drafts_dir)
    print(f"本机剪映 {versions['app_version']}，草稿版本 {versions['new_version']}"
          f"（读自草稿「{versions['from_draft']}」）")

    # 画布：按镜头时长加权选主导画幅，同画幅取最高分辨率，免得 4K 素材被压成 1080p
    aspect, fps_w = Counter(), Counter()
    for s in shots:
        r = inv[s["source"]]
        aspect[round(int(r["width"]) / int(r["height"]), 2)] += int(s["dur_us"])
        fps_w[round(float(r["fps"]))] += int(s["dur_us"])
    main_aspect = aspect.most_common(1)[0][0]
    used = {s["source"] for s in shots}   # 只看成片里真用到的素材，被剔除的 4K 素材不该把画布撑大
    w, h = max((int(r["width"]), int(r["height"])) for p, r in inv.items()
               if p in used and round(int(r["width"]) / int(r["height"]), 2) == main_aspect)
    fps = fps_w.most_common(1)[0][0]
    volume = args.volume if args.volume is not None else (0.6 if bgms or args.bgm_plan else 1.0)

    if os.path.exists(draft_dir):   # 坑：被剪映打开过的草稿已加密，只能整目录删掉重建
        shutil.rmtree(draft_dir)
        print(f"已删除旧草稿目录 {draft_dir}")
    folder = jy.DraftFolder(args.drafts_dir)   # 不传 user_data_path：不改剪映的全局注册表
    script = folder.create_draft(args.name, w, h, fps)
    stamp_versions(script, os.path.join(draft_dir, "draft_meta_info.json"), versions)

    # 第 3 步判定整段倒装的素材（运动相机倒挂等）：片段转 180°
    rotate = {}
    op = os.path.join(args.work, "orientation.json")
    if os.path.exists(op):
        with open(op, encoding="utf-8") as f:
            rotate = {c: d.get("rotate", 0) for c, d in json.load(f).get("clips", {}).items()}
    main_track = script.append_track(TrackSpec(TrackType.video, "主轨"))
    mats = {}
    for s in shots:
        src = s["source"]
        if src not in mats:  # 同一素材多次取用只建一个素材对象
            mats[src] = injected_material(inv[src])
            script.add_material(mats[src])
        dur = int(s["dur_us"])
        cs = jy.ClipSettings(rotation=180) if rotate.get(inv[src]["clip_id"]) == 180 else None
        t0 = int(s["start_us"])
        if narr is not None:   # 旁白片：原声音量只由镜头类型决定
            cid = inv[src]["clip_id"]
            vol = live_gain.get(cid, 1.0) if s["kind"] == "live" else (
                args.volume if args.volume is not None else bed.get(cid, 0.0))
        else:
            talks = any(a < t0 + dur and t0 < a + d for a, d, _ in subs)
            vol = max(volume, SPEECH_VOLUME) if talks else volume
        seg = jy.VideoSegment(mats[src], Timerange(t0, dur), source_timerange=Timerange(int(s["in_us"]), dur),
                              volume=vol, clip_settings=cs)
        script.add_segment(seg, main_track)
    total = sum(int(s["dur_us"]) for s in shots)

    narr_count = 0
    if narr is not None:
        vo_track = script.append_track(TrackSpec(TrackType.audio, NARR_TRACK))
        vo_mats = {}
        for a in narr["audio"]:
            p = a["file"]
            if p not in vo_mats:
                vo_mats[p] = injected_audio(p, vo_durs[p])
            seg = jy.AudioSegment(vo_mats[p], Timerange(a["start_us"], a["dur_us"]),
                                  source_timerange=Timerange(a["src_us"], a["dur_us"]), volume=vo_gain[p])
            if a.get("fade_in_us") or a.get("fade_out_us"):
                seg.add_fade(a.get("fade_in_us", 0), a.get("fade_out_us", 0))
            script.add_segment(seg, vo_track)
            narr_count += 1
        subs = sorted(subs + [(x["start_us"], x["dur_us"], x["text"]) for x in narr["subs"]])

    if args.titles:
        text_track = script.append_track(TrackSpec(TrackType.text, "章节标题"))
        seen = set()
        for s in shots:
            if s["chapter"] in seen:
                continue
            seen.add(s["chapter"])
            seg = jy.TextSegment(s["chapter_title"], Timerange(int(s["start_us"]), min(TITLE_US, total - int(s["start_us"]))),
                                 style=jy.TextStyle(size=8.0, bold=True),
                                 clip_settings=jy.ClipSettings(transform_y=-0.75))
            seg.extra_material_refs = []  # 悬空的变速引用会让剪映报「草稿内容已损坏」
            script.add_segment(seg, text_track)

    if subs:
        sub_track = script.append_track(TrackSpec(TrackType.text, "字幕"))
        for t0, d, text in subs:
            seg = jy.TextSegment(text, Timerange(t0, d), style=jy.TextStyle(size=6.0, color=(1.0, 1.0, 1.0)),
                                 background=jy.TextBackground(color="#000000", alpha=0.55, round_radius=0.3),
                                 clip_settings=jy.ClipSettings(transform_y=-0.85))
            seg.extra_material_refs = []
            script.add_segment(seg, sub_track)
    speech = [(t0, d) for t0, d, _ in subs] if narr is None else [tuple(x) for x in narr["speech"]]

    def duck(seg, t0, d, gain):
        for off, v in duck_keyframes(speech, t0, d, gain, gain * DUCK):
            seg.add_keyframe(off, v)

    bgm_count = 0
    if args.bgm_plan:
        with open(args.bgm_plan, encoding="utf-8") as f:
            plan = json.load(f)
        bgm_track = script.append_track(TrackSpec(TrackType.audio, "BGM"))
        for b in plan:
            mat = jy.AudioMaterial(b["path"])
            d = min(int(b["dur_us"]), total - int(b["start_us"]), mat.duration - int(b["src_us"]))
            seg = jy.AudioSegment(mat, Timerange(int(b["start_us"]), d),
                                  source_timerange=Timerange(int(b["src_us"]), d), volume=b["gain"])
            fade = min(round(b["fade"] * US), d // 2)
            seg.add_fade(0 if b["start_us"] else fade, fade)   # 卡点换歌：只淡出，下一首在拍上直接进
            duck(seg, int(b["start_us"]), d, b["gain"])
            script.add_segment(seg, bgm_track)
            bgm_count += 1
    elif bgms and narr is not None:
        bgm_track = script.append_track(TrackSpec(TrackType.audio, "BGM"))
        songs = [jy.AudioMaterial(b["path"]) for b in bgms]
        plans, duck_ratio = bgm_mix(cache, bgms, songs, total, speech)
        ups = [(x["start_us"], x["dur_us"]) for x in narr["bgm"] if x["mode"] == "up"]
        drops = [(x["start_us"], x["dur_us"]) for x in narr["bgm"] if x["mode"] == "drop"]
        for b, mat, (segs, base, _) in zip(bgms, songs, plans):
            fade = round(b["fade"] * US)
            for i, (t0, s0, d) in enumerate(segs):
                seg = jy.AudioSegment(mat, Timerange(t0, d), source_timerange=Timerange(s0, d), volume=base)
                fin = min(fade, d // 2) if i == 0 else 0
                fout = min(fade, d // 2) if i == len(segs) - 1 else 0
                if fin or fout:
                    seg.add_fade(fin, fout)
                for off, v in bgm_curve(speech, ups, drops, t0, d, base, duck_ratio, total_us=total):
                    seg.add_keyframe(off, v)
                script.add_segment(seg, bgm_track)
                bgm_count += 1
        live_at = [(x["start_us"], x["start_us"] + x["dur_us"], x["clip_id"]) for x in narr["live"]]
        audio_at = [(x["start_us"], x["start_us"] + x["dur_us"], x["file"]) for x in narr["audio"]]

        def voice_of(t):
            for a, b_, cid in live_at:
                if a <= t < b_:
                    return voice_level["live:" + cid]
            for a, b_, p in audio_at:
                if a <= t < b_:
                    return voice_level[p]
            return loudness.VOICE_TARGET
        mix_notes += loudness.margin_warnings(speech, bgm_level_fn(plans, duck_ratio), [voice_of(t) for t, _ in speech])
        mix_notes.insert(0, f"BGM 全片压低到 {duck_ratio:.0%}（只在长空隙 / bgm: up 处升起）")
    elif bgms:
        bgm_track = script.append_track(TrackSpec(TrackType.audio, "BGM"))
        songs = [jy.AudioMaterial(b["path"]) for b in bgms]
        # 按歌长比例分段：成片时长 = 各首歌长之和时，每首歌完整播放、不截断不循环
        cum = [0]
        for m in songs:
            cum.append(cum[-1] + m.duration)
        for k, (b, mat) in enumerate(zip(bgms, songs)):
            start = total * cum[k] // cum[-1]
            end = total * cum[k + 1] // cum[-1]
            segs = bgm_segments(mat.duration, start, end)
            fade = round(b["fade"] * US)
            for i, (t0, s0, d) in enumerate(segs):
                seg = jy.AudioSegment(mat, Timerange(t0, d), source_timerange=Timerange(s0, d), volume=b["gain"])
                fin = min(fade, d // 2) if i == 0 else 0
                fout = min(fade, d // 2) if i == len(segs) - 1 else 0
                if fin or fout:
                    seg.add_fade(fin, fout)
                duck(seg, t0, d, b["gain"])
                script.add_segment(seg, bgm_track)
                bgm_count += 1

    script.save()  # 不传 inline_materials：素材只记路径

    if narr is None and bgms and subs:   # 口播片也查一遍：人声要比同时段 BGM 高 ≥ 12 LU
        try:
            cache = loudness.Cache(args.work)
            plans, _ = bgm_mix(cache, bgms, songs, total, speech)
            voice = []
            for t0, d, _ in subs:
                shot = next(s for s in shots if int(s["start_us"]) <= t0 < int(s["start_us"]) + int(s["dur_us"]))
                a = (int(shot["in_us"]) + t0 - int(shot["start_us"])) / US
                voice.append(cache.measure(shot["source"], round(a, 3), round(a + d / US, 3))["i"])
            for w_ in loudness.margin_warnings(speech, bgm_level_fn(plans, DUCK), voice):
                sub_warns.append(w_)
        except (OSError, subprocess.SubprocessError, StopIteration):
            sub_warns.append("没测成响度（需要 ffmpeg），人声和 BGM 的音量差没有校验")

    errs, d = verify(draft_dir, shots, versions, bgm_count, narr_count)
    sec = d["duration"] / US
    print(f"\n草稿：{draft_dir}")
    print(f"  {len(shots)} 个镜头 / {len(mats)} 段素材 / {len({s['chapter'] for s in shots})} 章"
          f"{' + 章节标题' if args.titles else ''}{f' + BGM {len(bgms)} 首（{bgm_count} 段）' if bgms else (f' + 卡点 BGM {bgm_count} 段' if bgm_count else '')}，"
          f"总长 {int(sec // 60)}:{sec % 60:06.3f}，画布 {w}x{h}@{fps}，"
          + ("原声：旁白下垫底、原声段归一化" if narr is not None else f"原声音量 {volume:g}"))
    if errs:
        print("\n校验失败：")
        for e in errs:
            print("  ✗", e)
        sys.exit(1)
    print("  ✓ 零缝隙零重叠 ✓ 时长精确 ✓ 无悬空引用 ✓ 素材零复制 ✓ 版本号对齐" + (" ✓ BGM 铺满不越界" if bgm_count else ""))
    if narr is not None:
        print(f"  旁白 {narr_count} 段 / 原声段 {len(narr['live'])} 个 / 字幕 {len(subs)} 条")
        boosted = [os.path.basename(p) for p, g in vo_gain.items() if g > 1] + \
                  [c for c, g in live_gain.items() if g > 1]
        if boosted:
            print(f"  ⚠ 音量放大（>100%）待真机验证剪映是否生效：{'、'.join(boosted)}")
        for n in mix_notes:
            print("  ⚠" if "人声只比" in n or "太" in n else "  ·", n)
    if args.subs:
        print(f"  字幕 {len(subs)} 条，说话时 BGM 压到 {DUCK:.0%}")
    for w_ in sub_warns:
        print("  ⚠", w_)
    print("\n现在打开剪映，首页就能看到这个草稿。素材文件别移动或改名（草稿里存的是绝对路径）。")


if __name__ == "__main__":
    main()

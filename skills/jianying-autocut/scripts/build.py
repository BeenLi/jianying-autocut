# /// script
# requires-python = ">=3.10"
# dependencies = ["pyJianYingDraft @ git+https://github.com/aoguai/pyJianYingDraft@69cee12ae3f7442416df16acdf368ae574764811", "pymediainfo"]
# ///
"""第 6 步 生成剪映草稿：shots.csv → 剪映专业版 11.6 能直接打开的草稿

用法: uv run --script build.py --work W --name 庐山粗剪 [--titles] [--bgm 歌.mp3[:音量[:淡入淡出秒]]] [--replace]

  · 版本号：new_version / app_version 每次从本机剪映读（root_meta_info.json + Info.plist），不硬编码
  · 素材零复制：只引用绝对路径；时长 / 宽高取自 inventory.csv 直接注入，不再逐个解析文件
  · 时间：一律整数微秒 Timerange(起点, 时长)，下一段起点 = 上一段终点
  · 清场：剪映在跑就拒绝；同名草稿默认拒绝，--replace 才整目录删掉再生成
  · BGM：可多次 --bgm，依次铺满成片；歌比成片短就循环，比成片长就截断；首尾淡入淡出
  · 画面方向：orientation.json 判定整段倒装的素材，片段旋转 180°
  · 写完重新读回来自检：零缝隙零重叠、时长精确、无悬空引用、素材零复制、版本号对齐、BGM 不越界
只生成草稿，不导出成片——导出请在剪映里手动点。
"""
import argparse
import json
import os
import platform
import re
import shutil
import sys
import uuid
from collections import Counter

import pyJianYingDraft as jy
from pyJianYingDraft import Timerange, TrackSpec, TrackType

from common import DRAFTS_DIR, US, detect_versions, jianying_running, read_csv

TITLE_US = 3 * US
MIN_BGM_TAIL = 1 * US


def parse_bgm(arg):
    """'路径[:音量[:淡入淡出秒]]'；只把末尾的数字段当参数，路径里的冒号不受影响。"""
    path, gain, fade = arg, 0.3, 1.5
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


def verify(draft_dir, shots, versions, bgm_expected):
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
    audio = [s for t in d["tracks"] if t["type"] == "audio" for s in t["segments"]]
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
    ap.add_argument("--titles", action="store_true", help="每章开头加 3 秒章节标题（文字轨）")
    ap.add_argument("--replace", action="store_true", help="同名草稿已存在时整目录删除后重建")
    ap.add_argument("--extra", help=argparse.SUPPRESS)  # v2 预留：旁白 / 字幕轨
    args = ap.parse_args()
    if args.extra:
        raise NotImplementedError("旁白 / 字幕轨（--extra）留到 v2")

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
    volume = args.volume if args.volume is not None else (0.6 if bgms else 1.0)

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
        seg = jy.VideoSegment(mats[src], Timerange(int(s["start_us"]), dur),
                              source_timerange=Timerange(int(s["in_us"]), dur), volume=volume, clip_settings=cs)
        script.add_segment(seg, main_track)
    total = sum(int(s["dur_us"]) for s in shots)

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

    bgm_count = 0
    if bgms:
        bgm_track = script.append_track(TrackSpec(TrackType.audio, "BGM"))
        span = total // len(bgms)  # 多首歌平分成片，最后一首吃掉余数
        for k, b in enumerate(bgms):
            mat = jy.AudioMaterial(b["path"])
            start = k * span
            end = total if k == len(bgms) - 1 else (k + 1) * span
            segs = bgm_segments(mat.duration, start, end)
            fade = round(b["fade"] * US)
            for i, (t0, s0, d) in enumerate(segs):
                seg = jy.AudioSegment(mat, Timerange(t0, d), source_timerange=Timerange(s0, d), volume=b["gain"])
                fin = min(fade, d // 2) if i == 0 else 0
                fout = min(fade, d // 2) if i == len(segs) - 1 else 0
                if fin or fout:
                    seg.add_fade(fin, fout)
                script.add_segment(seg, bgm_track)
                bgm_count += 1

    script.save()  # 不传 inline_materials：素材只记路径

    errs, d = verify(draft_dir, shots, versions, bgm_count)
    sec = d["duration"] / US
    print(f"\n草稿：{draft_dir}")
    print(f"  {len(shots)} 个镜头 / {len(mats)} 段素材 / {len({s['chapter'] for s in shots})} 章"
          f"{' + 章节标题' if args.titles else ''}{f' + BGM {len(bgms)} 首（{bgm_count} 段）' if bgms else ''}，"
          f"总长 {int(sec // 60)}:{sec % 60:06.3f}，画布 {w}x{h}@{fps}，原声音量 {volume:g}")
    if errs:
        print("\n校验失败：")
        for e in errs:
            print("  ✗", e)
        sys.exit(1)
    print("  ✓ 零缝隙零重叠 ✓ 时长精确 ✓ 无悬空引用 ✓ 素材零复制 ✓ 版本号对齐" + (" ✓ BGM 铺满不越界" if bgms else ""))
    print("\n现在打开剪映，首页就能看到这个草稿。素材文件别移动或改名（草稿里存的是绝对路径）。")


if __name__ == "__main__":
    main()

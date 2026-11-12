# /// script
# requires-python = ">=3.10"
# dependencies = ["librosa", "numpy", "soundfile"]
# ///
"""第 5.5 步（可选）卡点：shots.csv + 几首 BGM → 切点对齐节拍的 shots.csv + bgm_plan.json

用法:
  uv run --script beatsync.py --work W --song 歌.mp3 --analyze          # 先看歌：BPM、小节、能量段落
  uv run --script beatsync.py --work W --song 歌1.mp3 --song 歌2.mp3 [--split 3] [--anchor 4:62.5]

  · 歌按 --song 顺序依次铺；--split 给出每首歌从第几章开始（章节号见 shots.csv 的 chapter 列，按成片顺序），
    不写就按各章时长就近平分。换歌点落在章节交界，再吸附到上一首歌的小节线（4 拍）上
  · --anchor 章:歌内秒 让这一章从歌的这一刻开始（吸附到小节线），用来把高潮对上音乐的高能段，可多次；
    落在一首歌的第一章时，这首歌从该处开始放（跳过前面）；否则前面的镜头按比例伸缩来凑
  · 没有 anchor 时每首歌从第一拍开始放（跳过前奏的空白）
  · 成片长度跟镜头走，不会为了放完整首歌去拉伸：最后一首歌与成片相差 15% 以内才放到歌尾，否则停在最近的小节线
    （build.py 会淡出）；歌比这段镜头短 15% 以上就报错，要多给一首歌或少留镜头
  · 每个切点吸附到最近的拍点，章节交界优先吸附到小节线，镜头至少 1.5s；有 speech.json 时，会切在话中间的切点
    改用 2s 内不切话的拍点（找不到就照旧）；镜头变长时入点不动，超出素材就把入点往前挪
  · 原 shots.csv 备份为 shots.prebeat.csv；build.py --bgm-plan W/bgm_plan.json 使用本步结果
"""
import argparse
import csv
import json
import os
import shutil
import sys

from common import US, load_json, read_csv

MIN_SHOT = int(1.5 * US)
TAIL = int(0.5 * US)      # 素材首尾不取
BAR = 4                   # 每小节拍数
FIT_TOL = 0.15            # 歌长与镜头总长相差这个比例以内才算「放得下 / 放到歌尾」
MIN_CONTRAST = 1.3        # 响小节与轻小节的能量比低于这个值，就认为整首歌没有明显起伏
SCALE_WARN = 0.3          # anchor 让镜头伸缩超过这个比例就警告
SPEECH_SHIFT = 2 * US     # 为了不切在话中间，切点最多偏离最近拍点这么多
SPEECH_TOL = int(0.2 * US)  # 句尾 0.2s 内切下去不算切断（Whisper 的句尾时间本来就不准）


def load_song(path):
    import librosa
    import numpy as np
    y, sr = librosa.load(path, sr=22050, mono=True)
    tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
    t = librosa.frames_to_time(frames, sr=sr)
    beats = [round(x * US) for x in t]
    rms = librosa.feature.rms(y=y)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    bars = beats[::BAR]
    edges = [b / US for b in bars] + [len(y) / sr]
    bar_rms = []
    for a, b in zip(edges, edges[1:]):
        inside = rms[(rms_t >= a) & (rms_t < b)]
        bar_rms.append(float(inside.mean()) if len(inside) else 0.0)
    return {"path": path, "tempo": float(np.atleast_1d(tempo)[0]), "beats": beats,
            "dur": round(len(y) / sr * US), "bars": bars, "bar_rms": bar_rms}


def energy_sections(bars, rms, dur):
    """每小节的能量 → [{start_us, end_us, level}]，level 是这首歌内部相对的 low / mid / high。
    不足 2 小节的起伏并入前一段。"""
    ranked = sorted(rms)
    p10, p90 = ranked[len(rms) // 10], ranked[min(len(rms) - 1, len(rms) * 9 // 10)]
    if p90 < p10 * MIN_CONTRAST:          # 全曲响度差不多：不要硬分出高低
        levels = ["mid"] * len(rms)
    else:
        lo, hi = p10 + (p90 - p10) / 3, p10 + (p90 - p10) * 2 / 3
        levels = ["high" if r >= hi else "low" if r <= lo else "mid" for r in rms]
    runs = []
    for i, level in enumerate(levels):
        if runs and runs[-1][1] == level:
            runs[-1][2] += 1
        else:
            runs.append([i, level, 1])
    merged = []
    for start, level, n in runs:
        if merged and (n < 2 or merged[-1][1] == level):
            merged[-1][2] += n
        else:
            merged.append([start, level, n])
    ends = [m[0] for m in merged[1:]] + [None]
    return [{"start_us": bars[s], "end_us": bars[e] if e is not None else dur, "level": level}
            for (s, level, _), e in zip(merged, ends)]


def chapter_spans(rows):
    spans = {}
    for r in rows:
        c = int(r["chapter_no"])
        s, e = int(r["start_us"]), int(r["start_us"]) + int(r["dur_us"])
        a, b = spans.get(c, (s, e))
        spans[c] = (min(a, s), max(b, e))
    return spans


def snap_cuts(cuts, grid, lo, hi, strong=(), bars=(), talking=None):
    """cuts：组内各切点（已缩放到新组长）；grid：组内可用拍点。返回吸附后的严格递增切点。
    strong 里的下标（章节交界）优先吸附到 bars（小节线）。
    talking(i, 镜头起点, 切点) 为真表示这一刀会切在第 i 个镜头的一句话中间：
    改用 SPEECH_SHIFT 内最近的不切话的拍点，找不到就仍用最近的拍点。"""
    out, prev = [], lo
    for i, t in enumerate(cuts):
        cands = [g for g in grid if prev + MIN_SHOT <= g <= hi - MIN_SHOT]
        if not cands:
            break
        if i in strong:
            cands = [g for g in bars if prev + MIN_SHOT <= g <= hi - MIN_SHOT] or cands
        cands.sort(key=lambda g: abs(g - t))
        pick = cands[0]
        if talking and talking(i, prev, pick):
            pick = next((g for g in cands if abs(g - t) <= SPEECH_SHIFT and not talking(i, prev, g)), pick)
        out.append(pick)
        prev = out[-1]
    return out


def _talking(rows, speech):
    """speech：{素材路径: [(句首微秒, 句尾微秒)]}（素材内时间）→ snap_cuts 用的 talking 函数。"""
    def f(i, start, cut):
        src = int(rows[i]["in_us"]) + cut - start
        return any(s0 < src < s1 - SPEECH_TOL for s0, s1 in speech.get(rows[i]["source"], ()))
    return f if speech else None


def music_len(want, bars, avail, last):
    """这段镜头（want 微秒）配多长的音乐。bars：相对本段起点的小节线；avail：歌还剩多长。"""
    if want > avail * (1 + FIT_TOL):
        raise ValueError(f"歌不够长：这段镜头 {want / US:.0f}s，歌只剩 {avail / US:.0f}s。多给一首歌或少留镜头")
    if last and abs(avail - want) <= want * FIT_TOL:
        return avail                      # 差不多长：放到歌尾，自然收束
    usable = [b for b in bars if 0 < b <= avail]
    return min(usable, key=lambda b: abs(b - want)) if usable else avail


def _retime_section(g_rows, old_lo, old_hi, t0, new_len, beats, bars, clip_us, speech=None):
    """把一段镜头摆到 [t0, t0+new_len)，切点吸附到 beats / bars（均为成片时间）。返回实际结束时间。"""
    scale = new_len / (old_hi - old_lo)
    old_cuts = [int(r["start_us"]) + int(r["dur_us"]) for r in g_rows][:-1]
    want = [t0 + round((c - old_lo) * scale) for c in old_cuts]
    strong = {i for i in range(len(want)) if g_rows[i]["chapter_no"] != g_rows[i + 1]["chapter_no"]}
    cuts = snap_cuts(want, [b for b in beats if t0 < b < t0 + new_len], t0, t0 + new_len, strong, bars,
                     _talking(g_rows, speech))
    if len(cuts) < len(want):
        print(f"  ⚠ 拍点不够，丢掉 {len(want) - len(cuts)} 个镜头")
        g_rows = g_rows[:len(cuts)] + [g_rows[-1]]   # 丢中间的，保住本段最后一个镜头（收尾镜头）
    prev_end = t0
    for r, b in zip(g_rows, cuts + [t0 + new_len]):
        a = prev_end                  # 上一个镜头被截短时，本镜头往前多取一点补上，下一刀仍在拍上
        d = b - a
        length = clip_us[r["source"]]
        inn = int(r["in_us"])
        if inn + d > length - TAIL:
            inn = max(TAIL, length - TAIL - d)
            d = min(d, length - TAIL - inn)
        if a + d < b:
            print(f"  ⚠ {r['name']} 素材不够长，截短 {(b - a - d) / US:.2f}s")
        prev_end = a + d
        r.update({"in_us": inn, "dur_us": d, "start_us": a})
    return g_rows, prev_end


def retime(rows, songs, starts, clip_us, anchors, gain=0.2, fade=1.5, speech=None):
    """rows（带 chapter_no）→ (卡点后的 rows, bgm 计划)。starts：每首歌从第几章开始；
    anchors：{章号: 歌内微秒}；speech：{素材路径: [(句首, 句尾)]}，切点尽量不切在话中间。
    歌不够长或 anchor 不合理时抛 ValueError。"""
    spans = chapter_spans(rows)
    n_ch = max(spans)
    ends = [s - 1 for s in starts[1:]] + [n_ch]
    out_rows, bgm, t0 = [], [], 0
    for k, (c0, c1, song) in enumerate(zip(starts, ends, songs)):
        first = song["beats"][0]
        rel = [b - first for b in song["beats"]]          # 以首拍为 0 的拍点
        rel_bars = rel[::BAR]
        tail = song["dur"] - first
        for c, t in anchors.items():
            if c0 <= c <= c1 and t < first:
                raise ValueError(f"--anchor 第 {c} 章的 {t / US:g}s 早于这首歌的首拍 {first / US:.2f}s")
        here = {c: min(rel_bars, key=lambda b: abs(b - (t - first))) for c, t in anchors.items() if c0 <= c <= c1}
        m_start = here.get(c0, 0)
        m, song_t0 = m_start, t0
        sec_starts = [c0] + sorted(c for c in here if c != c0)
        for j, sc0 in enumerate(sec_starts):
            sc1 = sec_starts[j + 1] - 1 if j + 1 < len(sec_starts) else c1
            old_lo, old_hi = spans[sc0][0], spans[sc1][1]
            if j + 1 < len(sec_starts):
                new_len = here[sec_starts[j + 1]] - m
                if new_len <= 0:
                    raise ValueError(f"--anchor 第 {sec_starts[j + 1]} 章的歌内时间不在前一段之后")
                scale = new_len / (old_hi - old_lo)
                if abs(scale - 1) > SCALE_WARN:
                    print(f"  ⚠ 为对上 anchor，第 {sc0}-{sc1} 章镜头被伸缩到 {scale:.0%}，建议调整镜头数或换个 anchor")
            else:
                new_len = music_len(old_hi - old_lo, [b - m for b in rel_bars if b > m], tail - m,
                                    last=k == len(songs) - 1)
            offset = t0 - m
            g_rows = [r for r in rows if sc0 <= int(r["chapter_no"]) <= sc1]
            placed, end = _retime_section(g_rows, old_lo, old_hi, t0, new_len,
                                          [b + offset for b in rel], [b + offset for b in rel_bars], clip_us,
                                          speech)
            out_rows += placed
            print(f"  第 {k + 1} 首 → 第 {sc0}-{sc1} 章，{(old_hi - old_lo) / US:.1f}s → {new_len / US:.1f}s，"
                  f"{len(placed)} 个镜头卡在拍上")
            if j + 1 < len(sec_starts) and end < t0 + new_len:
                print(f"  ⚠ 第 {sec_starts[j + 1]} 章没对上 anchor，提前了 {(t0 + new_len - end) / US:.1f}s（素材不够长）："
                      "换素材更长的收尾镜头，或把 anchor 提前")
            m += end - t0
            t0 = end
        bgm.append({"path": song["path"], "start_us": song_t0, "src_us": first + m_start,
                    "dur_us": t0 - song_t0, "gain": gain, "fade": fade})
    for i, r in enumerate(out_rows, 1):
        r["idx"] = i
        r.update({"in_s": round(int(r["in_us"]) / US, 3), "dur_s": round(int(r["dur_us"]) / US, 3),
                  "start_s": round(int(r["start_us"]) / US, 3)})
    return out_rows, bgm


def _parse_anchors(specs):
    out = {}
    for s in specs:
        ch, sec = s.split(":")
        out[int(ch)] = round(float(sec) * US)
    return out


def analyze(work, songs):
    report = []
    for s in songs:
        sections = energy_sections(s["bars"], s["bar_rms"], s["dur"])
        report.append({"path": s["path"], "tempo": round(s["tempo"], 1), "dur_s": round(s["dur"] / US, 1),
                       "first_beat_s": round(s["beats"][0] / US, 3),
                       "bar_s": round((s["bars"][1] - s["bars"][0]) / US, 3) if len(s["bars"]) > 1 else None,
                       "sections": [{"start_s": round(x["start_us"] / US, 1), "end_s": round(x["end_us"] / US, 1),
                                     "level": x["level"]} for x in sections]})
        print(f"{os.path.basename(s['path'])}: {s['tempo']:.1f} BPM，长 {s['dur'] / US:.1f}s")
        for x in report[-1]["sections"]:
            print(f"  {x['start_s']:>7.1f}s - {x['end_s']:>7.1f}s  {x['level']}")
    out = os.path.join(work, "bgm_analysis.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"→ {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--song", action="append", required=True)
    ap.add_argument("--analyze", action="store_true", help="只分析歌（BPM、能量段落），写 bgm_analysis.json")
    ap.add_argument("--split", default="", help="第 2、3… 首歌从第几章开始（成片顺序），如 3,5")
    ap.add_argument("--anchor", action="append", default=[], help="章:歌内秒，让这一章从歌的这一刻开始，可多次")
    ap.add_argument("--gain", type=float, default=0.2)
    ap.add_argument("--fade", type=float, default=1.5)
    args = ap.parse_args()
    W = args.work
    if os.path.exists(os.path.join(W, "narration_track.json")):
        sys.exit("这是旁白片：镜头时长由旁白决定，不能卡点。用 build.py --bgm 铺 BGM。")

    songs = [load_song(os.path.expanduser(p)) for p in args.song]
    if args.analyze:
        analyze(W, songs)
        return
    for s in songs:
        print(f"{os.path.basename(s['path'])}: {s['tempo']:.1f} BPM，{len(s['beats'])} 拍，"
              f"首拍 {s['beats'][0] / US:.2f}s，长 {s['dur'] / US:.1f}s")

    src = os.path.join(W, "shots.prebeat.csv")
    if not os.path.exists(src):
        shutil.copy(os.path.join(W, "shots.csv"), src)
    rows = read_csv(src)
    # 章节按成片顺序编号（hook 排在最前，chapter 列是 story_plan 里的序号）
    order = list(dict.fromkeys(r["chapter"] for r in rows))
    for r in rows:
        r["chapter_no"] = order.index(r["chapter"]) + 1
    n_ch = len(order)
    inv = read_csv(os.path.join(W, "inventory.csv"))
    clip_us = {r["path"]: round(float(r["duration_s"]) * US) for r in inv}
    speech = {}
    sp = os.path.join(W, "speech.json")
    if os.path.exists(sp):     # 第 3 步的转写：切点尽量不切在话中间
        said = load_json(sp, kind=dict)
        speech = {r["path"]: [(round(x["start"] * US), round(x["end"] * US)) for x in said.get(r["clip_id"], [])]
                  for r in inv}

    spans = chapter_spans(rows)
    if args.split:
        starts = [1] + [int(x) for x in args.split.split(",")]
    else:   # 按时长就近平分
        total = spans[n_ch][1]
        starts = [1]
        for k in range(1, len(songs)):
            want = total * k / len(songs)
            starts.append(min(range(2, n_ch + 1), key=lambda c: abs(spans[c][0] - want)))
    assert len(starts) == len(songs) and starts == sorted(set(starts)), f"--split 不对：{starts}"

    try:
        out_rows, bgm = retime(rows, songs, starts, clip_us, _parse_anchors(args.anchor), args.gain, args.fade,
                               speech)
    except ValueError as e:
        sys.exit(str(e))
    fields = [f for f in rows[0].keys() if f != "chapter_no"]
    with open(os.path.join(W, "shots.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)
    with open(os.path.join(W, "bgm_plan.json"), "w", encoding="utf-8") as f:
        json.dump(bgm, f, ensure_ascii=False, indent=1)
    t = int(out_rows[-1]["start_us"]) + int(out_rows[-1]["dur_us"])
    print(f"合计 {len(out_rows)} 个镜头，总长 {int(t / US // 60)}:{t / US % 60:04.1f} → shots.csv, bgm_plan.json")


if __name__ == "__main__":
    main()

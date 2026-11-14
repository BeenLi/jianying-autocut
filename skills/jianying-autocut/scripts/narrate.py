# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""后期旁白：narration_plan.json → shots.csv + narration_track.json（画面跟着旁白剪）

用法:
  uv run --script narrate.py --work W --draft [--script W/narration_script.json]   # 由转写生成初稿
  uv run --script narrate.py --work W --dry-run                                    # 看时间线和配画面
  uv run --script narrate.py --work W                                              # 落地
  可调：--lead 0.3 --head 1.0 --tail 1.5 --pause-ratio 0.6 --pause-min 0.3 --pause-max 1.2 --file-gap 1.2

时间线：
  同一文件里相邻的保留句合成一段连续音频（停顿里留着真实底噪）；停顿按比例压缩、夹在上下限之间，
  要缩短时从停顿中间剪掉一截。块的首尾向外扩到最近的静音（最多 0.3s），永不内缩，免得吃字。
  live 段插在旁白之间、前后无间隔；跨文件留 file-gap；片头 head、片尾 tail 只有画面。
"""
import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, fields

from common import US, load_json
from plan import EDGE, MIN_SHOT, fmt, load_clips, pick_one, place_pin, write_shots

RESTART_WORDS = ("重来", "不对", "再来一遍")
RETAKE_RATIO = 0.8       # 两句相似到这个程度，就当作同一句录了两遍
RETAKE_WINDOW = 3        # 只和后面这么多句比（重录总是紧挨着）
RESTART_MAX_CHARS = 8    # 「重来」类关键词出现在不超过这么多字的短句里才算口头标记
HALF_MIN_CHARS = 4       # 「重来」前一句至少这么多字，才可能是说了一半的句子（太短的什么都像）
HALF_RATIO = 0.8         # 前一句和重说那句的开头相似到这个程度，就当作说了一半
SCRIPT_RATIO = 0.6       # 转写句和稿子句相似到这个程度才算对上
SPLIT_GAIN = 0.05        # 和前一段拼起来比单独更像稿子这么多，就当作同一句被 Whisper 拆成了两段
OVERLAP_TOL = 0.3        # 相邻两句在源文件里重叠不超过这么多秒（Whisper 边界误差）仍算连续
BGM_MODES = ("up", "drop")
TALK_PENALTY = 0.5       # 素材里对镜说话的区间，挑画面时得分乘这个系数（免得画面张嘴、声音是旁白）
SUB_MAX = 16             # 每条字幕最多这么多字
SUB_BREAK = "，。！？；、,.!?;"


@dataclass
class Opts:
    lead: float = 0.3
    head: float = 1.0
    tail: float = 1.5
    pause_ratio: float = 0.6
    pause_min: float = 0.3
    pause_max: float = 1.2
    file_gap: float = 1.2
    edge_max: float = 0.3
    fade: float = 0.015


def _us(s):
    return round(float(s) * US)


def _norm(text):
    return re.sub(r"[\s，。！？、；：,.!?;:…“”\"'（）()]", "", text)


def _ratio(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


# ---------- 校验 ----------

def validate(plan, clip_durs, file_durs):
    """返回 (errs, warns)。clip_durs：{clip_id: 秒}；file_durs：{fid: 秒}（只含磁盘上存在的文件）。"""
    errs, warns = [], []
    files = plan.get("files", {})
    items, chs = plan.get("items", []), plan.get("chapters", [])
    if not isinstance(items, list) or not isinstance(chs, list) or not isinstance(files, dict):
        return ["narration_plan.json 的 items / chapters 应该是列表，files 应该是对象"], warns
    for k, c in enumerate(chs, 1):
        if not isinstance(c, dict) or not c.get("id"):
            errs.append(f"chapters 第 {k} 项缺 id")
    chapters = {c["id"] for c in chs if isinstance(c, dict) and c.get("id")}
    seen = set()
    for k, it in enumerate(items, 1):
        if not isinstance(it, dict) or not it.get("id"):
            errs.append(f"items 第 {k} 项缺 id")
            continue
        iid = it["id"]
        if iid in seen:
            errs.append(f"{iid}：id 重复")
        seen.add(iid)
        if it.get("chapter") not in chapters:
            errs.append(f"{iid}：章节 {it.get('chapter')} 没有在 chapters 里定义")
        if it.get("bgm") is not None and it["bgm"] not in BGM_MODES:
            errs.append(f"{iid}：bgm 只能是 up 或 drop，不是 {it['bgm']}")
        try:
            start, end = float(it.get("start", 0)), float(it.get("end", 0))
        except (TypeError, ValueError):
            errs.append(f"{iid}：start / end 要是秒数，现在是 {it.get('start')!r} / {it.get('end')!r}")
            continue
        if it.get("type") == "line" and not it.get("skip") and not (isinstance(it.get("text"), str) and it["text"].strip()):
            errs.append(f"{iid}：旁白句缺 text（字幕要用）")
        if it.get("type") == "line":
            fid = it.get("file")
            if fid not in files:
                errs.append(f"{iid}：旁白文件 {fid} 不在 files 里")
            elif fid not in file_durs:
                errs.append(f"{iid}：旁白文件 {files[fid]} 不存在")
            elif start >= end:
                errs.append(f"{iid}：start {start} 不早于 end {end}")
            elif end > file_durs[fid] + 0.05:
                errs.append(f"{iid}：end {end}s 超出旁白文件长度 {file_durs[fid]}s")
            for v in it.get("visuals", []):
                cid = v.get("clip_id") if isinstance(v, dict) else None
                if cid not in clip_durs:
                    errs.append(f"{iid}：素材 {cid} 不在 inventory 里")
                elif v.get("at") is not None and not isinstance(v["at"], (int, float)):
                    errs.append(f"{iid}：素材 {cid} 的 at 要是秒数，现在是 {v['at']!r}")
                elif v.get("at") is not None and not 0 <= float(v["at"]) <= clip_durs[cid]:
                    errs.append(f"{iid}：素材 {cid} 的 at={v['at']}s 超出素材长度 {clip_durs[cid]}s")
            if it.get("bgm") == "up":
                warns.append(f"{iid}：旁白句上标 bgm: up 会盖住人声，已忽略")
        elif it.get("type") == "live":
            cid = it.get("clip_id")
            if cid not in clip_durs:
                errs.append(f"{iid}：素材 {cid} 不在 inventory 里")
            elif not 0 <= start < end <= clip_durs[cid] + 0.05:
                errs.append(f"{iid}：原声段 {start}–{end}s 超出素材 {cid}（{clip_durs[cid]}s）")
        else:
            errs.append(f"{iid}：type 只能是 line 或 live")
    return errs, warns


# ---------- 重录与稿子对齐 ----------

def mark_retakes(lines):
    """没有旁白稿时找重录：返回新列表，被认定为废弃的句子加 skip / skip_reason，不改入参。"""
    out = [dict(l) for l in lines]

    def neighbour(k, step):
        j = k + step
        while 0 <= j < len(out):
            if out[j].get("file") == out[k].get("file") and not out[j].get("skip"):
                return j
            j += step
        return None

    def drop_half(k, retold):
        """「重来」前面那句如果是重说那句的开头（说了一半），也跳过。"""
        j = neighbour(k, -1)
        if j is None:
            return
        a = _norm(out[j]["text"])
        if len(a) >= HALF_MIN_CHARS and len(retold) > len(a) and _ratio(a, retold[:len(a)]) >= HALF_RATIO:
            out[j].update(skip=True, skip_reason="说了一半，后面重说了")

    for k, l in enumerate(out):
        t = _norm(l["text"])
        w = next((w for w in RESTART_WORDS if w in t), None)
        if w and t.startswith(w) and len(t) > RESTART_MAX_CHARS:
            # Whisper 把「重来，〈重说的整句〉」合成了一句：去掉开头的口头标记，保留后面的话
            rest = re.sub(rf"^[\s，。！？、,.!?]*{w}[\s，。！？、,.!?]*", "", l["text"])
            drop_half(k, _norm(rest))
            nxt = next((x for x in l.get("words") or [] if _norm(x["word"]) and _norm(x["word"]) not in w
                        and x["start"] >= l["start"]), None)
            if nxt is not None:
                l.update(start=nxt["start"], text=rest)
            else:
                l["note"] = f"开头有口头「{w}」，没有逐字时间去掉它：在页面上把 start 往后改一点"
            continue
        # 「重来」类口头标记：只认短句或出现在句尾，免得「不对劲」这种正常句子被误删
        if w and (len(t) <= RESTART_MAX_CHARS or t.endswith(w)):
            l.update(skip=True, skip_reason="口头重来")
            j = neighbour(k, 1)
            if j is not None:
                drop_half(k, _norm(out[j]["text"]))
            continue
        later = [m for m in out[k + 1:k + 1 + RETAKE_WINDOW] if m.get("file") == l.get("file")]
        if any(_ratio(l["text"], m["text"]) >= RETAKE_RATIO for m in later):
            l.update(skip=True, skip_reason="重录，取后一遍")
    return out


def align_to_script(lines, script):
    """有旁白稿时：每句转写对到最像的稿子句。同一稿子句录了几遍只留最后一遍；对不上的是口误或闲聊。
    返回 (lines, 没录到的稿子 id)。"""
    out = [dict(l) for l in lines]
    text = {s["id"]: s["text"] for s in script}
    last = {}            # 稿子 id → 最近一遍录音的句子下标（Whisper 拆开的一句有几段就有几个）
    prev = None
    for k, l in enumerate(out):
        if prev is not None and l.get("file") == out[prev].get("file"):
            sid = out[prev]["script_id"]
            group = "".join(out[j]["text"] for j in last[sid])
            if _ratio(group + l["text"], text[sid]) > _ratio(group, text[sid]) + SPLIT_GAIN \
                    and _ratio(out[prev]["text"], l["text"]) < RETAKE_RATIO:
                l["script_id"] = sid
                last[sid].append(k)
                prev = k
                continue
        best = max(script, key=lambda s: _ratio(l["text"], s["text"]), default=None)
        if best is None or _ratio(l["text"], best["text"]) < SCRIPT_RATIO:
            l.update(skip=True, skip_reason="稿外：口误或闲聊")
            continue
        l["script_id"] = best["id"]
        for j in last.get(best["id"], []):
            out[j].update(skip=True, skip_reason="重录")
        last[best["id"]] = [k]
        prev = k
    return out, [s["id"] for s in script if s["id"] not in last]


MULTI_GAIN = 0.15        # 一段转写对上连续几句稿子，比对上最像的单句至少好这么多，才按稿子切开
MULTI_MAX = 8            # 一段转写最多按几句稿子切
SAME_TEXT = 0.9          # 念的和稿子相似度低于它，在 note 里留下实际念的内容


def _split_by_script(lines, script):
    """流畅朗读时 Whisper 会把一个文件转成一整段：这段如果对上连续几句稿子，就按各句字数比例
    在逐字时间里切开，切点吸附到附近（±2 个字）停顿最长的地方。没有逐字时间的不切。"""
    out = []
    for l in lines:
        ws = l.get("words") or []
        lens = [len(_norm(w["word"])) for w in ws]
        best1 = max((_ratio(l["text"], x["text"]) for x in script), default=0)
        run = None
        if sum(lens) >= 4:
            for i in range(len(script)):
                for j in range(i + 2, min(len(script), i + MULTI_MAX) + 1):
                    r = _ratio(l["text"], "".join(x["text"] for x in script[i:j]))
                    if r >= SCRIPT_RATIO and r > best1 + MULTI_GAIN and (run is None or r > run[0]):
                        run = (r, i, j)
        if run is None:
            out.append(l)
            continue
        parts = script[run[1]:run[2]]
        if len(ws) < len(parts):              # 逐字时间太粗（一个词就是半句），切不开
            out.append(dict(l, split_fail=[x["id"] for x in parts]))
            continue
        slen = [max(1, len(_norm(x["text"]))) for x in parts]
        cum = [sum(lens[:k + 1]) for k in range(len(ws))]
        cuts, acc = [], 0
        for n in slen[:-1]:
            acc += n
            target = acc / sum(slen) * cum[-1]
            k0 = min(range(len(ws) - 1), key=lambda k: abs(cum[k] - target))
            near = [k for k in range(max(0, k0 - 2), min(len(ws) - 1, k0 + 3)) if not cuts or k > cuts[-1]]
            if not near:
                break
            cuts.append(max(near, key=lambda k: (ws[k + 1]["start"] - ws[k]["end"]) - 0.02 * abs(cum[k] - target)))
        if len(cuts) < len(parts) - 1:        # 切不出每一句：整段保留，别把两句并成一段再对到其中一句
            out.append(dict(l, split_fail=[x["id"] for x in parts]))
            continue
        a = 0
        for c in cuts + [len(ws) - 1]:
            piece = ws[a:c + 1]
            out.append(dict(l, start=piece[0]["start"], end=piece[-1]["end"],
                            text="".join(w["word"] for w in piece), words=piece))
            a = c + 1
    return out


def _apply_script(lines, script):
    """对上稿子的句子：id、文字、章节都用稿子的（页面导出时就能一一对应）；稿外的句子沿用前一句的章节，
    另编 X 开头的 id。返回 (lines, chapters)。"""
    meta = {x["id"]: x for x in script}
    first_ch = next((x["chapter"] for x in script if x.get("chapter")), None)
    cur, titles, order, extra, takes, out = first_ch or "ch1", {}, [], 0, {}, []
    for l in lines:
        sid = l.pop("script_id", None)
        fail = l.pop("split_fail", None)
        prev = out[-1] if out else None
        if (sid is not None and not l.get("skip") and prev is not None and prev["id"] == sid
                and prev.get("file") == l.get("file")):
            prev["end"] = l["end"]            # Whisper 把一句拆成了两段：并回一句（和页面一一对应）
            continue
        if sid is not None:
            x = meta[sid]
            cur = x.get("chapter") or cur
            if x.get("chapter_title") and cur not in titles:
                titles[cur] = x["chapter_title"]
            if l.get("skip"):                     # 被替掉的那几遍：留着可恢复，id 加后缀
                takes[sid] = takes.get(sid, 0) + 1
                l["id"] = f"{sid}-{takes[sid]}"
            else:
                l["id"] = sid
                if _ratio(l["text"], x["text"]) < SAME_TEXT:
                    l["note"] = f"转写和稿子差得较多（可能是同音字，也可能念得不一样）：{l['text']}。字幕用稿子，念的不一样就改 text"
                l["text"] = x["text"]
        else:
            extra += 1
            l["id"] = f"X{extra:02d}"
        if fail:
            l["note"] = (f"这段连着念了稿子 {'、'.join(fail)} 几句，逐字时间太粗没切开，时间按整段算；"
                         "需要的话手动拆成几句。" + (" " + l["note"] if l.get("note") else ""))
        l["chapter"] = cur
        if cur not in order:
            order.append(cur)
        out.append(l)
    default = "旁白" if first_ch is None else None
    return out, [{"id": c, "title": titles.get(c, default or c)} for c in order]


def draft_plan(speech, script=None):
    """narration_speech.json → narration_plan.json 初稿（visuals 留空，等 Claude 配画面）。"""
    lines = []
    for fid in sorted(speech["files"], key=lambda f: int(f[1:])):
        for l in speech["lines"].get(fid, []):
            lines.append({"type": "line", "chapter": "ch1", "file": fid, "start": l["start"], "end": l["end"],
                          "text": l["text"], "visuals": [], "words": l.get("words", [])})
    missing, chapters = [], [{"id": "ch1", "title": "旁白"}]
    if script:
        lines, missing = align_to_script(_split_by_script(lines, script), script)
        lines, chapters = _apply_script(lines, script)
    else:
        lines = mark_retakes(lines)
        for k, l in enumerate(lines, 1):
            l["id"] = f"L{k:02d}"
    for l in lines:
        l.pop("words", None)            # 逐字时间只给找重录用，不进 plan
    plan = {"files": dict(speech["files"]), "chapters": chapters,
            "items": [{"id": l.pop("id"), **l} for l in lines]}
    if missing:
        plan["missing_script"] = missing
    return plan


# ---------- 时间线 ----------

def _expand_start(s, sil, o):
    ends = [b for _, b in sil if b <= s]
    return max(s - o, max(ends, default=0), 0)


def _expand_end(e, sil, o, dur):
    starts = [a for a, _ in sil if a >= e]
    return min(e + o, min(starts, default=dur), dur)


def timeline(plan, silences, file_durs, opts):
    """排旁白在成片里的位置。返回 {"audio": [...], "marks": [...], "total_us"}，全部整数微秒。
    marks：line → {item, mouth_us, close_us}；live → {item, live: True, start_us, end_us}。"""
    o = opts
    sil = {f: [(_us(a), _us(b)) for a, b in v] for f, v in silences.items()}
    durs = {f: _us(d) for f, d in file_durs.items()}
    fade, edge = _us(o.fade), _us(o.edge_max)
    audio, marks = [], []
    cursor = _us(o.head)
    seg = None            # 当前音频段：{fid, src_us, start_us}，结束于 prev 之后
    prev = None           # 上一个保留的 line（同块判断用）
    skipped_since = []    # prev 之后被 skip 的同文件句子
    last_kind = None

    def close_block():
        nonlocal seg
        if seg is None:
            return
        fid = seg["fid"]
        end = _expand_end(_us(prev["end"]), sil.get(fid, []), edge, durs[fid])
        _emit(end)
        seg = None

    def _emit(src_end):
        nonlocal cursor
        d = src_end - seg["src_us"]
        if d <= 0:
            raise ValueError(f"旁白时间线算出了 {d / US:.2f}s 的音频段（{seg['fid']} @ {seg['src_us'] / US:.2f}s），"
                             "检查 narration_plan.json 里这附近句子的 start / end 和顺序")
        audio.append({"fid": seg["fid"], "src_us": seg["src_us"], "start_us": seg["start_us"], "dur_us": d,
                      "fade_in_us": fade, "fade_out_us": fade})
        cursor = seg["start_us"] + d

    for it in plan["items"]:
        if it.get("skip"):
            # 只有源时间夹在上一句之后的跳过句才需要剪掉；挪到别处的跳过句与这一段音频无关
            if it.get("type") == "line" and prev is not None and it.get("file") == prev["file"] \
                    and _us(it["start"]) >= _us(prev["end"]):
                skipped_since.append(it)
            continue
        if it["type"] == "live":
            close_block()
            prev, skipped_since = None, []
            d = _us(it["end"]) - _us(it["start"])
            marks.append({"item": it["id"], "live": True, "start_us": cursor, "end_us": cursor + d})
            cursor += d
            last_kind = "live"
            continue
        fid, s, e = it["file"], _us(it["start"]), _us(it["end"])
        same = prev is not None and fid == prev["file"] and s >= _us(prev["end"]) - _us(OVERLAP_TOL)
        if same:
            skipped_since = [k for k in skipped_since if _us(k["end"]) <= s]
            pe = _us(prev["end"])
            p = max(0, s - pe)
            if skipped_since:
                p = max(0, min(_us(skipped_since[0]["start"]) - pe, s - _us(skipped_since[-1]["end"])))
            if prev.get("pause_after") is not None:
                pp = _us(prev["pause_after"])
            else:
                pp = min(p, min(max(round(p * o.pause_ratio), _us(o.pause_min)), _us(o.pause_max)))
            if pp != p or skipped_since:
                q = min(pp, p)              # 只能剪短停顿；pause_after 要求更长时，补的是空白
                _emit(pe + q // 2)
                cursor += pp - q
                seg = {"fid": fid, "src_us": s - (q - q // 2), "start_us": cursor}
        else:
            close_block()
            if last_kind == "line":
                cursor += _us(o.file_gap)
            src = _expand_start(s, sil.get(fid, []), edge)
            seg = {"fid": fid, "src_us": src, "start_us": cursor}
        mouth = seg["start_us"] + (s - seg["src_us"])
        marks.append({"item": it["id"], "mouth_us": mouth, "close_us": mouth + (e - s)})
        prev, skipped_since, last_kind = it, [], "line"
    close_block()
    return {"audio": audio, "marks": marks, "total_us": cursor + _us(o.tail)}


# ---------- 画面槽 ----------

def slots(tl, plan, opts):
    """每个保留项一个槽，首尾相接覆盖 [0, total_us)。line 的槽从「开口 − lead」开始（J-cut），
    但不早于前一个 live 的结束；live 的槽就是它自己。第一个槽从 0 开始，最后一个到 total_us。"""
    marks = tl["marks"]
    starts = []
    for k, m in enumerate(marks):
        if k == 0:
            starts.append(0)
        elif m.get("live"):
            starts.append(m["start_us"])
        elif marks[k - 1].get("live"):
            starts.append(marks[k - 1]["end_us"])
        else:
            starts.append(max(m["mouth_us"] - round(opts.lead * US), starts[-1]))
    ends = starts[1:] + [tl["total_us"]]
    return [{"item": m["item"], "start_us": a, "end_us": b, "live": bool(m.get("live"))}
            for m, a, b in zip(marks, starts, ends)]


# ---------- 铺画面 ----------

class _Penalty:
    """临时给素材里对镜说话的帧降权，退出时恢复。"""

    def __init__(self, clip, speech):
        self.clip, self.spans = clip, [(round(l["start"] * US), round(l["end"] * US)) for l in speech or []]

    def __enter__(self):
        self.orig = self.clip.frames
        if self.spans:
            self.clip.frames = [(t, s * TALK_PENALTY if any(a <= t <= b for a, b in self.spans) else s, bad)
                                for t, s, bad in self.orig]

    def __exit__(self, *exc):
        self.clip.frames = self.orig


def _try_place(c, at, d, speech):
    """在素材 c 里放一个长 d 的镜头：有 at 以它为中心，没有就取得分最高的窗口。成功则占用并返回 (a, score)。"""
    with _Penalty(c, speech.get(c.clip_id)):
        if at is not None:
            w = place_pin(c, round(float(at) * US), d)
            if not w or w[1] != d:
                return None
            a = w[0]
        else:
            w = c.best_window(d)
            if not w:
                return None
            a = w[0]
        score = c.window_score(a, d)
    c.used.append((a, a + d))
    return a, round(score or 0, 3)


def _place_in_free_segment(c, d):
    """把长 d 的镜头放进素材 c 最长的空闲段（居中）。空闲段起点常不在 STEP 网格上，best_window 会错过它。"""
    segs, cur = [], EDGE
    for u0, u1 in sorted(c.used):
        segs.append((cur, u0 - c.gap - cur))
        cur = u1 + c.gap
    segs.append((cur, c.dur - EDGE - cur))
    a, length = max(segs, key=lambda x: x[1])
    if length < d:
        return None
    a += (length - d) // 2
    score = c.window_score(a, d)
    if score is None or not c.free(a, d):
        return None
    c.used.append((a, a + d))
    return a, round(score, 3)


def _place_any(cands, clips, avoid, remaining, speech, partial, last=False):
    """按顺序在候选画面里放一个镜头。partial=False 要整块盖住 remaining；partial=True 取素材里最长的空闲段
    （至少 MIN_SHOT）。last=True（本槽最后一块）时不留不足 MIN_SHOT 的零头：零头没有下一块可挪。
    返回镜头 dict，放不下返回 None。"""
    for v in cands:
        c = clips.get(v["clip_id"])
        if c is None or c.clip_id in avoid:
            continue
        d = remaining
        if partial:
            d = min(c.longest_free(), remaining)
            if last and 0 < remaining - d < MIN_SHOT:
                d = remaining - MIN_SHOT
            if d < MIN_SHOT:
                continue
        w = _try_place(c, v.get("at"), d, speech)
        if not w and partial:
            w = _place_in_free_segment(c, d)          # 以 at 为中心 / 网格上都放不下：直接放进最长的空闲段
        if w:
            return {"kind": "narr", "clip": c, "in_us": w[0], "dur_us": d, "score": w[1]}
    return None


def _extend(shot, extra, head=False):
    """把镜头延长 extra（head=True 时入点往前挪，出点不动）；素材不够长、碰到坏帧或别的占用就返回 False。
    extra 为负就是剪短（总是可行，只要剩下的不短于 0）。"""
    c, a, d = shot["clip"], shot["in_us"], shot["dur_us"]
    na, nd = (a - extra if head else a), d + extra
    c.used.remove((a, a + d))
    ok = nd > 0 and EDGE <= na and na + nd <= c.dur - EDGE and c.free(na, nd) and c.window_score(na, nd) is not None
    c.used.append((na, na + nd) if ok else (a, a + d))
    if ok:
        shot["in_us"], shot["dur_us"] = na, nd
    return ok


def split_sub(text, start_us, dur_us, max_chars=SUB_MAX):
    """长句按标点拆成每条不超过 max_chars 字的字幕，时长按字数分。"""
    parts, cur = [], ""
    for ch in text:
        cur += ch
        if ch in SUB_BREAK:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    merged = []
    for p in parts:
        while len(p) > max_chars:
            merged.append(p[:max_chars])
            p = p[max_chars:]
        if merged and len(merged[-1]) + len(p) <= max_chars:
            merged[-1] += p
        elif p:
            merged.append(p)
    total = sum(len(p) for p in merged) or 1
    out, t = [], start_us
    for k, p in enumerate(merged):
        d = start_us + dur_us - t if k == len(merged) - 1 else dur_us * len(p) // total
        out.append((t, d, p))
        t += d
    return out


def layout(plan, clips, speech, silences, file_durs, opts):
    """narration_plan → (shots 行, narration_track, 报告)。不读写文件、不用随机数；会占用 clips 的 used。"""
    tl = timeline(plan, silences, file_durs, opts)
    sl = slots(tl, plan, opts)
    items = {it["id"]: it for it in plan["items"]}
    marks = {m["item"]: m for m in tl["marks"]}
    chapters = plan["chapters"]
    ch_no = {c["id"]: k for k, c in enumerate(chapters, 1)}
    ch_title = {c["id"]: c.get("title", c["id"]) for c in chapters}
    report = {"fallback": [], "unpaired": [], "skipped": [], "warns": [], "items": []}
    for it in plan["items"]:
        if it.get("skip"):
            report["skipped"].append((it["id"], it.get("skip_reason", "")))
    for c in clips.values():
        c.silences = []                       # 旁白下的原声只是垫底，静音吸附没意义
    pool = {}                                 # 章节 → 本章出现过的素材
    for it in plan["items"]:
        if it.get("skip"):
            continue
        ids = [it["clip_id"]] if it["type"] == "live" else [v["clip_id"] for v in it.get("visuals", [])]
        pool.setdefault(it["chapter"], [])
        pool[it["chapter"]] += [c for c in ids if c in clips and c not in pool[it["chapter"]]]

    shots = {}                                # 槽序号 → [shot]
    # 1. 先放 live：画面严格取 [start, end]，片头 / 片尾的槽向外延伸
    for k, s in enumerate(sl):
        if not s["live"]:
            continue
        it, m = items[s["item"]], marks[s["item"]]
        c = clips[it["clip_id"]]
        a = round(it["start"] * US) - (m["start_us"] - s["start_us"])
        d = s["end_us"] - s["start_us"]
        if a < 0:
            raise ValueError(f"{it['id']}：原声段在片头，素材 {c.clip_id} 在 {it['start']}s 之前不够放片头："
                             f"把 --head 调到 {max(0.0, it['start'] - (m['start_us'] - s['start_us'] - opts.head * US) / US):.1f} 以下（或 --head 0）")
        if a + d > c.dur:
            raise ValueError(f"{it['id']}：原声段在片尾，素材 {c.clip_id} 在 {it['end']}s 之后不够放片尾："
                             f"把 --tail 调到 {max(0.0, (c.dur - round(it['end'] * US)) / US):.1f} 以下")
        c.used.append((a, a + d))
        if c.window_score(a, d) is None:
            report["warns"].append(f"{it['id']}：原声段 {c.clip_id} 里有坏帧（按你给的范围保留）")
        shots[k] = [{"kind": "live", "clip": c, "in_us": a, "dur_us": d, "score": round(c.window_score(a, d) or 0, 3)}]

    # 2. 再按成片顺序给 line 铺画面
    line_slots = [k for k, s in enumerate(sl) if not s["live"]]
    prev_shot = None
    for k, s in enumerate(sl):
        if s["live"]:
            prev_shot = shots[k][-1]
            continue
        it = items[s["item"]]
        L = s["end_us"] - s["start_us"]
        vis = it.get("visuals", [])
        # 紧跟着的原声段用的素材：这一槽的最后一个镜头不能是它，否则同一素材前后相邻
        next_live = items[sl[k + 1]["item"]]["clip_id"] if k + 1 < len(sl) and sl[k + 1]["live"] else None
        if prev_shot is not None and (L < MIN_SHOT or not vis):
            if not vis:
                report["unpaired"].append(it["id"])
            # 原声段的画面就是用户给的那段声音，不能延长（会把范围外的原声以人声音量带进旁白）
            if prev_shot["kind"] != "live" and prev_shot["clip"].clip_id != next_live and _extend(prev_shot, L):
                continue
        j = line_slots.index(k)
        # 借来的画面不带原句的 at：那一刻是原句自己要用的，借用只取素材里还空着的地方
        neighbours = [{"clip_id": v["clip_id"]} for jj in (j - 1, j + 1) if 0 <= jj < len(line_slots)
                      for v in items[sl[line_slots[jj]]["item"]].get("visuals", [])]
        n = max(1, min(len(vis), L // MIN_SHOT)) if vis else 1
        pieces = [L // n] * (n - 1) + [L - L // n * (n - 1)]
        got = []
        for i, d in enumerate(pieces):
            remaining = d
            while remaining > 0:
                last = (got[-1] if got else prev_shot)
                avoid = {last["clip"].clip_id} if last else set()
                if i == len(pieces) - 1 and next_live:
                    avoid.add(next_live)
                own = ([vis[i]] if i < len(vis) else []) + [v for v in vis if v is not (vis[i] if i < len(vis) else None)]
                others = [clips[c] for c in pool.get(it["chapter"], []) if c not in avoid]
                # 先找能整块盖住的；素材都比这块短时，放得下多少放多少，剩下的交给下一个候选。
                # 本块指定的画面最优先，其次本句别的画面，最后才是借来的（相邻句的画面、本章出现过的素材）
                tail = i == len(pieces) - 1

                def place(rem, avoid=avoid, own=own, others=others, tail=tail):
                    p_ = (_place_any(own[:1], clips, avoid, rem, speech, False)
                          or _place_any(own[:1], clips, avoid, rem, speech, True, tail)
                          or _place_any(own[1:], clips, avoid, rem, speech, False)
                          or _place_any(own[1:], clips, avoid, rem, speech, True, tail)
                          or _place_any(neighbours, clips, avoid, rem, speech, False))
                    pool_ = [c for c in others if c.clip_id not in avoid]
                    if p_ is None:
                        with _Penalties(pool_, speech):
                            p_ = pick_one(pool_, rem, "narr")
                        if p_ is not None:
                            p_["kind"] = "narr"
                    return p_ or _place_any(neighbours + [{"clip_id": c.clip_id} for c in pool_],
                                            clips, avoid, rem, speech, True, tail)
                placed = place(remaining)
                if placed is None:
                    raise ValueError(f"章节 {it['chapter']}（{it['id']}）没有可用的素材来铺这句旁白："
                                     f"本句和相邻句的画面都被占用或不够 {MIN_SHOT / US:g}s，给这句多配一两个画面")
                if placed["clip"].clip_id not in {v["clip_id"] for v in own}:
                    report["fallback"].append((it["id"], placed["clip"].clip_id))
                got.append(placed)
                remaining -= placed["dur_us"]
                if 0 < remaining < MIN_SHOT:
                    # 零头不单独成镜头：并进本槽里能延长的镜头（往后延长，或入点往前挪），
                    # 并不进去就挪给下一块；最后一块就把刚放的镜头剪短，凑出一个够 MIN_SHOT 的镜头
                    if any(_extend(g, remaining) for g in reversed(got)) or \
                            any(_extend(g, remaining, head=True) for g in reversed(got)):
                        remaining = 0
                    elif i + 1 < len(pieces):
                        pieces[i + 1] += remaining
                        remaining = 0
                    else:
                        cut = MIN_SHOT - remaining
                        if placed["dur_us"] - cut >= MIN_SHOT and _extend(placed, -cut):
                            nxt = place(MIN_SHOT, avoid={placed["clip"].clip_id} | ({next_live} if next_live else set()))
                            if nxt is not None:
                                if nxt["clip"].clip_id not in {v["clip_id"] for v in own}:
                                    report["fallback"].append((it["id"], nxt["clip"].clip_id))
                                got.append(nxt)
                                remaining = 0
                            else:
                                _extend(placed, cut)       # 放不进去：恢复原样，留给下一轮
        if any(g["dur_us"] < MIN_SHOT for g in got):
            report["warns"].append(f"{it['id']}：有个镜头不到 {MIN_SHOT / US:g}s（本句和相邻句的素材都凑不出更长的），"
                                   "给这句多配一个画面，或在剪映里手动调")
        shots[k] = got
        prev_shot = got[-1]

    # 3. 输出
    rows, t = [], 0
    for k, s in enumerate(sl):
        it = items[s["item"]]
        report["items"].append({"item": it["id"], "start_us": s["start_us"], "end_us": s["end_us"],
                                "text": it.get("text", it.get("reason", "")), "live": s["live"],
                                "shots": [(sh["clip"].clip_id, sh["in_us"], sh["dur_us"]) for sh in shots.get(k, [])]})
        for sh in shots.get(k, []):
            c = sh["clip"]
            rows.append({"idx": len(rows) + 1, "chapter": ch_no[it["chapter"]], "chapter_title": ch_title[it["chapter"]],
                         "chapter_function": "", "kind": sh["kind"], "name": c.name, "source": c.path,
                         "in_s": round(sh["in_us"] / US, 3), "dur_s": round(sh["dur_us"] / US, 3),
                         "start_s": round(t / US, 3), "in_us": sh["in_us"], "dur_us": sh["dur_us"],
                         "start_us": t, "score": sh["score"]})
            t += sh["dur_us"]
    track = {"audio": [dict(a, file=plan["files"][a["fid"]]) for a in tl["audio"]],
             "subs": [], "speech": [], "live": [], "bgm": [], "total_us": tl["total_us"]}
    for s in sl:
        it, m = items[s["item"]], marks[s["item"]]
        if s["live"]:
            src0 = round(it["start"] * US) - (m["start_us"] - s["start_us"])
            track["live"].append({"start_us": s["start_us"], "dur_us": s["end_us"] - s["start_us"],
                                  "clip_id": it["clip_id"], "src_us": src0})
            for l in speech.get(it["clip_id"], []):
                a, b = max(round(l["start"] * US), src0), min(round(l["end"] * US), src0 + s["end_us"] - s["start_us"])
                if b > a:
                    track["speech"].append([s["start_us"] + a - src0, b - a])
        else:
            dur = m["close_us"] - m["mouth_us"]
            track["speech"].append([m["mouth_us"], dur])
            track["subs"] += [{"start_us": a, "dur_us": d, "text": x} for a, d, x in split_sub(it["text"], m["mouth_us"], dur)]
        mode = it.get("bgm")
        if mode == "up" and s["live"] and any(a + d > s["start_us"] and a < s["end_us"] for a, d in track["speech"]):
            report["warns"].append(f"{it['id']}：原声段里有人说话，标 bgm: up 会把人声盖住，已忽略")
            mode = None
        if mode == "drop" or (mode == "up" and s["live"]):
            track["bgm"].append({"start_us": s["start_us"], "dur_us": s["end_us"] - s["start_us"], "mode": mode})
    return rows, track, report


class _Penalties:
    def __init__(self, clips, speech):
        self.ps = [_Penalty(c, speech.get(c.clip_id)) for c in clips]

    def __enter__(self):
        for p in self.ps:
            p.__enter__()

    def __exit__(self, *exc):
        for p in self.ps:
            p.__exit__()


# ---------- CLI ----------

def _load(path, default=None):
    return load_json(path, default=default)


def note_at(notes, cid, t_s):
    """scene_notes.json 里素材 cid 在 t_s 秒处的画面描述。"""
    for n in notes.get(cid, []):
        if n.get("start", 0) <= t_s <= n.get("end", 0):
            return n.get("description", "")
    return ""


def _print_report(plan, rows, track, report, notes):
    items = {it["id"]: it for it in plan["items"]}
    print(f"成片 {fmt(track['total_us'])}，{len(rows)} 个镜头，旁白 {len(track['audio'])} 段，原声段 {len(track['live'])} 个")
    for e in report["items"]:
        tag = "原声" if e["live"] else "旁白"
        print(f"  {fmt(e['start_us'])}–{fmt(e['end_us'])} {e['item']} {tag}「{e['text'][:24]}」")
        if not e["live"] and not e["shots"]:
            print("      （延续上一镜头）")
        for cid, a, d in e["shots"]:
            print(f"      {cid}@{a / US:.1f}s +{d / US:.1f}s  {note_at(notes, cid, (a + d / 2) / US)[:30]}")
    for iid, why in report["skipped"]:
        print(f"  跳过 {iid}「{items[iid].get('text', '')[:20]}」：{why}")
    for iid, cid in report["fallback"]:
        print(f"  ⚠ {iid} 没配到你指定的画面，用了 {cid}")
    if report["unpaired"]:
        print(f"  ⚠ 没配画面、延续上一个镜头的句子：{'、'.join(report['unpaired'])}")
    for w in report["warns"]:
        print(f"  ⚠ {w}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--draft", action="store_true", help="由 narration_speech.json 生成 narration_plan.json 初稿")
    ap.add_argument("--script", help="旁白稿 [{id, text}]（--draft 时用来对齐、挑重录）")
    ap.add_argument("--force", action="store_true", help="--draft 时覆盖已有的 narration_plan.json")
    ap.add_argument("--dry-run", action="store_true")
    for f in fields(Opts):
        if f.name not in ("edge_max", "fade"):
            ap.add_argument("--" + f.name.replace("_", "-"), type=float, default=f.default)
    args = ap.parse_args(argv)
    W = args.work
    speech_vo = _load(os.path.join(W, "narration_speech.json"))
    if speech_vo is None:
        print(f"{W}/narration_speech.json 不存在：先跑 transcribe.py --narration", file=sys.stderr)
        return 1
    plan_path = os.path.join(W, "narration_plan.json")
    if args.draft:
        if os.path.exists(plan_path) and not args.force:
            print(f"{plan_path} 已存在；要重新生成加 --force", file=sys.stderr)
            return 1
        draft = draft_plan(speech_vo, _load(args.script) if args.script else None)
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=1)
        skipped = sum(bool(i.get("skip")) for i in draft["items"])
        print(f"初稿 {len(draft['items'])} 句，其中 {skipped} 句默认跳过 → {plan_path}")
        return 0
    plan = _load(plan_path)
    if plan is None:
        print(f"{plan_path} 不存在：先跑 --draft", file=sys.stderr)
        return 1
    clips, _ = load_clips(W)
    file_durs = {fid: speech_vo["durations"][fid] for fid, p in plan.get("files", {}).items()
                 if os.path.exists(p) and fid in speech_vo.get("durations", {})}
    errs, warns = validate(plan, {cid: c.dur / US for cid, c in clips.items()}, file_durs)
    if errs:
        print("narration_plan.json 有问题：\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    opts = Opts(**{f.name: getattr(args, f.name) for f in fields(Opts) if hasattr(args, f.name)})
    speech = _load(os.path.join(W, "speech.json"), {})
    try:
        rows, track, report = layout(plan, clips, speech, speech_vo.get("silences", {}), file_durs, opts)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    report["warns"] = warns + report["warns"]
    notes = _load(os.path.join(W, "scene_notes.json"), {}) or {}
    _print_report(plan, rows, track, report, notes)
    if args.dry_run:
        print("（dry-run，没写文件）")
        return 0
    out = write_shots(W, rows)
    with open(os.path.join(W, "narration_track.json"), "w", encoding="utf-8") as f:
        json.dump(track, f, ensure_ascii=False, indent=1)
    print(f"→ {out}\n→ {os.path.join(W, 'narration_track.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

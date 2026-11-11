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

from common import US
from plan import EDGE, FIELDS, MIN_SHOT, fmt, load_clips, pick_one, place_pin, write_shots

RESTART_WORDS = ("重来", "不对", "再来一遍")
RETAKE_RATIO = 0.8       # 两句相似到这个程度，就当作同一句录了两遍
RETAKE_WINDOW = 3        # 只和后面这么多句比（重录总是紧挨着）
RESTART_MAX_CHARS = 8    # 「重来」类关键词出现在不超过这么多字的短句里才算口头标记
SCRIPT_RATIO = 0.6       # 转写句和稿子句相似到这个程度才算对上
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
    chapters = {c["id"] for c in plan.get("chapters", [])}
    seen = set()
    for it in plan.get("items", []):
        iid = it.get("id", "?")
        if iid in seen:
            errs.append(f"{iid}：id 重复")
        seen.add(iid)
        if it.get("chapter") not in chapters:
            errs.append(f"{iid}：章节 {it.get('chapter')} 没有在 chapters 里定义")
        if it.get("bgm") is not None and it["bgm"] not in BGM_MODES:
            errs.append(f"{iid}：bgm 只能是 up 或 drop，不是 {it['bgm']}")
        start, end = float(it.get("start", 0)), float(it.get("end", 0))
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
                cid = v.get("clip_id")
                if cid not in clip_durs:
                    errs.append(f"{iid}：素材 {cid} 不在 inventory 里")
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
    for k, l in enumerate(out):
        t = _norm(l["text"])
        # 「重来」类口头标记：只认短句或出现在句首 / 句尾，免得「不对劲」这种正常句子被误删
        if any(w in t and (len(t) <= RESTART_MAX_CHARS or t.startswith(w) or t.endswith(w)) for w in RESTART_WORDS):
            l.update(skip=True, skip_reason="口头重来")
            continue
        later = [m for m in out[k + 1:k + 1 + RETAKE_WINDOW] if m.get("file") == l.get("file")]
        if any(_ratio(l["text"], m["text"]) >= RETAKE_RATIO for m in later):
            l.update(skip=True, skip_reason="重录，取后一遍")
    return out


def align_to_script(lines, script):
    """有旁白稿时：每句转写对到最像的稿子句。同一稿子句录了几遍只留最后一遍；对不上的是口误或闲聊。
    返回 (lines, 没录到的稿子 id)。"""
    out = [dict(l) for l in lines]
    last = {}
    for k, l in enumerate(out):
        best = max(script, key=lambda s: _ratio(l["text"], s["text"]), default=None)
        if best is None or _ratio(l["text"], best["text"]) < SCRIPT_RATIO:
            l.update(skip=True, skip_reason="稿外：口误或闲聊")
            continue
        l["script_id"] = best["id"]
        if best["id"] in last:
            out[last[best["id"]]].update(skip=True, skip_reason="重录")
        last[best["id"]] = k
    return out, [s["id"] for s in script if s["id"] not in last]


def draft_plan(speech, script=None):
    """narration_speech.json → narration_plan.json 初稿（visuals 留空，等 Claude 配画面）。"""
    lines = []
    for fid in sorted(speech["files"], key=lambda f: int(f[1:])):
        for l in speech["lines"].get(fid, []):
            lines.append({"type": "line", "chapter": "ch1", "file": fid, "start": l["start"], "end": l["end"],
                          "text": l["text"], "visuals": []})
    missing = []
    if script:
        lines, missing = align_to_script(lines, script)
    else:
        lines = mark_retakes(lines)
    plan = {"files": dict(speech["files"]), "chapters": [{"id": "ch1", "title": "旁白"}],
            "items": [{"id": f"L{k:02d}", **l} for k, l in enumerate(lines, 1)]}
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
        nonlocal seg, cursor
        if seg is None:
            return
        fid = seg["fid"]
        end = _expand_end(_us(prev["end"]), sil.get(fid, []), edge, durs[fid])
        _emit(end)
        seg = None

    def _emit(src_end):
        nonlocal cursor
        d = src_end - seg["src_us"]
        audio.append({"fid": seg["fid"], "src_us": seg["src_us"], "start_us": seg["start_us"], "dur_us": d,
                      "fade_in_us": fade, "fade_out_us": fade})
        cursor = seg["start_us"] + d

    for it in plan["items"]:
        if it.get("skip"):
            if it.get("type") == "line" and prev is not None and it.get("file") == prev["file"]:
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
        same = prev is not None and fid == prev["file"] and s >= _us(prev["end"])
        if same:
            pe = _us(prev["end"])
            p = s - pe
            if skipped_since:
                p = min(_us(skipped_since[0]["start"]) - pe, s - _us(skipped_since[-1]["end"]))
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


def _extend(shot, extra):
    """把上一个镜头往后延长 extra；素材不够长、碰到坏帧或别的占用就返回 False。"""
    c, a, d = shot["clip"], shot["in_us"], shot["dur_us"]
    nd = d + extra
    c.used.remove((a, a + d))
    ok = a + nd <= c.dur - EDGE and c.free(a, nd) and c.window_score(a, nd) is not None
    c.used.append((a, a + (nd if ok else d)))
    if ok:
        shot["dur_us"] = nd
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
        if a < 0 or a + d > c.dur:
            raise ValueError(f"{it['id']}：原声段所在素材 {c.clip_id} 不够长，放不下片头 / 片尾")
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
        if prev_shot is not None and (L < MIN_SHOT or not vis):
            if not vis:
                report["unpaired"].append(it["id"])
            if _extend(prev_shot, L):
                continue
        j = line_slots.index(k)
        neighbours = [v for jj in (j - 1, j + 1) if 0 <= jj < len(line_slots)
                      for v in items[sl[line_slots[jj]]["item"]].get("visuals", [])]
        n = max(1, min(len(vis), L // MIN_SHOT)) if vis else 1
        pieces = [L // n] * (n - 1) + [L - L // n * (n - 1)]
        got = []
        for i, d in enumerate(pieces):
            remaining = d
            while remaining > 0:
                last = (got[-1] if got else prev_shot)
                avoid = last["clip"].clip_id if last else None
                cands = ([vis[i]] if i < len(vis) else []) + [v for v in vis if v is not (vis[i] if i < len(vis) else None)] \
                    + neighbours
                placed = None
                for v in cands:
                    c = clips.get(v["clip_id"])
                    if c is None or c.clip_id == avoid:
                        continue
                    w = _try_place(c, v.get("at"), remaining, speech)
                    if w:
                        placed = {"kind": "narr", "clip": c, "in_us": w[0], "dur_us": remaining, "score": w[1]}
                        if v not in vis:
                            report["fallback"].append((it["id"], c.clip_id))
                        break
                if placed is None:
                    others = [clips[c] for c in pool.get(it["chapter"], []) if c != avoid]
                    with _Penalties(others, speech):
                        shot = pick_one(others, remaining, "narr")
                    if shot is None:
                        raise ValueError(f"章节 {it['chapter']}（{it['id']}）没有可用的素材来铺这句旁白")
                    shot["kind"] = "narr"
                    placed = shot
                    report["fallback"].append((it["id"], shot["clip"].clip_id))
                got.append(placed)
                remaining -= placed["dur_us"]
                if 0 < remaining < MIN_SHOT and _extend(placed, remaining):
                    remaining = 0
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
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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

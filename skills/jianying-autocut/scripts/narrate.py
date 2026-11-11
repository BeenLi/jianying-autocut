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
import difflib
import re
from dataclasses import dataclass

from common import US

RESTART_WORDS = ("重来", "不对", "再来一遍")
RETAKE_RATIO = 0.8       # 两句相似到这个程度，就当作同一句录了两遍
RETAKE_WINDOW = 3        # 只和后面这么多句比（重录总是紧挨着）
RESTART_MAX_CHARS = 8    # 「重来」类关键词出现在不超过这么多字的短句里才算口头标记
SCRIPT_RATIO = 0.6       # 转写句和稿子句相似到这个程度才算对上
BGM_MODES = ("up", "drop")


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

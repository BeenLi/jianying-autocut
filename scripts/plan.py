# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""第 5 步 分镜规划：story_plan.json + 节奏规则 → shots.csv

用法:
  uv run --script plan.py --work W --target 10:00 --dry-run   # 先看方案
  uv run --script plan.py --work W --target 10:00             # 确认后落地

章节、章节里能用哪些素材、必须出现的瞬间（pins）都来自 story_plan.json；
本步只负责「每章分多少时长、每个镜头从哪段素材的哪里取」：
  配额   有 share 的章节按比例拿；其余每章保底 20s，剩下按 √可用时长注水分配
  节奏   长 12-18s 压场 / 短 3-6s / 短 / 中 6-9s 循环，平均 ≈ 7.9s
  pins   先放：以该瞬间为中心取一个镜头，避开坏帧
  挑选   其余镜头在章内素材里找得分最高、不含坏帧的窗口；同素材复用降权、区间不重叠
  静音   入点 1.5s 内有静音段就把镜头整体挪过去，少切在半句话上（不再判断有没有人说话）
  交替   章节带 intercut 时做平行蒙太奇：两条线（a / b）轮流出镜头，各线内按拍摄时间，最后落在 end_on
  顺序   hook 章放最前（冷开场），其余按 story_plan 顺序；章内大体按拍摄时间，
         镜头最多挪 2 位来避免连续长镜头 / 三连短镜头
所有时间内部都是整数微秒；挑不满的章节把差额外溢给有余量的章节，总长一微秒都不差。
"""
import argparse
import json
import os
import random
import sys
from collections import defaultdict

from common import US, read_csv, write_csv

RHYTHM = [("long", 12, 18), ("short", 3, 6), ("short", 3, 6), ("mid", 6, 9)]
MIN_SHOT = 2 * US          # 再短的镜头在成片里就是闪一下，不要
EDGE = int(0.5 * US)       # 素材首尾 0.5s 常是按快门的晃动，不取
GAP = 1 * US               # 同一素材两次取用之间至少隔 1s
STEP = int(0.5 * US)       # 候选窗口起点步长
REUSE_DECAY = 0.6          # 同一素材每多用一次，得分乘这个系数
CHAPTER_FLOOR = 20 * US    # 每章保底时长（素材够的话）
SNAP_MAX = int(1.5 * US)   # 静音吸附最多平移这么多

FIELDS = ["idx", "chapter", "chapter_title", "chapter_function", "kind", "name", "source",
          "in_s", "dur_s", "start_s", "in_us", "dur_us", "start_us", "score"]


def parse_target(s):
    """'10:00' / '1:02:30' / '600' → 微秒"""
    sec = 0.0
    for part in s.split(":"):
        sec = sec * 60 + float(part)
    return round(sec * US)


def fmt(us):
    s = us / US
    return f"{int(s // 60)}:{s % 60:04.1f}"


def snap_to_silence(a, d, silences, dur):
    """把窗口 [a, a+d) 整体平移到「入点落在最近静音段中点」，平移超过 SNAP_MAX 或越界就不动。"""
    best = a
    for s0, s1 in silences:
        mid = (s0 + s1) // 2
        if abs(mid - a) <= SNAP_MAX and EDGE <= mid <= dur - EDGE - d:
            if best == a or abs(mid - a) < abs(best - a):
                best = mid
    return best


# ---------- 素材 ----------

class Clip:
    def __init__(self, row, frames, silences):
        self.clip_id = row["clip_id"]
        self.path = row["path"]
        self.name = row["name"]
        self.shot_time = row["shot_time"]
        self.dur = round(float(row["duration_s"]) * US)
        self.frames = sorted(frames)        # [(t_us, score, bad)]
        self.silences = silences            # [(s0_us, s1_us)]
        self.used = []                      # [(in_us, out_us)]

    @property
    def usable(self):
        return max(0, self.dur - 2 * EDGE)

    @property
    def good_usable(self):
        """扣掉坏帧比例后的可用时长（粗估，给配额用）。"""
        if not self.frames:
            return self.usable
        bad_ratio = sum(b for _, _, b in self.frames) / len(self.frames)
        return round(self.usable * (1 - bad_ratio))

    def window_score(self, a, d):
        """窗口 [a, a+d) 的得分；含坏帧返回 None。没跑第 2 步时一律 0.5。"""
        if not self.frames:
            return 0.5
        inside = [(s, b) for t, s, b in self.frames if a <= t < a + d]
        if any(b for _, b in inside):
            return None
        if not inside:  # 窗口里没采样点：用最近的一帧
            t, s, b = min(self.frames, key=lambda f: abs(f[0] - (a + d / 2)))
            return None if b else s
        return sum(s for s, _ in inside) / len(inside)

    def free(self, a, d):
        return all(a + d + GAP <= u0 or a >= u1 + GAP for u0, u1 in self.used)

    def feasible(self, a, d):
        return EDGE <= a <= self.dur - EDGE - d and self.free(a, d) and self.window_score(a, d) is not None

    def snap(self, a, d):
        if not self.silences:
            return a
        b = snap_to_silence(a, d, self.silences, self.dur)
        return b if b != a and self.feasible(b, d) else a

    def best_window(self, d):
        lo, hi = EDGE, self.dur - EDGE - d
        if hi < lo:
            return None
        best = None
        for a in list(range(lo, hi + 1, STEP)) + [(lo + hi) // 2]:
            if not self.free(a, d):
                continue
            s = self.window_score(a, d)
            if s is None:
                continue
            s_adj = s - 0.02 * abs((a + d / 2) / self.dur - 0.5)   # 同分时偏向素材中段
            if best is None or s_adj > best[1]:
                best = (a, s_adj, s)
        if best:
            best = (self.snap(best[0], d),) + best[1:]
        return best

    def longest_free(self):
        segs, cur = [], EDGE
        for u0, u1 in sorted(self.used):
            segs.append(u0 - GAP - cur)
            cur = u1 + GAP
        segs.append(self.dur - EDGE - cur)
        return max(segs + [0])


def load_clips(work):
    # 第 3 步判出的歪倒帧（orientation.json）同样当坏帧
    tilted = {}
    op = os.path.join(work, "orientation.json")
    if os.path.exists(op):
        with open(op, encoding="utf-8") as f:
            tilted = {cid: {round(t * 100) for t in d.get("bad", [])}
                      for cid, d in json.load(f).get("clips", {}).items()}
    frames = defaultdict(list)
    fp = os.path.join(work, "frames.csv")
    if os.path.exists(fp):
        for f in read_csv(fp):
            bad = int(f["bad"]) or round(float(f["t"]) * 100) in tilted.get(f.get("clip_id"), ())
            frames[f["path"]].append((round(float(f["t"]) * US), float(f["score"]), int(bad)))
    sil = {}
    sp = os.path.join(work, "silences.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            sil = {k: [(round(a * US), round(b * US)) for a, b in v] for k, v in json.load(f).items()}
    clips = {r["clip_id"]: Clip(r, frames.get(r["path"], []), sil.get(r["clip_id"], []))
             for r in read_csv(os.path.join(work, "inventory.csv"))}
    return clips, bool(frames)


# ---------- 配额 ----------

def _water_fill(caps, quota, left):
    """按 √cap 权重把 left 注水进 quota，不超过各自 cap；返回分不出去的余量。"""
    while left > 0:
        open_ = [i for i in range(len(caps)) if quota[i] < caps[i]]
        if not open_:
            break
        total_w = sum(caps[i] ** 0.5 for i in open_)
        given = 0
        for i in open_:
            add = min(int(left * caps[i] ** 0.5 / total_w), caps[i] - quota[i])
            quota[i] += add
            given += add
        left -= given
        if given == 0:  # 只剩不够平分的零头
            i = max(open_, key=lambda i: caps[i] - quota[i])
            add = min(left, caps[i] - quota[i])
            quota[i] += add
            left -= add
    return left


def allocate_quota(chapters, target_us):
    """每章分多少微秒，总和 == target_us。有 share 的先按比例拿（不超过 good_us）；
    其余章节先保底 CHAPTER_FLOOR，再按 √可用时长注水；还有剩就回填给有余量的任何章节。"""
    caps = [ch["good_us"] for ch in chapters]
    quota = [0] * len(chapters)
    shared = [i for i, ch in enumerate(chapters) if ch.get("share")]
    hooks = [i for i, ch in enumerate(chapters) if ch.get("function") == "hook" and not ch.get("share")]
    free = [i for i in range(len(chapters)) if i not in shared and i not in hooks]
    for i in shared:
        quota[i] = min(round(float(chapters[i]["share"]) * target_us), caps[i])
    for i in hooks:   # 冷开场是一口高光，不按素材量分：默认 min(20s, 目标的 10%)
        quota[i] = min(CHAPTER_FLOOR, target_us // 10, caps[i])
    left = target_us - sum(quota)
    if free:
        floor = min(CHAPTER_FLOOR, left // len(free))
        for i in free:
            quota[i] = min(floor, caps[i])
        left = target_us - sum(quota)
        sub_q = [quota[i] for i in free]
        left = _water_fill([caps[i] for i in free], sub_q, left)
        for i, q in zip(free, sub_q):
            quota[i] = q
    if left > 0:
        left = _water_fill(caps, quota, left)
    return quota


# ---------- 章内挑镜头 ----------

def place_pin(c, at, d):
    """以 at 为中心放一个长度 d 的窗口；不可行就每 0.5s 向两侧平移，始终包含 at。"""
    d = min(d, c.usable)
    base = at - d // 2
    for k in range(0, 2 * d // STEP + 1):
        off = (k + 1) // 2 * STEP * (1 if k % 2 else -1)
        a = base + off
        if a <= at < a + d and c.feasible(a, d):
            return a, d
    return None


def place_pins(pool, quota, rng, pins):
    """先放必须出现的瞬间。返回 (shots, 剩余配额, 已用的节奏位置)。"""
    shots, remaining, k = [], quota, 0
    for p in pins:
        c = pool.get(p["clip_id"])
        kind, lo, hi = RHYTHM[k % len(RHYTHM)]
        d = min(round(rng.uniform(lo, hi) * US), remaining)
        if c is None or d < MIN_SHOT:
            why = "素材不在本章可选范围" if c is None else "本章配额已用完（给章节加 share 或减少 pins）"
            print(f"  ⚠ pin {p['clip_id']}@{p['at']}s 没放进去：{why}")
            continue
        w = place_pin(c, round(float(p["at"]) * US), d)
        if not w:
            print(f"  ⚠ pin {p['clip_id']}@{p['at']}s 放不下（坏帧或已占用），跳过")
            continue
        k += 1
        a, d = w
        c.used.append((a, a + d))
        shots.append({"kind": kind, "clip": c, "in_us": a, "dur_us": d,
                      "score": round(c.window_score(a, d) or 0, 3)})
        remaining -= d
    return shots, remaining, k


def pick_one(clips, d, kind):
    """在 clips 里挑一个长 d 的镜头（得分最高、不含坏帧、复用降权）；放不下就按空闲段从长到短、
    长度减半地退而求其次。挑中就占用并返回 shot，否则 None。"""
    best = None
    for c in clips:
        w = c.best_window(d)
        if w:
            score = w[1] * REUSE_DECAY ** len(c.used)
            if best is None or score > best[0]:
                best = (score, c, w[0], w[2])
    if best is None:
        for c in sorted(clips, key=Clip.longest_free, reverse=True):
            dd = min(d, c.longest_free())
            while dd >= MIN_SHOT:
                w = c.best_window(dd)
                if w:
                    best = (w[1], c, w[0], w[2])
                    d = dd
                    break
                dd //= 2
            if best:
                break
        if best is None:
            return None
        kind = "short" if d < 6 * US else "mid"
    _, c, a, s = best
    c.used.append((a, a + d))
    return {"kind": kind, "clip": c, "in_us": a, "dur_us": d, "score": round(s, 3)}


def _next_len(rng, k, remaining):
    kind, lo, hi = RHYTHM[k % len(RHYTHM)]
    d = min(round(rng.uniform(lo, hi) * US), remaining)
    if remaining - d < MIN_SHOT:      # 别留一个 <2s 的尾巴，并进当前镜头
        d = remaining
    return kind, d


def fill(pool, remaining, rng, k=0):
    """按节奏在 pool 里挑镜头填满 remaining。返回 (shots, 填不满的差额)。"""
    shots = []
    clips = list(pool.values())
    while remaining > 0 and clips:
        kind, d = _next_len(rng, k, remaining)
        k += 1
        shot = pick_one(clips, d, kind)
        if shot is None:
            break
        shots.append(shot)
        remaining -= shot["dur_us"]
    return shots, remaining


def fill_intercut(pool, intercut, remaining, rng, k=0, shots_so_far=()):
    """平行蒙太奇：两条线轮流各出一个镜头；最后一个镜头落在 end_on 那条线。
    某条线挑不出来就由另一条线补上。返回 (shots, 差额)。"""
    lines = {t: [pool[c] for c in intercut.get(t, []) if c in pool] for t in ("a", "b")}
    end_on = intercut.get("end_on", "a")
    count = {t: sum(s["clip"].clip_id in intercut.get(t, []) for s in shots_so_far) for t in ("a", "b")}
    turn = "a" if count["a"] <= count["b"] else "b"
    shots = []
    while remaining > 0 and (lines["a"] or lines["b"]):
        kind, d = _next_len(rng, k, remaining)
        k += 1
        if d == remaining:
            turn = end_on                 # 最后一个镜头
        shot = pick_one(lines[turn], d, kind) or pick_one(lines["b" if turn == "a" else "a"], d, kind)
        if shot is None:
            break
        shots.append(shot)
        remaining -= shot["dur_us"]
        turn = "b" if turn == "a" else "a"
    return shots, remaining


def interleave(shots, intercut):
    """两条线各自按拍摄时间排，再交替拼起来，最后一个落在 end_on（数量允许时）。"""
    a_ids = set(intercut.get("a", []))
    a = _sort([s for s in shots if s["clip"].clip_id in a_ids])
    b = _sort([s for s in shots if s["clip"].clip_id not in a_ids])
    end_on = intercut.get("end_on", "a")
    if len(a) == len(b):
        first, second = (b, a) if end_on == "a" else (a, b)
    else:
        first, second = (a, b) if len(a) > len(b) else (b, a)
    out = []
    for i in range(max(len(first), len(second))):
        if i < len(first):
            out.append(first[i])
        if i < len(second):
            out.append(second[i])
    return out


def plan_chapter(pool, quota, rng, pins=()):
    shots, remaining, k = place_pins(pool, quota, rng, pins)
    more, remaining = fill(pool, remaining, rng, k)
    return shots + more, remaining


MAX_SHIFT = 2              # 节奏调整时每个镜头离拍摄时间顺序最多挪几位


def _rhythm_bad(seq):
    """末尾是否出现「长-长」或「短-短-短」。"""
    k = [s["kind"] for s in seq[-3:]]
    return (len(k) >= 2 and k[-1] == k[-2] == "long") or (len(k) == 3 and k[0] == k[1] == k[2] == "short")


def rhythm_reorder(shots, budget=20000):
    """章内镜头已按拍摄时间排好：在每个镜头最多挪 MAX_SHIFT 位的前提下，消掉连续长镜头和三连短镜头。
    小范围回溯搜索，优先保持原顺序；搜不到可行解（或超出步数）就原样返回。"""
    n = len(shots)
    out, used, steps = [], [False] * n, [0]

    def dfs(p):
        if p == n:
            return True
        steps[0] += 1
        if steps[0] > budget:
            return False
        forced = [i for i in range(n) if not used[i] and i <= p - MAX_SHIFT]
        cands = forced or [i for i in range(max(0, p - MAX_SHIFT), min(n, p + MAX_SHIFT + 1)) if not used[i]]
        for i in cands:
            out.append(shots[i])
            if not _rhythm_bad(out):
                used[i] = True
                if dfs(p + 1):
                    return True
                used[i] = False
            out.pop()
        return False

    return list(out) if dfs(0) else list(shots)


def spill_order(chapters):
    """差额外溢的顺序：普通章节按剩余空闲素材从多到少；hook 排最后（冷开场要保持短）。"""
    return sorted(range(len(chapters)),
                  key=lambda i: (chapters[i]["function"] == "hook" or bool(chapters[i].get("intercut")),
                                 -sum(c.longest_free() for c in chapters[i]["pool"].values())))


def _sort(shots):
    return sorted(shots, key=lambda s: (s["clip"].shot_time, s["clip"].name, s["in_us"]))


def plan(work, target_us, seed=7):
    """返回 (shots 行列表, 章节摘要列表, 差额微秒)。"""
    clips, _ = load_clips(work)
    with open(os.path.join(work, "story_plan.json"), encoding="utf-8") as f:
        story = json.load(f)
    # pool=all 指「故事里出现过的全部素材」：被 --exclude 剔掉、没进任何章节的素材绝不回来
    in_story = [c for c in clips if any(c in ch.get("clip_ids", []) for ch in story["chapters"])]
    chapters = []
    for no, ch in enumerate(story["chapters"], 1):
        ids = [c for c in ch.get("clip_ids", []) if c in clips and clips[c].usable >= MIN_SHOT]
        pool_ids = in_story if ch.get("pool") == "all" else ids
        chapters.append({"no": no, "title": ch.get("title", ch["id"]), "function": ch.get("function", ""),
                         "share": ch.get("share"), "pins": ch.get("pins", []), "intercut": ch.get("intercut"),
                         "pool": {c: clips[c] for c in pool_ids if clips[c].usable >= MIN_SHOT},
                         "good_us": sum(clips[c].good_usable for c in pool_ids)})
    quotas = allocate_quota(chapters, target_us)

    rng = random.Random(seed)
    # 先给所有章节放 pins，再逐章补镜头：免得前面 pool=all 的章节把后面章节的高光占走
    placed = [place_pins(ch["pool"], q, rng, ch["pins"]) for ch, q in zip(chapters, quotas)]
    plans, short_of = [], 0
    for ch, (shots, left, k) in zip(chapters, placed):
        if ch["intercut"]:
            more, left = fill_intercut(ch["pool"], ch["intercut"], left, rng, k, shots)
        else:
            more, left = fill(ch["pool"], left, rng, k)
        plans.append(shots + more)
        short_of += left
    # good_us 只是估算：差额外溢给剩余空闲素材最多的章节，保证总长仍然精确
    for i in spill_order(chapters):
        if not short_of:
            break
        extra, short_of = fill(chapters[i]["pool"], short_of, rng)
        plans[i] = plans[i] + extra

    order = [i for i, ch in enumerate(chapters) if ch["function"] == "hook"] + \
            [i for i, ch in enumerate(chapters) if ch["function"] != "hook"]
    rows, t, summary = [], 0, []
    for i in order:
        ch = chapters[i]
        if ch["intercut"]:
            shots = interleave(plans[i], ch["intercut"])         # 平行蒙太奇：两条线交替
        else:
            shots = rhythm_reorder(_sort(plans[i]))               # 大体按拍摄时间，局部调整保长短交替
        summary.append({"title": ch["title"], "function": ch["function"], "clips": len(ch["pool"]),
                        "good_us": ch["good_us"], "got_us": sum(s["dur_us"] for s in shots), "shots": shots})
        for s in shots:
            c = s["clip"]
            rows.append({"idx": len(rows) + 1, "chapter": ch["no"], "chapter_title": ch["title"],
                         "chapter_function": ch["function"], "kind": s["kind"], "name": c.name, "source": c.path,
                         "in_s": round(s["in_us"] / US, 3), "dur_s": round(s["dur_us"] / US, 3),
                         "start_s": round(t / US, 3), "in_us": s["in_us"], "dur_us": s["dur_us"],
                         "start_us": t, "score": s["score"]})
            t += s["dur_us"]
    return rows, summary, short_of


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--target", required=True, help="成片时长，如 10:00 或 600")
    ap.add_argument("--seed", type=int, default=7, help="换个数能换一版镜头时长")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    target = parse_target(args.target)
    rows, summary, short_of = plan(args.work, target, args.seed)
    print(f"{'章节':<16} {'功能':<10} {'素材':>4} {'可用':>8} {'实得':>8} {'镜头':>4} {'均长':>6}  长/中/短")
    for ch in summary:
        n = len(ch["shots"]) or 1
        mix = "/".join(str(sum(s["kind"] == k for s in ch["shots"])) for k in ("long", "mid", "short"))
        print(f"{ch['title'][:16]:<16} {ch['function']:<10} {ch['clips']:>4} {fmt(ch['good_us']):>8} "
              f"{fmt(ch['got_us']):>8} {len(ch['shots']):>4} {ch['got_us'] / n / US:>5.1f}s  {mix}")
    total = sum(r["dur_us"] for r in rows)
    if rows:
        print(f"\n合计 {len(rows)} 个镜头，总长 {fmt(total)}（目标 {fmt(target)}），"
              f"平均 {total / len(rows) / US:.1f}s，用到 {len({r['source'] for r in rows})} 段素材")
    if short_of:
        sys.exit(f"素材不够，共差 {fmt(short_of)}：减少目标时长，或在 story_plan 里给章节加素材")
    if args.dry_run:
        print("\n[dry-run] 未写文件。满意就去掉 --dry-run 重跑；想换一版用 --seed。")
        return
    out = os.path.join(args.work, "shots.csv")
    write_csv(out, rows, FIELDS)
    print(f"→ {out}")


if __name__ == "__main__":
    main()

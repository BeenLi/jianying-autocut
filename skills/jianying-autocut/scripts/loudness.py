# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""响度：ffmpeg ebur128 实测 + 缓存 + 增益规则（build.py 调用，不单独跑）

  · 人声（旁白文件、原声段）按来源归一化到 -16 LUFS，最多 +12 dB，真峰值不超过 -1 dBTP
  · 旁白下的原声垫底：比人声目标低 18 LU，最多 0.15
  · BGM：全片一个压低比例，让每处人声比同时段 BGM 短时响度高至少 12 LU
  · 结果缓存在 W/loudness.json，键 = 路径 + mtime + 大小（+ 区间），文件被重录覆盖就重新测
"""
import json
import math
import os
import re
import subprocess

from common import US

VOICE_TARGET = -16.0
VOICE_MAX_DB = 12.0
TRUE_PEAK_MAX = -1.0
BED_BELOW = 18.0
BED_CAP = 0.15
MARGIN = 12.0
DEFAULT_DUCK = 0.25


def _fmt(us):
    s = us / US
    return f"{int(s // 60)}:{s % 60:04.1f}"


def parse_ebur128(stderr):
    """ebur128=peak=true:framelog=info 的输出 → {i, tp, short: [(t秒, S)]}。"""
    short = [(round(float(m.group(1)), 1), float(m.group(2)))
             for m in re.finditer(r"\bt:\s*([\d.]+)\s+TARGET:.*?\bS:\s*(-?[\d.]+)", stderr)]
    summary = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else ""
    i = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", summary)
    tp = re.search(r"Peak:\s*(-?[\d.]+)\s*dBFS", summary)
    return {"i": float(i.group(1)) if i else -70.0, "tp": float(tp.group(1)) if tp else -70.0, "short": short}


def measure(path, start=None, end=None):
    """实测 [start, end) 秒（不给就是整段）的积分响度、真峰值和逐 0.1s 的短时响度。"""
    cmd = ["ffmpeg", "-nostats", "-hide_banner"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", path, "-vn", "-af", "ebur128=peak=true:framelog=info", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return parse_ebur128(r.stderr)


def max_short(short, a_s, b_s):
    """[a_s, b_s] 秒内短时响度的最大值；没有采样点返回 None。"""
    vals = [s for t, s in short if a_s <= t <= b_s]
    return max(vals) if vals else None


class Cache:
    def __init__(self, work):
        self.path = os.path.join(work, "loudness.json")
        self.data = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)

    @staticmethod
    def _key(path, key_extra):
        st = os.stat(path)
        return f"{path}|{st.st_mtime}|{st.st_size}|{key_extra}"

    def get(self, path, key_extra=""):
        return self.data.get(self._key(path, key_extra))

    def put(self, path, value, key_extra=""):
        self.data[self._key(path, key_extra)] = value
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)

    def measure(self, path, start=None, end=None):
        extra = "" if start is None and end is None else f"{start}-{end}"
        hit = self.get(path, extra)
        if hit is None:
            hit = measure(path, start, end)
            self.put(path, hit, extra)
        return hit


def voice_gain(i, tp, target=VOICE_TARGET, max_db=VOICE_MAX_DB, tp_max=TRUE_PEAK_MAX):
    """人声增益（线性）和还差多少 dB 才到目标（0 = 达标）。"""
    d = min(target - i, max_db, tp_max - tp)
    return 10 ** (d / 20), max(0.0, target - i - d)


def bed_gain(clip_i, voice_target=VOICE_TARGET, below=BED_BELOW, cap=BED_CAP):
    """旁白下原声垫底的音量：比人声目标低 below LU，最多 cap。"""
    return min(cap, 10 ** ((voice_target - below - clip_i) / 20))


def bgm_duck(levels, voice=VOICE_TARGET, margin=MARGIN, default=DEFAULT_DUCK):
    """levels：[(该首歌的基础增益 dB, 人声期间该歌的最大短时响度)]。返回全片统一的压低比例。"""
    need = [10 ** ((voice - margin - s_max - base_db) / 20) for base_db, s_max in levels]
    return min([default] + need)


def margin_warnings(speech_spans, bgm_level, voice_levels, margin=MARGIN):
    """speech_spans：[(成片起点 us, 时长 us)]；bgm_level(a_us, b_us)：该区间 BGM 实际最大短时响度（无 BGM 为 None）；
    voice_levels：每句人声的实际响度。返回不达标的句子说明。"""
    out = []
    for (t, d), v in zip(speech_spans, voice_levels):
        b = bgm_level(t, t + d)
        if b is None:
            continue
        diff = round(v - b, 1)
        if diff < margin:
            out.append(f"{_fmt(t)} 人声只比 BGM 高 {diff} LU（要 ≥{margin:g}）：把这首歌的 --bgm 音量整体调低")
    return out


def db(g):
    return 20 * math.log10(g) if g > 0 else -120.0

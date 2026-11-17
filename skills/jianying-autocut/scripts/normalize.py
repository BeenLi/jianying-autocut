# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""旁白响度归一化：两遍 loudnorm，给每个旁白文件生成 -16 LUFS / -1.5 dBTP 的 WAV 副本（原文件不动）。

build.py --narration 调用；剪映里引用副本，音量固定 1.0。手机旁白峰均比大，剪映里单纯调音量提不上去
（真峰值先到顶），所以在剪映外面用 loudnorm 的动态模式先做好。

  第一遍：测 input_i / input_tp / input_lra / input_thresh / target_offset
  第二遍：带着测量值和 linear=true 输出；峰值放不下时 ffmpeg 自己退回动态模式（normalization_type）
不到 3 秒的文件 loudnorm 只能线性，可能被真峰值卡住、到不了目标：info["short"] 为真，由 build.py 提示。
"""
import json
import os
import re
import subprocess

TARGET = "I=-16:TP=-1.5:LRA=11"
KEY = "norm"                 # loudness.Cache 里的额外标记


def copy_names(paths, prev=None):
    """{原路径: 副本文件名（不含扩展名）}：去掉扩展名后同名的，依次加 _n2、_n3。
    prev：上次分给各原路径的名字（从缓存读）。还能用的（属于这个原文件名、没被别人占）照旧，
    这样新加一个同名文件时，已有的副本不会改名重做；其余按原路径排序分配空着的名字。"""
    prev, names, taken = prev or {}, {}, set()
    def base(p):
        return os.path.splitext(os.path.basename(p))[0]
    for p in sorted(set(paths)):
        n = prev.get(p)
        if n and n not in taken and (n == base(p) or re.fullmatch(re.escape(base(p)) + r"_n\d+", n)):
            names[p] = n
            taken.add(n)
    for p in sorted(set(paths) - set(names)):
        n, k = base(p), 1
        while n in taken:
            k += 1
            n = f"{base(p)}_n{k}"
        names[p] = n
        taken.add(n)
    return names


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, (r.stderr or "")[-500:])
    return r.stderr or ""


def _last_json(stderr):
    """loudnorm 的 print_format=json 打在 stderr 最后一个 {…} 块里。"""
    m = re.findall(r"\{[^{}]*\}", stderr)
    if not m:
        raise ValueError("loudnorm 没有输出测量结果")
    return json.loads(m[-1])


def _duration(stderr):
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def normalize(path, out_dir, cache, short_s=3.0, name=None):
    """生成 path 的归一化 WAV 副本 → (副本路径, {"type": "dynamic" | "linear", "short": bool})。
    name：副本文件名（不含扩展名），默认用原文件名；几个原文件同名时由调用方用 copy_names 定。
    结果记在 cache（键：原文件路径 + mtime + 大小 + "norm"），原文件、副本都没变就不再跑 ffmpeg。
    ffmpeg 失败抛 CalledProcessError，不留半截副本。"""
    out = os.path.join(out_dir, (name or os.path.splitext(os.path.basename(path))[0]) + ".wav")
    hit = cache.get(path, KEY)
    if hit and hit.get("out") == out and os.path.exists(out) and os.path.getmtime(out) == hit.get("out_mtime"):
        return out, {"type": hit["type"], "short": hit["short"]}
    first = _run(["ffmpeg", "-nostats", "-hide_banner", "-i", path, "-vn",
                  "-af", f"loudnorm={TARGET}:print_format=json", "-f", "null", "-"])
    m = _last_json(first)
    dur = _duration(first)
    af = (f"loudnorm={TARGET}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    os.makedirs(out_dir, exist_ok=True)
    try:
        second = _run(["ffmpeg", "-y", "-nostats", "-hide_banner", "-i", path, "-vn", "-af", af,
                       "-ar", "48000", "-c:a", "pcm_s16le", out])
        kind = _last_json(second).get("normalization_type", "dynamic")
    except Exception:
        if os.path.exists(out):
            os.remove(out)
        raise
    info = {"type": "linear" if kind == "linear" else "dynamic", "short": dur is not None and dur < short_s}
    cache.put(path, {"out": out, "out_mtime": os.path.getmtime(out), **info}, KEY)
    return out, info

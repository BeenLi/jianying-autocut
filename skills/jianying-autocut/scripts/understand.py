# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""第 3 步 内容理解：代理长片 → video-understanding（MiMo）→ 拆回每段素材

用法: uv run --script understand.py --work <目录> [--context "庐山两日徒步"] [--no-understanding]

video-understanding 是按「一部长片」设计的（每次只吃一个视频）。这里把所有素材按拍摄顺序
转成 720p/15fps 低清片段拼成一条代理长片 proxy/reel.mp4，只跑一次理解，再按 proxy_map.json
把场景描述和语音拆回每段素材 → clip_understanding.json（时间为素材内秒）。
随后逐张缩略图让 MiMo 判断画面方向 → orientation.json：整段倒装的素材在草稿里转 180°，
晃着拍歪倒的帧当坏帧（第 5 步避开）。

MiMo 不可用（无 key / 余额不足 / 欠费）时会提醒充值并以退出码 3 结束；
--no-understanding 跳过本步，改由 Claude 看 contact/ 联系表写故事。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from common import RECHARGE_HINT, UNDERSTAND_CLI, classify_mimo_error, read_csv

W, H, FPS = 1280, 720, 15


def proxy_cmd(row, out):
    """一段素材 → 1280x720 / 15fps CFR / AAC 立体声。等比缩进框内再补黑边，不裁画面；
    ffmpeg 转码默认按旋转元数据自动转正；没有音轨的补一条静音，保证拼接时流结构一致。"""
    mute = str(row["has_audio"]) != "True"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", row["path"]]
    if mute:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p")
    cmd += ["-map", "0:v:0", "-map", "1:a:0" if mute else "0:a:0", "-vf", vf,
            "-c:v", "h264_videotoolbox", "-b:v", "2M",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", out]
    return cmd


def _duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return float(out.strip())


def build_map(rows, durations):
    """按各片段的真实时长累加出每段素材在代理长片上的位置（秒）。"""
    out, t = [], 0.0
    for r, d in zip(rows, durations):
        out.append({"clip_id": r["clip_id"], "source_path": r["path"],
                    "proxy_start": round(t, 3), "proxy_end": round(t + d, 3)})
        t += d
    return out


def make_reel(work, rows):
    parts_dir = os.path.join(work, "proxy", "parts")
    os.makedirs(parts_dir, exist_ok=True)

    def part(r):
        st = os.stat(r["path"])
        key = hashlib.sha1(f"{r['path']}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:8]
        out = os.path.join(parts_dir, f"{r['clip_id']}_{key}.mp4")
        if not os.path.exists(out):  # 按 路径+大小+mtime 缓存，重跑只转新素材
            tmp = out + ".tmp.mp4"
            subprocess.run(proxy_cmd(r, tmp), check=True)
            os.replace(tmp, out)
        return out

    print(f"转代理片段 {len(rows)} 段（720p/15fps，有缓存的跳过）…")
    with ThreadPoolExecutor(4) as ex:
        parts = list(ex.map(part, rows))
    durations = [_duration(p) for p in parts]
    lst = os.path.join(work, "proxy", "parts.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    reel = os.path.join(work, "proxy", "reel.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", reel], check=True)
    pm = build_map(rows, durations)
    with open(os.path.join(work, "proxy_map.json"), "w", encoding="utf-8") as f:
        json.dump(pm, f, ensure_ascii=False, indent=1)
    print(f"代理长片 {pm[-1]['proxy_end'] / 60:.1f} 分钟 → {reel}")
    return reel


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def split_to_clips(proxy_map, vlm, asr):
    """场景归给与它重叠最长的那段素材（时间裁进该素材）；语音按中点归属。输出素材内秒。"""
    out = {c["clip_id"]: {"scenes": [], "speech": []} for c in proxy_map}
    for s in vlm:
        best = max(proxy_map, key=lambda c: _overlap(s["start"], s["end"], c["proxy_start"], c["proxy_end"]))
        if _overlap(s["start"], s["end"], best["proxy_start"], best["proxy_end"]) <= 0:
            continue
        off = best["proxy_start"]
        facts = {}
        for k, v in (s.get("frame_facts") or {}).items():
            try:
                facts[f"{float(k) - off:.1f}"] = v
            except ValueError:
                facts[k] = v
        out[best["clip_id"]]["scenes"].append({
            "start": round(max(s["start"], off) - off, 3),
            "end": round(min(s["end"], best["proxy_end"]) - off, 3),
            "description": s.get("description", ""), "frame_facts": facts})
    for u in asr:
        if not (u.get("text") or "").strip():
            continue
        mid = (u["start"] + u["end"]) / 2
        for c in proxy_map:
            if c["proxy_start"] <= mid < c["proxy_end"]:
                off = c["proxy_start"]
                out[c["clip_id"]]["speech"].append({
                    "start": round(max(u["start"], off) - off, 3),
                    "end": round(min(u["end"], c["proxy_end"]) - off, 3), "text": u["text"]})
                break
    return out


UPSTREAM_DEFAULT_MODEL = "mimo-v2.5"   # video-understanding 写死的默认 VLM


def pick_vision_model(available, wanted):
    """选看画面用的模型：用户指定（MIMO_MODEL）优先，但必须在可用清单里；
    否则用上游默认；默认已下线就挑一个 flash（理解要调几百次，快且省），再不行任意 chat 模型。"""
    if wanted:
        return wanted if wanted in available else None
    if UPSTREAM_DEFAULT_MODEL in available:
        return UPSTREAM_DEFAULT_MODEL
    chat = [m for m in available if not re.search(r"-(asr|tts)", m)]
    return next((m for m in chat if "flash" in m), chat[0] if chat else None)


def _mimo_base(key):
    if os.environ.get("MIMO_API_URL"):
        base = os.environ["MIMO_API_URL"].rstrip("/")
        return base[: -len("/chat/completions")] if base.endswith("/chat/completions") else base
    if key.startswith("tp-"):
        return f"https://token-plan-{os.environ.get('MIMO_TOKEN_PLAN_CLUSTER', 'cn')}.xiaomimimo.com/v1"
    return "https://api.xiaomimimo.com/v1"


def _stop(kind, detail):
    if kind == "recharge":
        print(f"\n⚠ {RECHARGE_HINT}\n  （MiMo 返回：{detail[:200]}）", file=sys.stderr)
    elif kind == "bad_model":
        print(f"\n⚠ MiMo 没有可用的看图模型：{detail[:200]}\n"
              "  可设置 MIMO_MODEL=<模型名>（见 MiMo 控制台），或加 --no-understanding", file=sys.stderr)
    else:
        print(f"\n⚠ MiMo key 无效：请检查 MIMO_API_KEY 与 MIMO_API_URL 是否匹配。（{detail[:200]}）\n"
              "  不想用 MiMo：加 --no-understanding", file=sys.stderr)
    sys.exit(3)


def _call(url, key, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers={
        "Content-Type": "application/json", "api-key": key, "User-Agent": "jianying-autocut/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def mimo_preflight():
    """开工前：查可用模型 → 选定看图模型 → 发一个极小请求。
    key 无效 / 欠费 / 模型下线当场报出来，不白等转码。选定的模型写进 MIMO_MODEL 传给上游。"""
    key = os.environ.get("MIMO_API_KEY", "").strip()
    if not key:
        _stop("recharge", "未设置 MIMO_API_KEY")
    base = _mimo_base(key)
    try:
        available = [m.get("id") for m in _call(base + "/models", key).get("data", [])]
        model = pick_vision_model(available, os.environ.get("MIMO_MODEL"))
        if not model:
            _stop("bad_model", f"MIMO_MODEL={os.environ.get('MIMO_MODEL') or '未设置'}，可用：{', '.join(available)}")
        _call(base + "/chat/completions", key, {"model": model, "messages": [{"role": "user", "content": "ping"}],
                                                "max_completion_tokens": 1, "thinking": {"type": "disabled"}})
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        kind = classify_mimo_error(text, e.code)
        if kind in ("recharge", "bad_key", "bad_model"):
            _stop(kind, text)
        print(f"MiMo 预检返回 {e.code}（{kind}），继续：{text[:120]}")
        return
    except urllib.error.URLError as e:
        print(f"MiMo 预检网络异常，继续尝试：{e.reason}")
        return
    os.environ["MIMO_MODEL"] = model   # 子进程（video-understanding）继承
    print(f"MiMo 预检通过，看图模型 {model}")


ORIENT_PROMPT = "这张视频截图的画面方向对吗？只回答一个词：正常 / 上下颠倒 / 向左倒 / 向右倒 / 无法判断"
FLIP_MAJORITY = 0.7   # ≥70% 的帧上下颠倒才判定整段倒装（运动相机倒挂），否则只是晃着拍
FLIP_MIN_FRAMES = 3   # 单帧判断会误判（实测把正常车窗画面判成颠倒）：至少 3 帧有判断才敢整段旋转


def normalize_orientation(text):
    t = (text or "").strip()
    if "颠倒" in t:
        return "flip"
    if "左倒" in t or "右倒" in t:
        return "tilt"
    if t.startswith("正常"):
        return "ok"
    return "unknown"


def decide_orientation(labels):
    """一段素材各帧的方向 {t: ok|flip|tilt|unknown} → {"rotate": 0|180, "bad": [t…]}。
    整段倒装就转 180°，此时原本「正常」的帧转完反而倒了，也算坏帧；
    否则不转，把颠倒 / 歪倒的帧当坏帧，挑镜头时避开。"""
    judged = {float(t): v for t, v in labels.items() if v != "unknown"}
    flips = sum(v == "flip" for v in judged.values())
    rotate = 180 if len(judged) >= FLIP_MIN_FRAMES and flips / len(judged) >= FLIP_MAJORITY else 0
    keep = "flip" if rotate else "ok"
    bad = sorted(t for t, v in judged.items() if v != keep)
    # 一半以上抽样帧都歪（相机挂着晃着拍）：8 秒一帧的缝隙里也大概率是歪的，整段不用
    if not rotate and len(labels) >= FLIP_MIN_FRAMES and len(bad) / len(labels) > 0.5:
        return {"rotate": 0, "bad": sorted(float(t) for t in labels), "unusable": True}
    return {"rotate": rotate, "bad": bad}


def check_orientation(work, model):
    """逐张缩略图问 MiMo 方向，结果缓存在 orientation.json，重跑只问新帧。"""
    import base64
    path = os.path.join(work, "orientation.json")
    cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    labels = cache.get("labels", {})
    key = os.environ.get("MIMO_API_KEY", "").strip()
    url = _mimo_base(key) + "/chat/completions"
    todo = [f for f in read_csv(os.path.join(work, "frames.csv"))
            if f"{float(f['t']):.2f}" not in labels.get(f["clip_id"], {})]

    def ask(f):
        thumb = os.path.join(work, "thumbs", f"{f['clip_id']}_{float(f['t']):07.2f}.jpg")
        if not os.path.exists(thumb):
            return f, "unknown"
        img = base64.b64encode(open(thumb, "rb").read()).decode()
        body = {"model": model, "max_completion_tokens": 10, "thinking": {"type": "disabled"},
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
                    {"type": "text", "text": ORIENT_PROMPT}]}]}
        for _ in range(3):
            try:
                r = _call(url, key, body)
                return f, normalize_orientation(r["choices"][0]["message"]["content"])
            except urllib.error.HTTPError as e:
                if classify_mimo_error(e.read().decode("utf-8", "replace"), e.code) in ("recharge", "bad_key"):
                    raise
            except (urllib.error.URLError, OSError, KeyError):
                pass
        return f, "unknown"

    if todo:
        print(f"检查画面方向：{len(todo)} 帧（MiMo {model}）…")
        with ThreadPoolExecutor(8) as ex:
            for f, lab in ex.map(ask, todo):
                labels.setdefault(f["clip_id"], {})[f"{float(f['t']):.2f}"] = lab
    clips = {cid: decide_orientation(v) for cid, v in labels.items()}
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"labels": labels, "clips": clips}, fp, ensure_ascii=False, indent=1)
    rot = [c for c, d in clips.items() if d["rotate"]]
    unusable = [c for c, d in clips.items() if d.get("unusable")]
    tilted = {c: len(d["bad"]) for c, d in clips.items() if d["bad"] and not d["rotate"] and not d.get("unusable")}
    print(f"画面方向：整段倒装需转 180° 的 {len(rot)} 段 {rot}；大半歪倒整段不用的 {len(unusable)} 段 {unusable}；"
          f"个别帧歪倒（挑镜头时避开）的 {len(tilted)} 段 {tilted}")


_NETWORK = re.compile(r"TLS|SSL|EOF|timed out|timeout|Connection reset|Connection aborted|"
                      r"RemoteDisconnected|urlopen error|5\d\d", re.I)


def should_retry(tail, kind):
    """上游失败后值不值得自动重跑：网络类错误 + 上游声明可断点续传（成功的部分已缓存）。"""
    return kind in ("other", "rate_limit") and "断点续传" in tail and bool(_NETWORK.search(tail))


def run_upstream(reel, wd, context, attempts=3):
    os.makedirs(wd, exist_ok=True)
    log_path = os.path.join(wd, "run.log")
    cmd = ["python3", UNDERSTAND_CLI, reel, "--work-dir", wd, "--style", "旅行vlog"]
    if context:
        cmd += ["--context", context]
    for n in range(1, attempts + 1):
        print("调用 video-understanding（MiMo 看画面 + 听语音，时间较长）…" if n == 1
              else f"网络中断导致部分场景失败，断点续传重试（第 {n}/{attempts} 次）…")
        with open(log_path, "w", encoding="utf-8") as log:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                sys.stdout.write(line)
                log.write(line)
            p.wait()
        if not p.returncode:
            return
        with open(log_path, encoding="utf-8") as f:
            tail = f.read()[-4000:]
        codes = re.findall(r"\((\d{3})\)|HTTP Error (\d{3})", tail)
        status = next((int(a or b) for a, b in codes), None)
        kind = classify_mimo_error(tail, status)
        if kind in ("recharge", "bad_key", "bad_model"):
            _stop(kind, tail[-300:])
        if not should_retry(tail, kind):
            break
    sys.exit(f"video-understanding 失败（退出码 {p.returncode}），见 {log_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--context", default="", help="一句话交代素材背景，帮 MiMo 理解")
    ap.add_argument("--no-understanding", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有理解结果也重跑代理长片和 video-understanding")
    args = ap.parse_args()

    if args.no_understanding:
        print("降级模式：不调 MiMo。请看 contact/ 联系表，按 references/story_plan.md 直接写 story_plan.json")
        return
    if not os.path.exists(UNDERSTAND_CLI):
        sys.exit(f"没找到 video-understanding（{UNDERSTAND_CLI}）；可加 --no-understanding 降级")
    mimo_preflight()

    wd = os.path.join(args.work, "understanding")
    cu_path = os.path.join(args.work, "clip_understanding.json")
    if os.path.exists(cu_path) and not args.force:
        print("已有理解结果（clip_understanding.json），跳过代理长片和 video-understanding；要重跑加 --force")
    else:
        rows = read_csv(os.path.join(args.work, "inventory.csv"))
        reel = make_reel(args.work, rows)
        run_upstream(reel, wd, args.context)
        with open(os.path.join(args.work, "proxy_map.json"), encoding="utf-8") as f:
            pm = json.load(f)
        load = lambda n: json.load(open(os.path.join(wd, n), encoding="utf-8")) if os.path.exists(os.path.join(wd, n)) else []
        per_clip = split_to_clips(pm, load("vlm_analysis.json"), load("asr_result.json"))
        with open(cu_path, "w", encoding="utf-8") as f:
            json.dump(per_clip, f, ensure_ascii=False, indent=1)
        described = sum(bool(v["scenes"]) for v in per_clip.values())
        talking = sum(bool(v["speech"]) for v in per_clip.values())
        print(f"\n拆回 {len(per_clip)} 段素材：{described} 段有画面描述，{talking} 段有语音文字")

    if os.path.exists(os.path.join(args.work, "frames.csv")):
        try:
            check_orientation(args.work, os.environ["MIMO_MODEL"])
        except urllib.error.HTTPError as e:
            _stop(classify_mimo_error(str(e), e.code), str(e))
    else:
        print("没有 frames.csv（第 2 步没跑），跳过画面方向检查")
    print(f"下一步：读 {os.path.join(wd, 'agent_narration_brief.md')}，写 recap_story_plan.json（时间用代理长片时间）")


if __name__ == "__main__":
    main()

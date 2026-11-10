# /// script
# requires-python = ">=3.10"
# dependencies = ["faster-whisper", "socksio"]   # socksio：走 SOCKS 代理时下载模型要用
# ///
"""第 3 步 语音转写（本地 Whisper，音频不离开本机、不收费）→ speech.json

用法: uv run --script transcribe.py --work W [--context "庐山两日徒步"] [--model small] [--language zh] [--force]

  · 逐段转写有音轨的素材，时间是素材内秒，分句来自 Whisper。每转完一段就落盘，中断后重跑会跳过已完成的素材
  · --context 里的地名、人名会提示给 Whisper，减少同音字错误
  · 首次运行要下载模型（small 约 500MB），之后离线可用
  · 输出 {clip_id: [{start, end, text}]}，没有语音的素材是空列表
"""
import argparse
import difflib
import json
import os
import re
from collections import Counter

from common import read_csv

MAX_NO_SPEECH = 0.5    # Whisper 认为「这段不是人声」的概率高于此值就丢弃。实测真话 0.02–0.20，幻听 0.60
BASE_PROMPT = "以下是普通话的句子。"   # 让中文输出简体并带标点
ECHO_RATIO = 0.8       # 与提示词里某一句的相似度达到这个值，就当作 Whisper 把提示词念了出来
MAX_REPEAT = 3         # 同一段素材里同一句出现这么多次，就当作幻听整组丢掉
END_SLACK = 0.5        # 句子结束时间最多超出素材长度这么多秒


def _norm(text):
    return re.sub(r"[\W_]+", "", text)


def is_prompt_echo(text, prompt):
    """安静画面上 Whisper 会把提示词原样输出（实测：日落素材转出「舟山枸杞岛旅行，带着小狗格桑。」）。"""
    t = _norm(text)
    if not t or not prompt:
        return False
    if len(t) >= 6 and t in _norm(prompt):
        return True
    return any(difflib.SequenceMatcher(None, t, _norm(p)).ratio() >= ECHO_RATIO
               for p in re.split(r"[。！？!?.\n]", prompt) if _norm(p))


def speech_from_segments(segments, duration=None, prompt=""):
    """Whisper 的分句 → [{start, end, text}]。去掉空句、大概率不是人声的句子，以及三种幻听：
    念出提示词、时间超出素材长度、同一句反复出现。"""
    out = []
    for s in segments:
        text = s.text.strip()
        if not text or s.no_speech_prob > MAX_NO_SPEECH or is_prompt_echo(text, prompt):
            continue
        if duration is not None and s.end > duration + END_SLACK:
            continue
        out.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": text})
    counts = Counter(_norm(s["text"]) for s in out)
    return [s for s in out if counts[_norm(s["text"])] < MAX_REPEAT]


def _save(path, result):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def transcribe_clips(rows, model, out_path, language=None, context="", force=False):
    """逐段转写并落盘，返回 {clip_id: speech}。转写失败的素材只报告，不写入结果，重跑时会再试。"""
    result = {}
    if os.path.exists(out_path) and not force:
        with open(out_path, encoding="utf-8") as f:
            result = json.load(f)
    prompt = f"{BASE_PROMPT}{context}" if context else BASE_PROMPT
    for i, r in enumerate(rows, 1):
        cid = r["clip_id"]
        if cid in result:
            continue
        if str(r.get("has_audio")) != "True":
            result[cid] = []
        else:
            try:
                segments, _ = model.transcribe(r["path"], language=language, initial_prompt=prompt, vad_filter=True,
                                               condition_on_previous_text=False)
                dur = float(r["duration_s"]) if r.get("duration_s") else None
                result[cid] = speech_from_segments(segments, dur, prompt)
            except Exception as e:   # 坏文件不应该让整批转写白跑
                print(f"  ⚠ {cid} 转写失败：{e}")
                continue
            print(f"  [{i}/{len(rows)}] {cid}：{len(result[cid])} 句")
        _save(out_path, result)
    _save(out_path, result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--context", default="", help="一句话背景，地名、人名有助于减少同音字错误")
    ap.add_argument("--model", default="small", help="Whisper 模型：tiny / base / small / medium / large-v3，越大越准越慢")
    ap.add_argument("--language", default="zh", help="素材语言；混合语言或不确定时写 auto")
    ap.add_argument("--force", action="store_true", help="已有结果也重新转写")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    rows = read_csv(os.path.join(args.work, "inventory.csv"))
    out = os.path.join(args.work, "speech.json")
    language = None if args.language == "auto" else args.language
    result = transcribe_clips(rows, model, out, language, args.context, args.force)
    talking = sum(bool(v) for v in result.values())
    missing = len(rows) - len(result)
    print(f"{len(result)} 段素材转写完成，{talking} 段有语音" + (f"，{missing} 段失败（重跑会再试）" if missing else ""))
    print(f"→ {out}")


if __name__ == "__main__":
    main()

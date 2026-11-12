# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""第 3 步 场景描述：校验 Claude 写的 scene_notes.json，合并语音生成 footage_brief.md

用法: uv run --script notes.py --work W

scene_notes.json 由 Claude 看联系表时写，可以分批写，时间是素材内秒：
  {"c001": [{"start": 0, "end": 12, "description": "石阶上山，雾很大"}]}

全部素材都写完且没有错误时，生成 footage_brief.md（每段素材的画面 + 语音，按时间排），退出码 0。
还有素材没写或有错误时列出来，退出码 1，把缺的补上再跑。
"""
import argparse
import os
import sys

from common import load_json, read_csv


def check_notes(notes, durations):
    """返回 (没写的素材, 错误列表)。durations: {clip_id: 秒}。"""
    errors = []
    for cid, items in notes.items():
        if cid not in durations:
            errors.append(f"{cid}：inventory.csv 里没有这段素材")
            continue
        for n in items:
            start, end = n.get("start"), n.get("end")
            if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
                    and 0 <= start < end <= durations[cid] + 1):
                errors.append(f"{cid}：时间 {start}-{end} 不对（素材长 {durations[cid]:g}s）")
            elif not str(n.get("description", "")).strip():
                errors.append(f"{cid}：{start}-{end} 没有描述")
    return [cid for cid in durations if not notes.get(cid)], errors


def render_brief(inventory, notes, speech):
    """每段素材一节，画面和语音按时间混排。"""
    lines = ["# 素材简报", ""]
    for r in inventory:
        cid = r["clip_id"]
        lines += [f"## {cid} {r['name']}（{float(r['duration_s']):.0f}s，{r.get('shot_time', '')}）", ""]
        entries = [(n["start"], 0, f"- {n['start']:g}-{n['end']:g}s 画面：{n['description'].strip()}")
                   for n in notes.get(cid, [])]
        entries += [(s["start"], 1, f"- {s['start']:g}-{s['end']:g}s 语音：{s['text']}") for s in speech.get(cid, [])]
        lines += [text for _, _, text in sorted(entries, key=lambda e: e[:2])] + [""]
    return "\n".join(lines)


def _load(path):
    return load_json(path, default={}, kind=dict)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()

    inventory = read_csv(os.path.join(args.work, "inventory.csv"))
    notes = _load(os.path.join(args.work, "scene_notes.json"))
    missing, errors = check_notes(notes, {r["clip_id"]: float(r["duration_s"]) for r in inventory})
    for e in errors:
        print("  ✗", e)
    if missing:
        print(f"还有 {len(missing)} 段素材没写描述：{','.join(missing)}")
    if missing or errors:
        sys.exit(1)
    out = os.path.join(args.work, "footage_brief.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_brief(inventory, notes, _load(os.path.join(args.work, "speech.json"))))
    print(f"{len(inventory)} 段素材都有描述 → {out}")


if __name__ == "__main__":
    main()

# /// script
# requires-python = ">=3.10"
# dependencies = ["pymediainfo"]
# ///
"""第 1 步 素材盘点 → inventory.csv + silences.json

用法: uv run --script probe.py <素材目录> [--work <目录>]

每段素材：时长 / 分辨率 / 帧率 / 有无音轨 / 拍摄时间，按拍摄时间排序后编号 c001…；
再测静音段（只解音频，很快）：人声频段（300-3000Hz）里 ≥0.4s 的安静处，
第 5 步把镜头入点挪到这里，少切在半句话上。
（曾试过给每段打「人声分」，用 MiMo 转写对照只有 AUC≈0.6，判不准，已取消。）
没有 ffprobe 时退回 pymediainfo（不为此去装 ffmpeg）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from common import VIDEO_EXTS, default_work, have, read_csv, write_csv

FIELDS = ["clip_id", "path", "name", "folder", "duration_s", "width", "height", "fps",
          "has_audio", "rotation", "shot_time", "size_mb"]
LOUD_DB = -35.0


def _fps(rate):
    num, _, den = (rate or "0/1").partition("/")
    return round(float(num) / float(den or 1), 3) if float(den or 1) else 0.0


def probe_ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    rot = int((v.get("tags") or {}).get("rotate", 0))
    for sd in v.get("side_data_list", []):
        rot = int(sd.get("rotation", rot))
    w, h = int(v["width"]), int(v["height"])
    if abs(rot) in (90, 270):  # 竖拍素材：剪映按显示方向算宽高
        w, h = h, w
    return {
        "duration_s": float(j["format"]["duration"]),
        "width": w, "height": h,
        "fps": _fps(v.get("avg_frame_rate") or v.get("r_frame_rate")),
        "has_audio": any(s["codec_type"] == "audio" for s in j["streams"]),
        "rotation": rot,
        "shot_time": (j["format"].get("tags") or {}).get("creation_time", ""),
    }


def probe_mediainfo(path):
    import pymediainfo
    info = pymediainfo.MediaInfo.parse(path)
    v = info.video_tracks[0]
    g = info.general_tracks[0]
    rot = int(float(getattr(v, "rotation", 0) or 0))
    w, h = int(v.width), int(v.height)
    if abs(rot) in (90, 270):
        w, h = h, w
    return {
        "duration_s": float(v.duration or g.duration) / 1000,
        "width": w, "height": h,
        "fps": float(v.frame_rate or 0),
        "has_audio": bool(info.audio_tracks),
        "rotation": rot,
        "shot_time": str(getattr(g, "encoded_date", "") or "").replace("UTC ", ""),
    }



def parse_silences(stderr, dur):
    """解析 ffmpeg silencedetect 输出；结尾未闭合的静音段收到素材末尾。"""
    out, start = [], None
    for line in stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    if start is not None:
        out.append((start, dur))
    return out


def analyze_audio(path, dur):
    """人声频段里的静音段（silencedetect 打到 stderr）。"""
    af = f"highpass=f=300,lowpass=f=3000,silencedetect=n={LOUD_DB}dB:d=0.4"
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-vn", "-i", path, "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True)
    return parse_silences(r.stderr, dur)


def assign_ids(rows, old):
    """编号跟着文件走：上次盘点过的沿用旧编号，新文件接在最大编号后面。
    这样素材目录加了新文件，故事脚本和 --exclude 里的编号也不会失效。"""
    used = [int(v[1:]) for v in old.values() if re.fullmatch(r"c\d+", v)]
    nxt = max(used, default=0) + 1
    for r in rows:
        if r["path"] in old:
            r["clip_id"] = old[r["path"]]
        else:
            r["clip_id"] = f"c{nxt:03d}"
            nxt += 1
    return rows


def probe(path, use_ffprobe):
    try:
        meta = probe_ffprobe(path) if use_ffprobe else probe_mediainfo(path)
    except Exception as e:  # 坏文件 / 没有视频轨：跳过但报出来
        return None, f"{path}: {e}"
    if not meta["shot_time"]:  # 没有拍摄时间就退回文件修改时间
        mtime = os.path.getmtime(path)
        meta["shot_time"] = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    meta["silences"] = analyze_audio(path, meta["duration_s"]) if meta["has_audio"] and have("ffmpeg") else []
    meta.update(path=path, name=os.path.basename(path),
                folder=os.path.basename(os.path.dirname(path)),
                duration_s=round(meta["duration_s"], 3),
                size_mb=round(os.path.getsize(path) / 2**20, 1))
    return meta, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--work", help="工作目录，默认 <素材目录>/_autocut")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.folder))
    work = args.work or default_work(root)
    files = sorted(
        os.path.join(d, f) for d, ds, fs in os.walk(root) for f in fs
        if os.path.splitext(f)[1].lower() in VIDEO_EXTS and not f.startswith("._")
        and os.path.abspath(d) != work and not os.path.abspath(d).startswith(work + os.sep))
    if not files:
        sys.exit(f"{root} 下没找到视频文件")

    use_ffprobe = have("ffprobe")
    print(f"扫描 {len(files)} 个文件（{'ffprobe' if use_ffprobe else 'pymediainfo，未检测到 ffprobe'}）…")
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda p: probe(p, use_ffprobe), files))
    rows = [m for m, _ in results if m]
    for _, err in results:
        if err:
            print("  跳过", err)
    rows.sort(key=lambda r: (r["shot_time"], r["name"]))
    old_inv = os.path.join(work, "inventory.csv")
    old = {r["path"]: r["clip_id"] for r in read_csv(old_inv)} if os.path.exists(old_inv) else {}
    assign_ids(rows, old)
    silences = {r["clip_id"]: [[round(a, 3), round(b, 3)] for a, b in r.pop("silences")] for r in rows}
    os.makedirs(work, exist_ok=True)
    write_csv(os.path.join(work, "inventory.csv"), rows, FIELDS)
    with open(os.path.join(work, "silences.json"), "w", encoding="utf-8") as f:
        json.dump(silences, f)

    total = sum(r["duration_s"] for r in rows)
    print(f"\n{'id':<5} {'文件':<32} {'时长':>8}  {'分辨率':<10} {'fps':>6}  静音段  拍摄时间")
    for r in rows:
        print(f"{r['clip_id']:<5} {r['name'][:32]:<32} {r['duration_s']:>7.1f}s  "
              f"{r['width']}x{r['height']:<5} {r['fps']:>6} {len(silences[r['clip_id']]):>6}  {r['shot_time'][:19]}")
    print(f"\n共 {len(rows)} 段，总时长 {total/3600:.0f} 小时 {total%3600/60:02.0f} 分，"
          f"{sum(r['size_mb'] for r in rows)/1024:.1f} GB → {work}")


if __name__ == "__main__":
    main()

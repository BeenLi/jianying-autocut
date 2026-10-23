# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "pillow"]
# ///
"""第 2 步 抽帧打分 + 联系表 → frames.csv, thumbs/, contact/

用法: uv run --script frames.py --work <目录> [--every 8]

每 N 秒抽 1 帧（只解关键帧：4K 10-bit HEVC 单帧 ~20s → ~0.4s），给两个原始分：
  sharpness  = 拉普拉斯方差（糊片 / 晃动会很低）
  brightness = 平均灰度 0-255
score = 清晰度在全部帧里的百分位 × 曝光惩罚（跨素材时偏好更清楚的）；
bad   = 糊（相对本段中位数突降，或绝对值极低）或曝光严重失常。
联系表 contact/sheet_NN.jpg：每张 4×5 格缩略图，标 clip_id 和秒数，
给没有 MiMo 时的降级模式用——Claude 直接看图写故事。
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from common import have, read_csv, write_csv

FIELDS = ["clip_id", "path", "t", "sharpness", "brightness", "score", "bad"]
DARK, BRIGHT = 40, 215          # 平均灰度低于 / 高于这个算欠曝 / 过曝
# 判糊要和「本段素材」比，不能和全局比：室内 / 雾天 / 夜景纹理少，
# 清晰帧的拉普拉斯方差也只有晴天外景的 1/10，按全局百分位会整段误杀。
BLUR_REL = 0.35                 # 低于本段中位数的 35%：晃动 / 失焦造成的突降
BLUR_ABS = 15                   # 低于这个绝对值：不管什么场景都是糊的
COLS, ROWS, TW, TH = 4, 5, 320, 180


def grab(path, t, w, h, thumb):
    """seek 到 t 之前最近的关键帧抽一帧：一份灰度小图打分，一份缩略图存盘。"""
    head = ["ffmpeg", "-v", "error", "-skip_frame", "nokey", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1"]
    raw = subprocess.run(head + ["-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    if len(raw) < w * h:
        return None
    subprocess.run(head + ["-y", "-vf", "scale=320:-2", thumb])
    img = np.frombuffer(raw[: w * h], np.uint8).reshape(h, w).astype(np.float32)
    lap = (-4 * img[1:-1, 1:-1] + img[:-2, 1:-1] + img[2:, 1:-1]
           + img[1:-1, :-2] + img[1:-1, 2:])
    return float(lap.var()), float(img.mean())


def judge(rows):
    """就地给每帧补 score / bad（见模块说明），返回 rows。"""
    if not rows:
        return rows
    order = np.argsort([r["sharpness"] for r in rows])
    pct = np.empty(len(rows))
    pct[order] = np.linspace(0, 1, len(rows)) if len(rows) > 1 else [1.0]
    per_clip = {}
    for r in rows:
        per_clip.setdefault(r["path"], []).append(r["sharpness"])
    median = {p: float(np.median(v)) for p, v in per_clip.items()}
    for r, p in zip(rows, pct):
        b, s = r["brightness"], r["sharpness"]
        expo = 1.0 if DARK <= b <= BRIGHT else max(0.0, 1 - abs(b - (DARK if b < DARK else BRIGHT)) / 40)
        blurry = s < BLUR_ABS or s < BLUR_REL * median[r["path"]]
        r["score"] = round(float(p) * expo, 3)
        r["bad"] = int(blurry or expo < 0.5)
    return rows


def sample_times(dur, every):
    """每个 every 秒窗口取中点；不足一个窗口的短素材取正中间。"""
    ts = [every / 2 + k * every for k in range(int(dur // every))]
    return ts or [dur / 2]


def contact_sheets(rows, thumb_of, out_dir):
    """把缩略图按 clip 顺序拼成 4×5 联系表，坏帧标红框。"""
    from PIL import Image, ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    per = COLS * ROWS
    paths = []
    for k in range(0, len(rows), per):
        sheet = Image.new("RGB", (COLS * TW, ROWS * (TH + 22)), "black")
        draw = ImageDraw.Draw(sheet)
        for i, r in enumerate(rows[k:k + per]):
            x, y = (i % COLS) * TW, (i // COLS) * (TH + 22)
            try:
                im = Image.open(thumb_of(r)).convert("RGB")
                im.thumbnail((TW, TH))
                sheet.paste(im, (x + (TW - im.width) // 2, y + (TH - im.height) // 2))
            except OSError:
                pass
            if r["bad"]:
                draw.rectangle([x, y, x + TW - 1, y + TH - 1], outline="red", width=3)
            draw.text((x + 4, y + TH + 4), f"{r['clip_id']} @{r['t']:.0f}s", fill="white")
        p = os.path.join(out_dir, f"sheet_{k // per + 1:02d}.jpg")
        sheet.save(p, quality=85)
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--every", type=float, default=8.0)
    args = ap.parse_args()
    if not have("ffmpeg"):
        sys.exit("没有 ffmpeg，跳过第 2 步即可（第 5 步照样能跑，只是不按画质挑）")

    thumbs = os.path.join(args.work, "thumbs")
    os.makedirs(thumbs, exist_ok=True)

    def thumb_of(r):
        return os.path.join(thumbs, f"{r['clip_id']}_{float(r['t']):07.2f}.jpg")

    jobs = []
    for r in read_csv(os.path.join(args.work, "inventory.csv")):
        w, h = int(r["width"]), int(r["height"])
        sw = 192 if w >= h else 108
        sh = max(2, round(sw * h / w / 2) * 2)
        for t in sample_times(float(r["duration_s"]), args.every):
            jobs.append({"clip_id": r["clip_id"], "path": r["path"], "t": round(t, 3), "w": sw, "h": sh})
    print(f"抽 {len(jobs)} 帧（每 {args.every:g} 秒 1 帧）…")
    with ThreadPoolExecutor(os.cpu_count() or 4) as ex:
        res = list(ex.map(lambda j: grab(j["path"], j["t"], j["w"], j["h"], thumb_of(j)), jobs))

    rows = [{"clip_id": j["clip_id"], "path": j["path"], "t": j["t"],
             "sharpness": round(v[0], 1), "brightness": round(v[1], 1)}
            for j, v in zip(jobs, res) if v]
    judge(rows)
    write_csv(os.path.join(args.work, "frames.csv"), rows, FIELDS)
    sheets = contact_sheets(rows, thumb_of, os.path.join(args.work, "contact"))

    bad = [r for r in rows if r["bad"]]
    print(f"有效帧 {len(rows)}，其中糊 / 过暗 / 过曝 {len(bad)} 帧（第 5 步会避开）")
    for r in sorted(bad, key=lambda r: r["score"])[:10]:
        print(f"  {r['clip_id']} {os.path.basename(r['path'])} @ {r['t']:.1f}s  "
              f"清晰度 {r['sharpness']:.0f}  亮度 {r['brightness']:.0f}")
    print(f"联系表 {len(sheets)} 张 → {os.path.join(args.work, 'contact')}")


if __name__ == "__main__":
    main()

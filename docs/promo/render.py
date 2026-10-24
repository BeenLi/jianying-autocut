# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""逐帧渲染 promo.html → build/frames/f_00000.jpg …（用本机 Google Chrome，不下载浏览器）

用法: uv run --script render.py [--fps 24] [--only 3,9,16]   # --only：只渲染这些秒，用来检查排版
"""
import argparse
import os
import pathlib

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--fps", type=int, default=24)
ap.add_argument("--duration", type=float, default=60.0)
ap.add_argument("--only", default="")
args = ap.parse_args()

out = HERE / "build" / ("check" if args.only else "frames")
out.mkdir(parents=True, exist_ok=True)
times = [float(x) for x in args.only.split(",")] if args.only else \
        [i / args.fps for i in range(int(args.duration * args.fps))]

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    page.goto((HERE / "promo.html").as_uri())
    page.wait_for_function("window.READY === true")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(500)   # 等图片解码
    for i, t in enumerate(times):
        page.evaluate(f"window.render({t})")
        name = f"t_{t:05.2f}.jpg" if args.only else f"f_{i:05d}.jpg"
        page.screenshot(path=str(out / name), type="jpeg", quality=92)
        if not args.only and i % 240 == 0:
            print(f"{i}/{len(times)}", flush=True)
    browser.close()
print(f"{len(times)} 帧 → {out}")

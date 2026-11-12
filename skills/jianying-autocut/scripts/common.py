"""各步脚本共用的小工具：路径、CSV 读写、本机剪映版本探测。"""
import csv
import json
import os
import plistlib
import shutil
import subprocess

US = 1_000_000  # 1 秒 = 1,000,000 微秒

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".mxf"}
JIANYING_APP = "/Applications/VideoFusion-macOS.app"
DRAFTS_DIR = os.path.expanduser(
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft")


def have(cmd):
    return shutil.which(cmd) is not None


def default_work(folder):
    """工作目录默认放在素材目录下，跟着素材走。"""
    return os.path.join(os.path.abspath(os.path.expanduser(folder)), "_autocut")


_MISSING = object()


def load_json(path, default=_MISSING, kind=None):
    """读 JSON 文件。文件不存在时返回 default（没给 default 就退出并说明）；JSON 写坏了、或顶层类型
    不是 kind（dict / list）时，退出并给出文件名和第几行第几列，免得一长串 traceback。"""
    if not os.path.exists(path):
        if default is not _MISSING:
            return default
        raise SystemExit(f"{path} 不存在")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} 不是合法的 JSON：第 {e.lineno} 行第 {e.colno} 列，{e.msg}。改好再跑。")
    if kind is not None and not isinstance(data, kind):
        want = {dict: "对象 {…}", list: "列表 […]"}.get(kind, kind.__name__)
        raise SystemExit(f"{path} 的最外层应该是{want}")
    return data


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def jianying_running():
    """剪映主进程（托盘助手 VideoFusion-macOSTrayHelper 不算）。"""
    r = subprocess.run(["pgrep", "-x", "VideoFusion-macOS"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def detect_versions(drafts_dir=DRAFTS_DIR):
    """坑 1：从本机剪映自己写过的草稿里读真实版本号，不硬编码。

    剪映 11.6 打开后会把每个草稿的 draft_meta_info.json 加密，
    但草稿根目录的 root_meta_info.json 仍是明文，里面每条记录带 draft_new_version。
    取最近修改过、且版本号非空的那条。
    """
    root_meta = os.path.join(drafts_dir, "root_meta_info.json")
    with open(root_meta, encoding="utf-8") as f:
        store = json.load(f).get("all_draft_store", [])
    versioned = [d for d in store if d.get("draft_new_version")]
    if not versioned:
        raise RuntimeError(
            f"{root_meta} 里没有任何带 draft_new_version 的草稿。"
            "先在剪映里随便新建并保存一个草稿，再重跑。")
    latest = max(versioned, key=lambda d: d.get("tm_draft_modified", 0))
    with open(os.path.join(JIANYING_APP, "Contents/Info.plist"), "rb") as f:
        app_version = plistlib.load(f)["CFBundleShortVersionString"]
    return {"new_version": latest["draft_new_version"], "app_version": app_version,
            "from_draft": latest.get("draft_name", "")}

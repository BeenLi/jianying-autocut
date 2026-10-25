"""各步脚本共用的小工具：路径、CSV 读写、本机剪映版本探测、MiMo 报错归类。"""
import csv
import json
import os
import plistlib
import re
import shutil
import subprocess

US = 1_000_000  # 1 秒 = 1,000,000 微秒

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".mxf"}
JIANYING_APP = "/Applications/VideoFusion-macOS.app"
DRAFTS_DIR = os.path.expanduser(
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft")
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# video-understanding 收录在仓库 vendor/ 下（MIT，来自 zenstory-ai/video-recap-skills）
UNDERSTAND_CLI = os.path.join(SKILL_DIR, "vendor", "video-understanding", "scripts", "understand.py")

RECHARGE_HINT = (
    "MiMo 不可用（未配置 key、余额不足或已欠费）。\n"
    "  · 请到小米 MiMo 开放平台控制台充值，或获取 key 后执行 export MIMO_API_KEY=…\n"
    "  · 不想用 MiMo：加 --no-understanding，改由 Claude 看 contact/ 联系表写故事脚本")
_RECHARGE_WORDS = re.compile(r"余额|欠费|充值|insufficient|balance|quota|credit|arrear|payment", re.I)


def have(cmd):
    return shutil.which(cmd) is not None


def default_work(folder):
    """工作目录默认放在素材目录下，跟着素材走。"""
    return os.path.join(os.path.abspath(os.path.expanduser(folder)), "_autocut")


def classify_mimo_error(text, status):
    """把 MiMo 报错归成五类：recharge / bad_key / bad_model / rate_limit / other。

    余额判断优先：有些网关欠费时也回 401/403，但文本里会带「余额 / balance」。
    """
    text = text or ""
    if status == 402 or _RECHARGE_WORDS.search(text):
        return "recharge"
    if re.search(r"unsupported model|model.*not (found|exist|support)", text, re.I):
        return "bad_model"
    # 日志尾巴里有行号、场景号，不能见 "401" 就判 key 无效：只认 HTTP 状态的写法
    if status == 401 or re.search(r"HTTP(?: Error)?:? ?401\b|\(401\)|\b401 Unauthorized|Unauthorized", text):
        return "bad_key"
    if status == 429 or re.search(r"429|too many requests|rate limit|限流", text, re.I):
        return "rate_limit"
    return "other"


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

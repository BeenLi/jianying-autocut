# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""宣传片素材筛选：逐张缩略图问 MiMo「有没有能认出来的人」，结果写 faces.json（只在本地，不进仓库）。"""
import base64, json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

thumbs, out = sys.argv[1], sys.argv[2]
key = os.environ["MIMO_API_KEY"]
model = os.environ.get("MIMO_MODEL", "mimo-v2.6-flash")
cache = json.load(open(out)) if os.path.exists(out) else {}
todo = [f for f in sorted(os.listdir(thumbs)) if f.endswith(".jpg") and f not in cache]
Q = "这张截图里有没有能看出是谁的人（正脸、侧脸、清楚的人物）？只回答一个字：有 / 无"

def ask(f):
    img = base64.b64encode(open(os.path.join(thumbs, f), "rb").read()).decode()
    body = {"model": model, "max_completion_tokens": 5, "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
                {"type": "text", "text": Q}]}]}
    req = urllib.request.Request("https://api.xiaomimimo.com/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "api-key": key})
    for _ in range(3):
        try:
            t = json.load(urllib.request.urlopen(req, timeout=60))["choices"][0]["message"]["content"]
            return f, ("无" not in t)          # 拿不准一律当「有人」
        except Exception:
            pass
    return f, True

with ThreadPoolExecutor(8) as ex:
    for f, has in ex.map(ask, todo):
        cache[f] = has
json.dump(cache, open(out, "w"), ensure_ascii=False, indent=0)
print(f"{len(cache)} 张：有人 {sum(cache.values())}，纯风景 {len(cache) - sum(cache.values())}")

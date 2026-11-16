"""页面脚本测试：用 node 在假 DOM / 假 db 上跑 shoot_plan_page.html 的脚本（没装 node 就跳过）。"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "skills/jianying-autocut/assets/shoot_plan_page.html"


@pytest.mark.skipif(shutil.which("node") is None, reason="没有 node")
@pytest.mark.parametrize("h", sorted((ROOT / "tests/page").glob("*.js")), ids=lambda p: p.stem)
def test_page_harness(h):
    r = subprocess.run(["node", str(h), str(PAGE)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr

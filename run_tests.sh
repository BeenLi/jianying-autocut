#!/bin/sh
# 跑全部测试（依赖与 build.py 头部保持一致）
cd "$(dirname "$0")" && exec uv run -q --with pytest --with numpy --with pillow --with pymediainfo \
  --with "pyJianYingDraft @ git+https://github.com/aoguai/pyJianYingDraft@69cee12ae3f7442416df16acdf368ae574764811" \
  pytest tests -q "$@"

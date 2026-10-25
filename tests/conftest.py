import os
import plistlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "jianying-autocut", "scripts"))


@pytest.fixture(autouse=True)
def fake_jianying_app(tmp_path, monkeypatch):
    """测试不读本机 /Applications 里的剪映：换成临时目录里的假 Info.plist（CI 上没装剪映）。"""
    import common
    app = tmp_path / "VideoFusion-macOS.app"
    (app / "Contents").mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": "11.6.0"}, f)
    monkeypatch.setattr(common, "JIANYING_APP", str(app))

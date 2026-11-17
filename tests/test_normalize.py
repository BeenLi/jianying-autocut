import os
import shutil
import subprocess

import pytest

import loudness
import normalize as nz
from loudness import Cache
from normalize import copy_names, normalize

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="没有 ffmpeg")

# 约 -28 LUFS 的 220Hz 正弦，2s / 5s / 8s 处各有一个 20ms、-6 dBFS 的尖峰：要提 12 dB，纯线性会把尖峰顶爆
EXPR = ("0.056*sin(2*PI*220*t)+0.5*sin(2*PI*1000*t)*"
        "(between(t,2,2.02)+between(t,5,5.02)+between(t,8,8.02))")


def _src(tmp_path, name="vo.wav", dur=10.0):
    p = tmp_path / "src" / name
    p.parent.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-nostats", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"aevalsrc='{EXPR}':s=48000:d={dur}", str(p)], check=True)
    return str(p)


@needs_ffmpeg
def test_normalize_hits_target_with_peaks(tmp_path):
    src = _src(tmp_path)
    assert loudness.measure(src)["i"] < -24
    out, info = normalize(src, str(tmp_path / "n"), Cache(str(tmp_path)))
    m = loudness.measure(out)
    assert abs(m["i"] + 16) <= 0.7 and m["tp"] <= -1.5
    assert info == {"type": "dynamic", "short": False}
    assert out == str(tmp_path / "n" / "vo.wav")


@needs_ffmpeg
def test_short_file_flagged(tmp_path):
    out, info = normalize(_src(tmp_path, dur=2.5), str(tmp_path / "n"), Cache(str(tmp_path)))
    assert info["short"] and info["type"] == "linear" and os.path.exists(out)


@needs_ffmpeg
def test_cache_skips_second_run_and_reruns_on_change(tmp_path, monkeypatch):
    src = _src(tmp_path)
    runs = []
    real = subprocess.run
    monkeypatch.setattr(nz.subprocess, "run", lambda *a, **k: runs.append(a) or real(*a, **k))
    cache, out_dir = Cache(str(tmp_path)), str(tmp_path / "n")
    out, info = normalize(src, out_dir, cache)
    assert len(runs) == 2
    runs.clear()
    assert normalize(src, out_dir, Cache(str(tmp_path))) == (out, info) and runs == []   # 缓存落盘，新 Cache 也命中
    st = os.stat(src)
    os.utime(src, (st.st_atime, st.st_mtime + 10))
    normalize(src, out_dir, cache)
    assert len(runs) == 2
    runs.clear()
    os.remove(out)
    normalize(src, out_dir, cache)
    assert len(runs) == 2 and os.path.exists(out)


def test_copy_names_dedupes_stably():
    assert copy_names(["/b/x.wav", "/a/x.m4a", "/a/y.m4a"]) == {"/a/x.m4a": "x", "/b/x.wav": "x_n2", "/a/y.m4a": "y"}
    assert copy_names(["/c/x.mp3", "/a/x.m4a", "/b/x.wav"])["/c/x.mp3"] == "x_n3"


def test_ffmpeg_failure_raises(tmp_path, monkeypatch):
    src = tmp_path / "vo.m4a"
    src.write_bytes(b"0")
    monkeypatch.setattr(nz.subprocess, "run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "Invalid data found"))
    with pytest.raises(subprocess.CalledProcessError):
        normalize(str(src), str(tmp_path / "n"), Cache(str(tmp_path)))
    assert not os.path.exists(tmp_path / "n" / "vo.wav")

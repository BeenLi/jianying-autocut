# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///
"""合成宣传片配乐（原创、无版权顾虑）：C–G–Am–F 循环，柔和长音铺底 + 八分音符分解和弦，60 秒。

用法: uv run --script music.py build/music.wav [--seconds 60]
"""
import sys
import wave

import numpy as np

out = sys.argv[1]
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--seconds" else 60.0
SR, BPM = 44100, 96
beat = 60 / BPM
n = int(SR * SECONDS)
t = np.arange(n) / SR
mix = np.zeros((n, 2))

NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
hz = lambda name, octave: 440.0 * 2 ** ((NOTE[name] + 12 * (octave - 4) - 9) / 12)
CHORDS = [("C", ["C", "E", "G"]), ("G", ["G", "B", "D"]), ("A", ["A", "C", "E"]), ("F", ["F", "A", "C"])]
bar = 4 * beat


def env(length, attack, release):
    k = np.ones(length)
    a, r = int(attack * SR), int(release * SR)
    k[:a] = np.linspace(0, 1, a)
    k[-r:] *= np.linspace(1, 0, r)
    return k


for b in range(int(SECONDS / bar) + 1):
    root, tri = CHORDS[b % 4]
    s0 = int(b * bar * SR)
    L = min(int(bar * SR), n - s0)
    if L <= 0:
        break
    tt = np.arange(L) / SR
    # 铺底：三和弦长音，带一点失谐让声音更厚
    pad = sum(np.sin(2 * np.pi * hz(x, 3 if x == root else 4) * tt * d)
              for x in tri for d in (0.997, 1.003)) / 6
    pad += 0.5 * np.sin(2 * np.pi * hz(root, 2) * tt)          # 低音根音
    pad *= env(L, 0.6, 0.6) * 0.22
    mix[s0:s0 + L, 0] += pad
    mix[s0:s0 + L, 1] += pad
    # 分解和弦：八分音符，左右轻微交替
    seq = [tri[0], tri[1], tri[2], tri[1]] * 2
    for i, x in enumerate(seq):
        p0 = s0 + int(i * beat / 2 * SR)
        PL = min(int(beat * 1.5 * SR), n - p0)
        if PL <= 0:
            continue
        pt = np.arange(PL) / SR
        f = hz(x, 5)
        pluck = (np.sin(2 * np.pi * f * pt) + 0.3 * np.sin(4 * np.pi * f * pt)) * np.exp(-pt * 5.5) * 0.10
        pan = 0.35 if i % 2 else -0.35
        mix[p0:p0 + PL, 0] += pluck * (1 - pan)
        mix[p0:p0 + PL, 1] += pluck * (1 + pan)

# 整体淡入淡出 + 归一化到 -3 dBFS
fade = np.ones(n)
fade[: int(1.5 * SR)] = np.linspace(0, 1, int(1.5 * SR))
fade[-int(3 * SR):] = np.linspace(1, 0, int(3 * SR))
mix *= fade[:, None]
mix /= np.abs(mix).max() / 0.7
pcm = (mix * 32767).astype("<i2")
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"{SECONDS:.0f}s → {out}")

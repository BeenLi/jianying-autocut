from build import bgm_segments, parse_bgm
from common import US


def test_bgm_segments_loop_and_trim():
    assert bgm_segments(100 * US, 0, 250 * US) == [(0, 0, 100 * US), (100 * US, 0, 100 * US), (200 * US, 0, 50 * US)]
    assert bgm_segments(400 * US, 0, 250 * US) == [(0, 0, 250 * US)]


def test_bgm_segments_drop_tiny_tail():
    # 循环后剩下 <1s 的尾巴并不好听：并进上一段的空间里截掉，最后一段补到终点
    segs = bgm_segments(100 * US, 0, 200 * US + US // 2)
    assert segs[-1][0] + segs[-1][2] == 200 * US + US // 2 and all(d >= US for _, _, d in segs)


def test_parse_bgm():
    assert parse_bgm("/a/b.mp3") == {"path": "/a/b.mp3", "gain": 0.3, "fade": 1.5}
    assert parse_bgm("/a/b.mp3:0.5:2") == {"path": "/a/b.mp3", "gain": 0.5, "fade": 2.0}

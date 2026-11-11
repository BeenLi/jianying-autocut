import json
import os
from types import SimpleNamespace as NS

from transcribe import speech_from_segments, transcribe_clips


def _seg(start, end, text, no_speech=0.1):
    return NS(start=start, end=end, text=text, no_speech_prob=no_speech)


class FakeModel:
    def __init__(self, by_path):
        self.by_path, self.calls = by_path, []

    def transcribe(self, path, **kw):
        self.calls.append((path, kw))
        return iter(self.by_path.get(path, [])), NS(language="zh")


def _row(cid, audio="True"):
    return {"clip_id": cid, "path": f"/x/{cid}.mp4", "has_audio": audio}


def test_speech_keeps_sentences_and_drops_noise_and_blanks():
    out = speech_from_segments([_seg(1.234, 2.5, " 到了 "), _seg(3, 4, "  "), _seg(5, 6, "幻听", no_speech=0.9)])
    assert out == [{"start": 1.234, "end": 2.5, "text": "到了"}]


def test_transcribes_only_clips_with_audio(tmp_path):
    out = str(tmp_path / "speech.json")
    model = FakeModel({"/x/c001.mp4": [_seg(0, 1, "你好")]})
    result = transcribe_clips([_row("c001"), _row("c002", "False")], model, out)
    assert result == {"c001": [{"start": 0.0, "end": 1.0, "text": "你好"}], "c002": []}
    assert [p for p, _ in model.calls] == ["/x/c001.mp4"]
    assert json.load(open(out, encoding="utf-8")) == result


def test_resume_skips_clips_already_done(tmp_path):
    out = str(tmp_path / "speech.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"c001": [{"start": 0, "end": 1, "text": "旧"}]}, f)
    model = FakeModel({})
    result = transcribe_clips([_row("c001"), _row("c002")], model, out)
    assert [p for p, _ in model.calls] == ["/x/c002.mp4"]
    assert result["c001"][0]["text"] == "旧"


def test_force_redoes_everything(tmp_path):
    out = str(tmp_path / "speech.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"c001": []}, f)
    model = FakeModel({"/x/c001.mp4": [_seg(0, 1, "新")]})
    assert transcribe_clips([_row("c001")], model, out, force=True)["c001"][0]["text"] == "新"


def test_failed_clip_is_reported_and_others_continue(tmp_path, capsys):
    class Boom(FakeModel):
        def transcribe(self, path, **kw):
            if "c001" in path:
                raise RuntimeError("坏文件")
            return super().transcribe(path, **kw)
    out = str(tmp_path / "speech.json")
    result = transcribe_clips([_row("c001"), _row("c002")], Boom({"/x/c002.mp4": [_seg(0, 1, "好")]}), out)
    assert "c001" not in result and result["c002"][0]["text"] == "好"     # 失败的不缓存，重跑时会再试
    assert "c001" in capsys.readouterr().out


def test_language_and_context_reach_whisper(tmp_path):
    model = FakeModel({})
    transcribe_clips([_row("c001")], model, str(tmp_path / "s.json"), language="zh", context="庐山徒步")
    kw = model.calls[0][1]
    assert kw["language"] == "zh" and "庐山徒步" in kw["initial_prompt"] and kw["vad_filter"] is True
    assert kw["condition_on_previous_text"] is False
    assert os.path.exists(tmp_path / "s.json")


# 下面的数值来自枸杞岛实测：真话 no_speech 0.02–0.20，幻听 0.60
def test_drops_prompt_echo():
    """Whisper 在安静画面上会把提示词原样念出来（实测：日落素材转出「舟山枸杞岛旅行，带着小狗格桑。」）。"""
    prompt = "以下是普通话的句子。舟山枸杞岛旅行，带着小狗格桑。"
    out = speech_from_segments([_seg(0, 5, "舟山枸杞岛旅行，带着小狗格桑。"), _seg(5, 9, "格桑，你妈妈回来了")],
                               prompt=prompt)
    assert [s["text"] for s in out] == ["格桑，你妈妈回来了"]


def test_drops_lines_past_clip_end():
    out = speech_from_segments([_seg(1, 3, "到了"), _seg(16, 28, "江湖")], duration=11.1)
    assert [s["text"] for s in out] == ["到了"]


def test_drops_text_repeated_many_times_in_one_clip():
    segs = [_seg(i, i + 1, "江湖") for i in range(4)] + [_seg(5, 6, "北京")]
    assert [s["text"] for s in speech_from_segments(segs)] == ["北京"]


def test_no_speech_threshold_drops_measured_hallucination():
    out = speech_from_segments([_seg(0, 5, "一句话", no_speech=0.60), _seg(5, 6, "真话", no_speech=0.20)])
    assert [s["text"] for s in out] == ["真话"]


# ---------- 旁白入口 ----------

def test_dedupe_false_keeps_retakes():
    segs = [_seg(i, i + 1, "凌晨四点出发") for i in range(3)]
    assert len(speech_from_segments(segs, dedupe=False)) == 3
    assert speech_from_segments(segs) == []


def test_dedupe_false_keeps_prompt_echo_like_line():
    segs = [_seg(0, 1, "庐山两日徒步")]
    assert speech_from_segments(segs, prompt="以下是普通话的句子。庐山两日徒步") == []
    assert len(speech_from_segments(segs, prompt="以下是普通话的句子。庐山两日徒步", dedupe=False)) == 1


def test_words_attached():
    s = _seg(0, 1, "你好")
    s.words = [NS(start=0.1, end=0.4, word="你好")]
    assert speech_from_segments([s], words=True)[0]["words"] == [{"start": 0.1, "end": 0.4, "word": "你好"}]
    assert "words" not in speech_from_segments([s])[0]


def test_narration_files_sorted_and_filtered(tmp_path):
    from transcribe import narration_files
    for n in ("02.m4a", "01.wav", "._01.wav", "a.txt"):
        (tmp_path / n).write_bytes(b"")
    assert narration_files(str(tmp_path)) == [str(tmp_path / "01.wav"), str(tmp_path / "02.m4a")]
    assert narration_files(str(tmp_path / "02.m4a")) == [str(tmp_path / "02.m4a")]


def test_assign_file_ids_stable():
    from transcribe import assign_file_ids
    assert assign_file_ids(["/b", "/c", "/a"], {"n1": "/a", "n2": "/b"}) == {"n1": "/a", "n2": "/b", "n3": "/c"}
    assert assign_file_ids(["/x", "/y"], {}) == {"n1": "/x", "n2": "/y"}

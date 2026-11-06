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

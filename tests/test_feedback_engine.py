import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import feedback, tts


class FakeEngine:
    sample_rate = 22050

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> bytes:
        if self.fail:
            raise RuntimeError("piper упал")
        self.spoken.append(text)
        return b"\x00\x01" * 10


def _voice(tmp_path: Path, name: str = "ru_RU-denis-medium", rate: int = 22050) -> Path:
    model = tmp_path / f"{name}.onnx"
    model.write_bytes(b"onnx")
    (tmp_path / f"{name}.onnx.json").write_text(json.dumps({"audio": {"sample_rate": rate}}), encoding="utf-8")
    return model


def test_engine_is_tried_first(monkeypatch):
    engine = FakeEngine()
    played: list[tuple[bytes, int]] = []
    monkeypatch.setattr(feedback, "_engine", engine)
    monkeypatch.setattr(feedback, "_play_pcm", lambda pcm, rate: played.append((pcm, rate)))
    with patch("audioreferent.feedback._play_recorded") as recorded:
        feedback.speak("Участник Иванов не найден", fallback="Не удалось выполнить команду")
    assert engine.spoken == ["Участник Иванов не найден"]
    assert played and played[0][1] == 22050
    recorded.assert_not_called()


def test_engine_failure_falls_back_to_recordings(monkeypatch):
    monkeypatch.setattr(feedback, "_engine", FakeEngine(fail=True))
    with patch("audioreferent.feedback._play_recorded", return_value=True) as recorded:
        feedback.speak("Событие не найдено")
    recorded.assert_called_once_with("Событие не найдено")


def test_configure_disables_engine_without_binary_or_voice(monkeypatch, tmp_path):
    binary = tmp_path / "piper"
    cfg = SimpleNamespace(
        tts_engine="piper", piper_binary_path=str(binary), piper_voices_dir=str(tmp_path), piper_voice="ru_RU-denis-medium"
    )
    feedback.configure(cfg)  # нет ни программы, ни голоса
    assert feedback.engine_name() == "recordings"

    binary.write_bytes(b"#!/bin/sh\n")
    feedback.configure(cfg)  # программа есть, голоса нет
    assert feedback.engine_name() == "recordings"

    _voice(tmp_path, rate=16000)
    feedback.configure(cfg, warm_up=False)
    assert feedback.engine_name() == "piper"
    assert feedback._engine.sample_rate == 16000  # из <voice>.onnx.json
    feedback._engine = None


def test_configure_respects_recordings_engine():
    feedback.configure(SimpleNamespace(tts_engine="recordings", piper_binary_path=None, piper_voices_dir=None, piper_voice="x"))
    assert feedback.engine_name() == "recordings"


def test_resolve_voice_and_available_voices(tmp_path):
    _voice(tmp_path, "ru_RU-denis-medium")
    _voice(tmp_path, "ru_RU-irina-medium")
    (tmp_path / "broken.onnx").write_bytes(b"onnx")  # без .json — не голос
    assert tts.resolve_voice("ru_RU-irina-medium", str(tmp_path)).endswith("ru_RU-irina-medium.onnx")
    assert tts.resolve_voice("ru_RU-ruslan-medium", str(tmp_path)) is None
    assert tts.available_voices(str(tmp_path)) == ["ru_RU-denis-medium", "ru_RU-irina-medium"]


def test_piper_engine_runs_binary_with_output_raw(tmp_path):
    voice = _voice(tmp_path)
    engine = tts.PiperEngine("/usr/bin/piper", str(voice))
    completed = SimpleNamespace(stdout=b"\x01\x02\x03\x04", stderr=b"")
    with patch("audioreferent.tts.subprocess.run", return_value=completed) as run:
        assert engine.synthesize("Слушаю") == b"\x01\x02\x03\x04"
        assert engine.synthesize("Слушаю") == b"\x01\x02\x03\x04"  # из кеша, без второго запуска
    run.assert_called_once()
    argv = run.call_args[0][0]
    assert argv[0] == "/usr/bin/piper" and "--output-raw" in argv and str(voice) in argv
    assert run.call_args[1]["input"] == "Слушаю".encode("utf-8")

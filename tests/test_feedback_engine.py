import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import feedback, tts


class FakeEngine:
    sample_rate = 48000

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> bytes:
        if self.fail:
            raise RuntimeError("модель не загрузилась")
        self.spoken.append(text)
        return b"\x00\x01" * 10


def test_engine_is_tried_first_and_uses_stress_marks(monkeypatch):
    engine = FakeEngine()
    played: list[tuple[bytes, int]] = []
    monkeypatch.setattr(feedback, "_engine", engine)
    monkeypatch.setattr(feedback, "_play_pcm", lambda pcm, rate: played.append((pcm, rate)))
    with patch("audioreferent.feedback._play_recorded") as recorded:
        feedback.speak("Команда не распознана", fallback="Не удалось выполнить команду")
    assert engine.spoken == ["Команда не расп+ознана"]  # явное ударение
    assert played and played[0][1] == 48000
    recorded.assert_not_called()


def test_engine_failure_falls_back_to_recordings(monkeypatch):
    monkeypatch.setattr(feedback, "_engine", FakeEngine(fail=True))
    with patch("audioreferent.feedback._play_recorded", return_value=True) as recorded:
        feedback.speak("Событие не найдено")
    recorded.assert_called_once_with("Событие не найдено")


def test_configure_disables_engine_without_model_or_torch(monkeypatch, tmp_path):
    cfg = SimpleNamespace(tts_engine="silero", silero_model_path=str(tmp_path / "missing.pt"), silero_speaker="xenia")
    feedback.configure(cfg)
    assert feedback.engine_name() == "recordings"

    model = tmp_path / "v4_ru.pt"
    model.write_bytes(b"PK")
    cfg.silero_model_path = str(model)
    with patch("audioreferent.tts.torch_available", return_value=False):
        feedback.configure(cfg)
    assert feedback.engine_name() == "recordings"

    with patch("audioreferent.tts.torch_available", return_value=True), patch.object(
        tts.SileroEngine, "warm_up", lambda self, texts: None
    ):
        feedback.configure(cfg)
    assert feedback.engine_name() == "silero"
    assert feedback._engine.speaker == "xenia"
    feedback._engine = None


def test_configure_respects_recordings_engine():
    feedback.configure(SimpleNamespace(tts_engine="recordings", silero_model_path=None, silero_speaker="xenia"))
    assert feedback.engine_name() == "recordings"


def test_resolve_model_path_prefers_configured_file(tmp_path):
    model = tmp_path / "m.pt"
    model.write_bytes(b"PK")
    assert tts.resolve_model_path(str(model)) == str(model)
    assert tts.resolve_model_path(str(tmp_path / "absent.pt")) is None

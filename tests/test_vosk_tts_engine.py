import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import vosk_tts_engine as engine


def test_apply_stress_marks_known_words_only():
    stress = {"будько": "будьк+о", "шапошников": "шапошн+иков"}
    assert engine.apply_stress("Участник Будько не найден", stress) == "Участник Будьк+о не найден"
    assert engine.apply_stress("будько и шилкин", stress) == "будьк+о и шилкин"  # незнакомые не трогаем
    assert engine.apply_stress("ШАПОШНИКОВ", stress) == "Шапошн+иков"  # регистр не мешает
    assert engine.apply_stress("текст без фамилий", stress) == "текст без фамилий"
    assert engine.apply_stress("Будько", {}) == "Будько"


def test_resolve_model_path_prefers_configured_dir(tmp_path):
    model = tmp_path / "vosk-model-tts-ru-0.9-multi"
    model.mkdir()
    assert engine.resolve_model_path(str(model)) == str(model)
    assert engine.resolve_model_path(str(tmp_path / "нет")) is None


class _FakeAudio:
    def __init__(self, data: bytes):
        self._data = data

    def tobytes(self) -> bytes:
        return self._data


def _engine_with_fake_synth(tmp_path, monkeypatch, *, stress=None):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    eng = engine.VoskTtsEngine(str(tmp_path), speaker=2, speech_rate=1.1, stress=stress)
    calls: list[tuple[str, int, float]] = []

    class FakeSynth:
        def synth_audio(self, text, speaker_id=0, speech_rate=1.0, **kwargs):
            calls.append((text, speaker_id, speech_rate))
            return _FakeAudio(b"\x07\x08" * 20)

    eng._synth = FakeSynth()
    return eng, calls


def test_synthesize_passes_voice_rate_and_stress_and_caches(tmp_path, monkeypatch):
    eng, calls = _engine_with_fake_synth(tmp_path, monkeypatch, stress={"будько": "будьк+о"})
    assert eng.synthesize("Участник Будько не найден") == b"\x07\x08" * 20
    assert calls == [("Участник Будьк+о не найден", 2, 1.1)]
    eng.synthesize("Участник Будько не найден")
    assert len(calls) == 1  # из кеша в памяти

    # новый движок с теми же настройками берёт фразу с диска, не синтезируя
    eng2, calls2 = _engine_with_fake_synth(tmp_path, monkeypatch, stress={"будько": "будьк+о"})
    assert eng2.synthesize("Участник Будько не найден") == b"\x07\x08" * 20
    assert calls2 == []


def test_onnx_threads_restores_the_original_session_class():
    fake_ort = SimpleNamespace(InferenceSession=object, SessionOptions=lambda: SimpleNamespace())
    original = fake_ort.InferenceSession
    with patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        with engine._onnx_threads(2):
            assert fake_ort.InferenceSession is not original
        assert fake_ort.InferenceSession is original
        with engine._onnx_threads(0):  # 0 — не вмешиваемся вовсе
            assert fake_ort.InferenceSession is original

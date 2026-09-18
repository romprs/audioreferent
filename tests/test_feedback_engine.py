import json
import sys
import wave
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


def test_configure_substitutes_missing_voice_instead_of_disabling(monkeypatch, tmp_path):
    binary = tmp_path / "piper"
    binary.write_bytes(b"#!/bin/sh\n")
    _voice(tmp_path, "ru_RU-irina-medium")
    cfg = SimpleNamespace(
        tts_engine="piper", piper_binary_path=str(binary), piper_voices_dir=str(tmp_path), piper_voice="ru_RU-ruslan-medium"
    )
    feedback.configure(cfg, warm_up=False)
    assert feedback.engine_name() == "piper"
    assert feedback.voice_name() == "ru_RU-irina-medium"  # запрошенный не установлен -> умолчание
    feedback._engine = None


def test_no_espeak_when_recordings_exist(monkeypatch):
    monkeypatch.setattr(feedback, "_engine", None)
    with patch("audioreferent.feedback._play_recorded", return_value=False), patch(
        "audioreferent.feedback._recordings_available", return_value=True
    ), patch("audioreferent.feedback.subprocess.run") as run:
        feedback.speak("Слушаю", fallback=None)
    run.assert_not_called()  # ни espeak-ng, ни espeak


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


def test_piper_engine_uses_a_long_lived_process(tmp_path):
    """Фраза уходит строкой JSON в уже запущенный piper, ответ читается из
    файла: перезапуск процесса стоил бы ~0,4 с на загрузку модели."""
    voice = _voice(tmp_path)
    engine = tts.PiperEngine("/usr/bin/piper", str(voice))
    written: list[bytes] = []

    class FakeProcess:
        def __init__(self):
            self.stdin = SimpleNamespace(write=self._write, flush=lambda: None, close=lambda: None)
            self.terminated = False

        def _write(self, data: bytes) -> None:
            written.append(data)
            request = json.loads(data.decode("utf-8"))
            path = Path(request["output_file"])
            with wave.open(str(path), "wb") as wav:  # «синтезированный» ответ
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(22050)
                wav.writeframes(b"\x01\x02" * 100)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    process = FakeProcess()
    with patch("audioreferent.tts.subprocess.Popen", return_value=process) as popen, patch(
        "audioreferent.tts.subprocess.run"
    ) as run:
        assert engine.synthesize("Слушаю") == b"\x01\x02" * 100
        assert engine.synthesize("Отменено") == b"\x01\x02" * 100
        assert engine.synthesize("Слушаю") == b"\x01\x02" * 100  # из кеша
    popen.assert_called_once()  # процесс один на все фразы
    assert "--json-input" in popen.call_args[0][0]
    run.assert_not_called()  # разовый запуск не понадобился
    assert [json.loads(w.decode("utf-8"))["text"] for w in written] == ["Слушаю", "Отменено"]
    engine.close()
    assert process.terminated


def test_piper_engine_falls_back_to_one_shot_when_process_fails(tmp_path):
    voice = _voice(tmp_path)
    engine = tts.PiperEngine("/usr/bin/piper", str(voice))
    completed = SimpleNamespace(stdout=b"\x05\x06", stderr=b"")
    with patch("audioreferent.tts.subprocess.Popen", side_effect=OSError("no exec")), patch(
        "audioreferent.tts.subprocess.run", return_value=completed
    ) as run:
        assert engine.synthesize("Слушаю") == b"\x05\x06"
    run.assert_called_once()
    assert "--output-raw" in run.call_args[0][0]


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

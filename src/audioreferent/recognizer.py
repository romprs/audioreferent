"""Обёртка над Vosk: загрузка модели и потоковое распознавание речи."""

from __future__ import annotations

import json
import os
from pathlib import Path

import vosk

vosk.SetLogLevel(-1)  # не засорять stdout служебными логами Kaldi

DEFAULT_MODEL_LOCATIONS = [
    "/usr/share/vosk-model-small-ru",
    "/usr/local/share/vosk-model-small-ru",
]


def resolve_model_path(configured_path: str | None) -> str:
    if configured_path:
        return configured_path
    env_path = os.environ.get("VOSK_MODEL_PATH")
    if env_path:
        return env_path
    for candidate in DEFAULT_MODEL_LOCATIONS:
        if Path(candidate).is_dir():
            return candidate
    raise FileNotFoundError(
        "Не найдена модель Vosk. Укажите model_path в конфиге, переменную "
        "окружения VOSK_MODEL_PATH, либо установите модель в один из "
        f"путей: {', '.join(DEFAULT_MODEL_LOCATIONS)}"
    )


class SpeechRecognizer:
    def __init__(self, model_path: str, sample_rate: int):
        self._model = vosk.Model(model_path)
        self._sample_rate = sample_rate
        self._recognizer = vosk.KaldiRecognizer(self._model, sample_rate)

    def reset(self) -> None:
        self._recognizer.Reset()

    def accept_chunk(self, chunk: bytes) -> str | None:
        """Отдаёт чанк движку. Возвращает финальный распознанный текст,
        если Vosk определил конец фразы (по паузе), иначе None."""
        if self._recognizer.AcceptWaveform(chunk):
            text = json.loads(self._recognizer.Result()).get("text", "")
            return text
        return None

    def partial_text(self) -> str:
        return json.loads(self._recognizer.PartialResult()).get("partial", "")

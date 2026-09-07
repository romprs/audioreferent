"""Обёртка над Vosk: загрузка модели и потоковое распознавание речи."""

from __future__ import annotations

import json
import os
from pathlib import Path

import vosk

vosk.SetLogLevel(-1)  # не засорять stdout служебными логами Kaldi

DEFAULT_MODEL_LOCATIONS = [
    # Куда RPM кладёт заранее подготовленную (без rescore/rnnlm, см.
    # README про их несовместимость) полную модель — первый кандидат,
    # чтобы установка из RPM работала сразу без правки конфига.
    "/usr/share/audioreferent/vosk-model",
    "/usr/share/vosk-model-small-ru",
    "/usr/local/share/vosk-model-small-ru",
]

DEFAULT_SPK_MODEL_LOCATIONS = [
    "/usr/share/audioreferent/vosk-model-spk",
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


def resolve_spk_model_path(configured_path: str | None) -> str | None:
    """Как resolve_model_path, но для необязательной spk-модели (проверка
    голоса) — при отсутствии просто возвращает None вместо исключения,
    так что функция без неё работает как раньше."""
    if configured_path:
        return configured_path if Path(configured_path).is_dir() else None
    for candidate in DEFAULT_SPK_MODEL_LOCATIONS:
        if Path(candidate).is_dir():
            return candidate
    default = Path.home() / ".local" / "share" / "vosk" / "vosk-model-spk-0.4"
    return str(default) if default.is_dir() else None


class SpeechRecognizer:
    def __init__(self, model_path: str, sample_rate: int, spk_model_path: str | None = None):
        self._model = vosk.Model(model_path)
        self._sample_rate = sample_rate
        self._recognizer = vosk.KaldiRecognizer(self._model, sample_rate)
        self._last_speaker_vector: list[float] | None = None
        if spk_model_path:
            self._recognizer.SetSpkModel(vosk.SpkModel(spk_model_path))

    def reset(self) -> None:
        self._recognizer.Reset()
        self._last_speaker_vector = None

    def accept_chunk(self, chunk: bytes) -> str | None:
        """Отдаёт чанк движку. Возвращает финальный распознанный текст,
        если Vosk определил конец фразы (по паузе), иначе None. Если
        подключена spk-модель, заодно запоминает x-вектор голоса этой
        фразы (см. last_speaker_vector) — Vosk отдаёт его только вместе
        с финальным результатом, не с промежуточным (partial)."""
        if self._recognizer.AcceptWaveform(chunk):
            result = json.loads(self._recognizer.Result())
            self._last_speaker_vector = result.get("spk")
            return result.get("text", "")
        return None

    def partial_text(self) -> str:
        return json.loads(self._recognizer.PartialResult()).get("partial", "")

    @property
    def last_speaker_vector(self) -> list[float] | None:
        return self._last_speaker_vector

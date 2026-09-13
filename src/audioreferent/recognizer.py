"""Обёртка над Vosk: загрузка модели и потоковое распознавание речи."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import vosk

from .model_overlay import prepare_model_with_endpointing

vosk.SetLogLevel(-1)  # не засорять stdout служебными логами Kaldi

log = logging.getLogger(__name__)

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


#: Режимы определения конца фразы Vosk (сколько тишины после речи ждать,
#: прежде чем выдать финальный результат): short — заметно быстрее отклик
#: на короткие команды, long — для длинной диктовки с паузами.
ENDPOINTING_MODES = ("short", "default", "long")



class SpeechRecognizer:
    def __init__(
        self,
        model_path: str,
        sample_rate: int,
        spk_model_path: str | None = None,
        *,
        endpointing: str = "short",
        end_silence_seconds: float | None = None,
    ):
        # Паузы конца фразы задаются в conf/model.conf самой модели — грузим
        # её через оверлей с укороченными паузами (см.
        # prepare_model_with_endpointing), т.к. API для этого в vosk 0.3.45 нет.
        self._model = vosk.Model(prepare_model_with_endpointing(model_path, end_silence_seconds))
        self._sample_rate = sample_rate
        self._recognizer = vosk.KaldiRecognizer(self._model, sample_rate)
        self._last_speaker_vector: list[float] | None = None
        if spk_model_path:
            self._recognizer.SetSpkModel(vosk.SpkModel(spk_model_path))
        self._configure_endpointing(endpointing, end_silence_seconds)

    def _configure_endpointing(self, endpointing: str, end_silence_seconds: float | None) -> None:
        """Быстрее конец фразы = быстрее ответ: в режиме short Vosk выдаёт
        финальный результат после ~0,5 с тишины вместо ~1 с. Всё в
        try/except: в старых vosk этих методов нет — тогда остаётся
        поведение по умолчанию."""
        modes = getattr(vosk, "EndpointerMode", None)
        try:
            if modes is not None and endpointing in ENDPOINTING_MODES and endpointing != "default":
                mode = modes.ANSWER_SHORT if endpointing == "short" else modes.ANSWER_LONG
                self._recognizer.SetEndpointerMode(mode)
            if end_silence_seconds:
                # (макс. тишина в начале, тишина после уверенной речи, макс. тишина после речи)
                self._recognizer.SetEndpointerDelays(5.0, float(end_silence_seconds), float(end_silence_seconds) * 2)
        except Exception as exc:  # noqa: BLE001 — необязательная настройка
            log.warning("Настройка определения конца фразы недоступна в этой версии vosk: %s", exc)

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

    def finalize(self) -> str:
        """Принудительно завершить фразу и отдать её текст — когда
        промежуточный результат не меняется дольше паузы (см.
        assistant._accept): vosk 0.3.45 не даёт настроить свой детектор
        конца фразы, и ждать его ~1 с после каждой короткой команды долго."""
        result = json.loads(self._recognizer.FinalResult())
        self._last_speaker_vector = result.get("spk")
        return result.get("text", "")

    @property
    def last_speaker_vector(self) -> list[float] | None:
        return self._last_speaker_vector

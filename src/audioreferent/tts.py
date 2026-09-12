"""Синтез речи Silero TTS (модель v4_ru, офлайн, CPU).

Зачем: голосовые ответы помощника должны звучать одним хорошим женским
голосом, включая тексты, которых нельзя записать заранее (например,
фамилия участника, которого не нашли). espeak-ng для этого слишком груб,
заранее записанные фразы — только для фиксированного набора. Silero даёт
~1 с на фразу на CPU при модели в 40 МБ; ударение можно задать явно
знаком «+» перед ударной гласной («расп+ознана»), остальное модель
ставит сама.

Зависимость torch (CPU-сборка) — необязательная: без неё модуль просто
сообщает, что движок недоступен, и feedback.py возвращается к записям.
Модель ищется по DEFAULT_MODEL_LOCATIONS (RPM кладёт её в
/usr/share/audioreferent/silero/) либо по silero_model_path из конфига.

Лицензия моделей Silero — CC BY-NC-SA 4.0 (некоммерческая); для
коммерческого продукта нужна отдельная лицензия от Silero.
"""

from __future__ import annotations

import array
import logging
import threading
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_MODEL_LOCATIONS = [
    "/usr/share/audioreferent/silero/v4_ru.pt",
    str(Path.home() / ".local" / "share" / "audioreferent" / "v4_ru.pt"),
]

#: Голоса модели v4_ru. Первые три — женские.
SPEAKERS = ["xenia", "baya", "kseniya", "aidar", "eugene"]
DEFAULT_SPEAKER = "xenia"
SAMPLE_RATE = 48000


def resolve_model_path(configured_path: str | None) -> str | None:
    if configured_path:
        return configured_path if Path(configured_path).is_file() else None
    for candidate in DEFAULT_MODEL_LOCATIONS:
        if Path(candidate).is_file():
            return candidate
    return None


def torch_available() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:  # noqa: BLE001 — любая проблема импорта = движка нет
        return False
    return True


class SileroEngine:
    """Ленивая загрузка модели (первый вызов ~1-2 с) и синтез PCM16 mono.
    Результаты кешируются по тексту: фиксированные фразы помощника
    синтезируются один раз (см. warm_up), а не при каждом ответе."""

    def __init__(self, model_path: str, *, speaker: str = DEFAULT_SPEAKER, sample_rate: int = SAMPLE_RATE, threads: int = 2):
        self.model_path = model_path
        self.speaker = speaker
        self.sample_rate = sample_rate
        self._threads = threads
        self._model = None
        self._lock = threading.Lock()
        self._cache: dict[str, bytes] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch

        # Не отбирать все ядра у распознавания: Vosk крутится в том же
        # процессе, а синтез короткой фразы и на двух потоках занимает ~1 с.
        torch.set_num_threads(self._threads)
        log.info("Загружаю модель синтеза речи Silero: %s (голос %s)", self.model_path, self.speaker)
        model = torch.package.PackageImporter(self.model_path).load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        self._model = model

    def synthesize(self, text: str) -> bytes:
        """PCM16 mono (self.sample_rate) для текста. Поднимает исключение,
        если torch/модель недоступны — решать, что делать, вызывающему."""
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        with self._lock:
            self._load()
            import torch

            audio = self._model.apply_tts(
                text=text, speaker=self.speaker, sample_rate=self.sample_rate, put_accent=True, put_yo=True
            )
            pcm = array.array("h", audio.clamp(-1, 1).mul(32767).to(torch.int16).tolist()).tobytes()
        self._cache[text] = pcm
        return pcm

    def warm_up(self, texts: Iterable[str]) -> threading.Thread:
        """Синтезировать заданные фразы в фоне, чтобы первый ответ не ждал
        загрузки модели и синтеза. Ошибки — только в журнал."""

        def _run() -> None:
            for text in texts:
                try:
                    self.synthesize(text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Не удалось заранее синтезировать %r: %s", text, exc)
                    return
            log.info("Фразы для голосового ответа подготовлены (%d)", len(self._cache))

        thread = threading.Thread(target=_run, name="silero-warmup", daemon=True)
        thread.start()
        return thread

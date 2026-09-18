"""Синтез речи vosk-tts (Apache 2.0) — альтернатива Piper с более чистой
дикцией.

Одна модель `vosk-model-tts-ru-0.9-multi` содержит пять русских голосов
(speaker_id 0…4): выбор голоса — параметр на каждой фразе, а не отдельный
файл, так что все пять доступны без дополнительной памяти.

Ударения. Модель ставит их сама по внутреннему словарю, но в фамилиях
ошибается («БУдько» вместо «БудькО»), а слово со словарным ударением иначе
не переучить. Разметка «+» перед ударной гласной («будьк+о») обходит
словарь — на этом построен stress_dictionary в настройках: пары «как
слышно → как произносить». Замена идёт по словам, регистр не важен.

Память: модель ~1 ГБ, живёт в том же процессе, что и распознавание,
поэтому её страницы уходят в своп на общих основаниях (см.
memory_saver.py) — отдельного управления не нужно.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from . import phrase_cache

log = logging.getLogger(__name__)

#: Сколько потоков отдать onnxruntime. Замер на рабочей станции (4 ядра,
#: загруженные другой работой): 1 поток — 1,7 с на короткую фразу, 2 — 1,0 с,
#: 4 — 2,0 с (потоки дерутся за ядра с распознаванием). 0 — как решит
#: onnxruntime сам.
DEFAULT_THREADS = 2


@contextlib.contextmanager
def _onnx_threads(threads: int) -> Iterator[None]:
    """Создать сессию onnxruntime с ограничением по потокам.

    vosk-tts не даёт задать SessionOptions, поэтому на время загрузки
    модели подменяем конструктор сессии. Подмена снимается сразу после —
    чужой код (если он в этом же процессе тоже грузит onnx) не затронут."""
    if not threads:
        yield
        return
    try:
        import onnxruntime
    except Exception:  # noqa: BLE001 — нет onnxruntime, значит и движка нет
        yield
        return
    original = onnxruntime.InferenceSession

    def limited(path, sess_options=None, providers=None, **kwargs):
        options = sess_options or onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        return original(path, sess_options=options, providers=providers, **kwargs)

    onnxruntime.InferenceSession = limited
    try:
        yield
    finally:
        onnxruntime.InferenceSession = original

DEFAULT_MODEL_LOCATIONS = [
    "/usr/share/audioreferent/vosk-tts/vosk-model-tts-ru-0.9-multi",
    str(Path.home() / ".cache" / "vosk" / "vosk-model-tts-ru-0.9-multi"),
]

#: Голоса модели …-multi: как их называть в настройках.
SPEAKERS = {0: "голос 0", 1: "голос 1", 2: "голос 2", 3: "голос 3", 4: "голос 4"}
DEFAULT_SPEAKER = 0
SAMPLE_RATE = 22050

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def resolve_model_path(configured_path: str | None) -> str | None:
    if configured_path:
        return configured_path if Path(configured_path).is_dir() else None
    for candidate in DEFAULT_MODEL_LOCATIONS:
        if Path(candidate).is_dir():
            return candidate
    return None


def available() -> bool:
    """Установлен ли пакет vosk-tts (он тянет onnxruntime и numpy)."""
    try:
        import vosk_tts  # noqa: F401
    except Exception:  # noqa: BLE001 — любая проблема импорта = движка нет
        return False
    return True


def apply_stress(text: str, stress: dict[str, str]) -> str:
    """Подставить ударения из словаря: «Участник Будько» -> «Участник
    Будьк+о». Ключи и значения — в нижнем регистре; регистр исходного слова
    восстанавливаем, чтобы текст в журнале оставался читаемым."""
    if not stress:
        return text

    def _replace(match: re.Match) -> str:
        word = match.group(0)
        marked = stress.get(word.lower())
        if marked is None:
            return word
        return marked.capitalize() if word[:1].isupper() else marked

    return _WORD_RE.sub(_replace, text)


class VoskTtsEngine:
    """PCM16 mono через vosk-tts. Кеш по тексту, как у PiperEngine, —
    фиксированные фразы синтезируются один раз (см. warm_up)."""

    def __init__(
        self,
        model_path: str,
        *,
        speaker: int = DEFAULT_SPEAKER,
        speech_rate: float = 1.0,
        stress: dict[str, str] | None = None,
        threads: int = DEFAULT_THREADS,
    ):
        self.model_path = model_path
        self.speaker = speaker
        self.speech_rate = speech_rate
        self.threads = threads
        self.stress = {k.lower(): v.lower() for k, v in (stress or {}).items()}
        self.sample_rate = SAMPLE_RATE
        self._lock = threading.Lock()
        self._cache: dict[str, bytes] = {}
        self._disk = phrase_cache.PhraseCache("vosk", str(speaker), speech_rate)
        self._synth = None

    def _ensure_synth(self):
        if self._synth is None:
            from vosk_tts import Model, Synth

            log.info("Загружаю модель синтеза речи vosk-tts: %s (голос %d)", self.model_path, self.speaker)
            with _onnx_threads(self.threads):
                self._synth = Synth(Model(model_path=self.model_path))
        return self._synth

    def synthesize(self, text: str) -> bytes:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        from_disk = self._disk.get(text)
        if from_disk:
            # Заранее собранная или уже синтезированная фраза: модель даже
            # не понадобится — на слабой машине это разница в секунды.
            self._cache[text] = from_disk
            return from_disk
        marked = apply_stress(text, self.stress)
        with self._lock:
            synth = self._ensure_synth()
            audio = synth.synth_audio(marked, speaker_id=self.speaker, speech_rate=self.speech_rate)
            pcm = audio.tobytes()
        if not pcm:
            raise RuntimeError("vosk-tts не вернул аудио")
        self._cache[text] = pcm
        self._disk.put(text, pcm)
        return pcm

    def warm_up(self, texts: Iterable[str]) -> threading.Thread:
        """Подготовить движок к работе в фоне: сначала фразы (обычно они
        уже в кэше и берутся мгновенно), затем — обязательно — загрузка
        самой модели.

        Модель грузится явно, даже когда все фразы нашлись в кэше: иначе
        она загрузится в первый раз посреди разговора, на первой же живой
        фразе с фамилией, и человек прождёт десятки секунд (замер на
        загруженной рабочей станции — 70 с). Пусть лучше это время пройдёт
        при старте сервиса, а дальше страницы уйдут в своп на общих
        основаниях (memory_saver)."""

        def _run() -> None:
            for text in texts:
                try:
                    self.synthesize(text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Не удалось заранее синтезировать %r: %s", text, exc)
                    return
            log.info("Фразы для голосового ответа подготовлены (%d)", len(self._cache))
            try:
                start = time.monotonic()
                with self._lock:
                    self._ensure_synth()
                log.info("Модель синтеза загружена за %.0f с — живые фразы не будут её ждать", time.monotonic() - start)
            except Exception as exc:  # noqa: BLE001 — не загрузилась, ответим из кэша
                log.warning("Не удалось заранее загрузить модель синтеза: %s", exc)

        thread = threading.Thread(target=_run, name="vosk-tts-warmup", daemon=True)
        thread.start()
        return thread

    def close(self) -> None:
        self._synth = None

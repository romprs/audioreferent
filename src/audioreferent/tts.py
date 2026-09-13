"""Синтез речи Piper TTS — офлайн, CPU, ~0,1 с на фразу.

Зачем: голосовые ответы помощника должны звучать одним хорошим голосом,
включая тексты, которых нельзя записать заранее (фамилия участника,
которого не нашли, тема встречи). espeak-ng для этого слишком груб, заранее
записанные фразы — только для фиксированного набора.

Почему Piper, а не Silero: движок Piper под MIT и весит ~30 МБ (ONNX
Runtime, без torch на 700 МБ), а голоса свободны: irina (женский) обучен
на данных RHVoice — лаборатория Tiflo RHVoice письмом от 12.09.2026
подтвердила, что дополнительного разрешения на него не требуется; denis и
dmitri (мужские) — CC0. Ударения Piper ставит сам (через словарь
espeak-ng), спецразметки нет.

Движок вызывается как внешняя программа (piper --output-raw): у Python-
пакета piper-tts версии новее 1.2 лицензия GPL, а бинарная сборка
rhasspy/piper 2023.11.14 — MIT и самодостаточна (onnxruntime и данные
espeak-ng внутри). Ищется по DEFAULT_BINARY_LOCATIONS (RPM кладёт в
/opt/audioreferent/piper/), голоса — по DEFAULT_VOICE_DIRS
(/usr/share/audioreferent/piper/<voice>.onnx + .onnx.json).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_BINARY_LOCATIONS = [
    "/opt/audioreferent/piper/piper",
    str(Path.home() / ".local" / "share" / "audioreferent" / "piper" / "piper"),
]
DEFAULT_VOICE_DIRS = [
    "/usr/share/audioreferent/piper",
    str(Path.home() / ".local" / "share" / "audioreferent" / "piper"),
]

#: Голос по умолчанию — женский irina (обучен на данных RHVoice; по ответу
#: руководителя лаборатории Tiflo RHVoice от 12.09.2026 дополнительного
#: разрешения на его использование в продукте не требуется). denis/dmitri —
#: мужские, CC0.
DEFAULT_VOICE = "ru_RU-irina-medium"
#: Голоса, которые кладёт пакет (ru_RU-ruslan-medium — CC BY-NC-SA, в пакет
#: не входит и здесь не перечислен).
KNOWN_VOICES = ["ru_RU-irina-medium", "ru_RU-denis-medium", "ru_RU-dmitri-medium"]


def pick_voice(requested: str | None, voices_dir: str | None) -> tuple[str | None, str | None]:
    """(имя голоса, путь к .onnx) — запрошенный, если установлен; иначе голос
    по умолчанию; иначе первый установленный. (None, None) — голосов нет.
    Отдельно от resolve_voice, чтобы вызывающий мог сообщить о подмене."""
    for candidate in (requested, DEFAULT_VOICE, *available_voices(voices_dir)):
        if not candidate:
            continue
        path = resolve_voice(candidate, voices_dir)
        if path:
            return candidate, path
    return None, None


def resolve_binary(configured_path: str | None) -> str | None:
    if configured_path:
        return configured_path if Path(configured_path).is_file() else None
    for candidate in DEFAULT_BINARY_LOCATIONS:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("piper")


def resolve_voice(voice: str, voices_dir: str | None) -> str | None:
    """Путь к <voice>.onnx (рядом должен лежать <voice>.onnx.json)."""
    dirs = [voices_dir] if voices_dir else DEFAULT_VOICE_DIRS
    for directory in dirs:
        model = Path(directory) / f"{voice}.onnx"
        if model.is_file() and model.with_suffix(".onnx.json").is_file():
            return str(model)
    return None


def available_voices(voices_dir: str | None = None) -> list[str]:
    """Голоса, реально лежащие в каталоге(ах) — для выпадающего списка GUI."""
    dirs = [voices_dir] if voices_dir else DEFAULT_VOICE_DIRS
    found: list[str] = []
    for directory in dirs:
        for model in sorted(Path(directory).glob("*.onnx")):
            if model.with_suffix(".onnx.json").is_file() and model.stem not in found:
                found.append(model.stem)
    return found


class PiperEngine:
    """Синтез PCM16 mono вызовом piper; результаты кешируются по тексту,
    фиксированные фразы помощника синтезируются один раз (см. warm_up)."""

    def __init__(self, binary: str, voice_path: str):
        self.binary = binary
        self.voice_path = voice_path
        self.sample_rate = self._read_sample_rate(voice_path)
        self._lock = threading.Lock()
        self._cache: dict[str, bytes] = {}

    @staticmethod
    def _read_sample_rate(voice_path: str) -> int:
        try:
            meta = json.loads(Path(voice_path + ".json").read_text(encoding="utf-8"))
            return int(meta["audio"]["sample_rate"])
        except (OSError, ValueError, KeyError, TypeError):
            return 22050  # частота голосов medium у Piper

    def synthesize(self, text: str) -> bytes:
        """PCM16 mono (self.sample_rate). Исключение — если piper упал."""
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        with self._lock:
            result = subprocess.run(
                [self.binary, "--model", self.voice_path, "--output-raw", "--sentence-silence", "0.15"],
                input=text.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=30,
            )
        pcm = result.stdout
        if not pcm:
            raise RuntimeError(f"piper не вернул аудио: {result.stderr.decode('utf-8', 'replace')[-200:]}")
        self._cache[text] = pcm
        return pcm

    def warm_up(self, texts: Iterable[str]) -> threading.Thread:
        """Синтезировать фразы в фоне, чтобы первый ответ не ждал."""

        def _run() -> None:
            for text in texts:
                try:
                    self.synthesize(text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Не удалось заранее синтезировать %r: %s", text, exc)
                    return
            log.info("Фразы для голосового ответа подготовлены (%d)", len(self._cache))

        thread = threading.Thread(target=_run, name="piper-warmup", daemon=True)
        thread.start()
        return thread

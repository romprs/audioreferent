"""Захват аудио с микрофона потоком чанков PCM16 для распознавателя."""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import sounddevice as sd


@contextmanager
def microphone_stream(
    sample_rate: int, device: int | str | None, blocksize: int = 8000
) -> Iterator[Iterator[bytes]]:
    """Контекстный менеджер: открывает поток с микрофона и отдаёт итератор
    сырых PCM16 mono чанков, пока поток открыт."""

    audio_queue: queue.Queue[bytes] = queue.Queue()

    def _callback(indata, frames, time_info, status):  # noqa: ARG001
        audio_queue.put(bytes(indata))

    stream = sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=blocksize,
        device=device,
        dtype="int16",
        channels=1,
        callback=_callback,
    )

    def _chunks() -> Iterator[bytes]:
        while True:
            yield audio_queue.get()

    with stream:
        yield _chunks()


def record_raw(sample_rate: int, device: int | str | None, duration_seconds: float) -> bytes:
    """Записывает моно PCM16 фиксированной длительности. Не через
    sounddevice.rec()/wait() — той удобной паре нужен NumPy, которого в
    проекте нарочно нет (см. microphone_stream выше)."""
    frames_needed = int(sample_rate * duration_seconds)
    collected = bytearray()
    done = threading.Event()

    def _callback(indata, frames, time_info, status):  # noqa: ARG001
        collected.extend(bytes(indata))
        if len(collected) >= frames_needed * 2:  # int16 = 2 байта на сэмпл
            done.set()

    with sd.RawInputStream(
        samplerate=sample_rate, blocksize=0, device=device, dtype="int16", channels=1, callback=_callback
    ):
        done.wait(timeout=duration_seconds + 5)

    return bytes(collected[: frames_needed * 2])


def list_input_devices() -> list[str]:
    lines = []
    for idx, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) > 0:
            lines.append(f"{idx}: {info['name']} (входных каналов: {info['max_input_channels']})")
    return lines

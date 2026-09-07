"""Голосовая биометрия поверх Vosk speaker-id модели (vosk-model-spk).

Не заменяет распознавание речи — отдельная лёгкая модель, дающая поверх
того же аудио x-вектор (числовой "отпечаток" голоса). Сверяем его с
заранее записанными эталонами по косинусному сходству: непохоже —
команда игнорируется, даже если активационное слово распознано верно.
Это фильтр "чей голос", а не средство от фонового шума как такового —
если эталонов нет (пользователь ничего не записал), сверка всегда
пропускает (fail-open), поведение не отличается от жизни без этой
функции."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .config import USER_CONFIG_DIR

PROFILE_PATH = USER_CONFIG_DIR / "speaker_profile.json"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SpeakerVerifier:
    def __init__(self, enrolled_vectors: list[list[float]], threshold: float):
        self.enrolled_vectors = enrolled_vectors
        self.threshold = threshold

    def matches(self, vector: list[float] | None) -> bool:
        """True, если голос похож на один из эталонов — или если сверять
        не с чем (нет вектора текущей фразы или нет эталонов вообще)."""
        if vector is None or not self.enrolled_vectors:
            return True
        return any(cosine_similarity(vector, ref) >= self.threshold for ref in self.enrolled_vectors)

    def best_similarity(self, vector: list[float]) -> float:
        if not self.enrolled_vectors:
            return 0.0
        return max(cosine_similarity(vector, ref) for ref in self.enrolled_vectors)


def load_enrolled_vectors() -> list[list[float]]:
    if not PROFILE_PATH.exists():
        return []
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return data.get("vectors", [])


def save_enrolled_vectors(vectors: list[list[float]]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps({"vectors": vectors}, ensure_ascii=False), encoding="utf-8")


def add_enrolled_vector(vector: list[float]) -> list[list[float]]:
    vectors = load_enrolled_vectors()
    vectors.append(vector)
    save_enrolled_vectors(vectors)
    return vectors


def clear_enrolled_vectors() -> None:
    if PROFILE_PATH.exists():
        PROFILE_PATH.unlink()


_BARE_NAN_INF_RE = re.compile(r'(?<![\w"])-?(?:nan|inf)(?![\w"])', re.IGNORECASE)


def load_voice_models(model_path: str, spk_model_path: str):
    """Грузит Model+SpkModel один раз. Вызывающая сторона (GUI) должна
    закэшировать результат на весь срок жизни окна и переиспользовать —
    иначе, при повторной загрузке этих тяжёлых нативных объектов на
    каждый клик "Записать образец" в одном и том же процессе, наблюдалось
    реальное повреждение кучи внутри Vosk/Kaldi ("free(): invalid next
    size", аварийный останов всего процесса) после нескольких циклов.
    KaldiRecognizer, в отличие от Model/SpkModel, дёшев и безопасен
    создавать заново на каждую запись — так и задумано в самом Vosk."""
    import vosk

    vosk.SetLogLevel(-1)
    return vosk.Model(model_path), vosk.SpkModel(spk_model_path)


def extract_voice_vector(model, spk_model, sample_rate: int, audio: bytes) -> tuple[list[float] | None, str]:
    """Прогоняет уже записанный кусок аудио (PCM16 mono) через Vosk и
    возвращает (x-вектор голоса, распознанный текст). Вектор — None, если
    в аудио не нашлось достаточно речи для него (тихая/пустая запись,
    либо вектор не посчитался численно нормально) — распознанный текст
    возвращается в любом случае, как диагностика "услышала ли Vosk хоть
    какие-то слова вообще". model/spk_model — результат load_voice_models,
    один на всю сессию (см. её docstring)."""
    import vosk

    recognizer = vosk.KaldiRecognizer(model, sample_rate)
    recognizer.SetSpkModel(spk_model)
    # Отдаём маленькими кусками, а не всей записью разом — так же, как
    # основной цикл прослушивания (см. audio.microphone_stream,
    # blocksize=8000). Скормленная целиком одним вызовом AcceptWaveform
    # 10-секундная запись на практике распознавалась ощутимо хуже, чем
    # тот же звук в потоковом режиме — по всей видимости, декодер Vosk
    # рассчитан именно на пошаговую подачу, а не на большие блоки разом.
    chunk_bytes = 8000 * 2  # int16 моно, 8000 сэмплов — как в microphone_stream
    for offset in range(0, len(audio), chunk_bytes):
        recognizer.AcceptWaveform(audio[offset : offset + chunk_bytes])
    raw = recognizer.FinalResult()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Два независимых источника невалидного JSON от Vosk (C++),
        # изредка встречающихся среди чисел в x-векторе:
        # 1) nan/inf в стиле printf вместо ожидаемых Python'ом NaN/Infinity;
        # 2) если процесс запущен под локалью с запятой как десятичным
        #    разделителем (например, PySide6/QApplication переключает
        #    C-локаль процесса под системную) — числа пишутся как "0,97"
        #    вместо "0.97". Отличаем такую запятую от настоящего
        #    JSON-разделителя элементов по отсутствию пробела после неё.
        # Чиним оба варианта и пробуем распарсить ещё раз, прежде чем
        # сдаться.
        repaired = _BARE_NAN_INF_RE.sub("null", raw)
        repaired = re.sub(r"(?<=\d),(?=\d)", ".", repaired)
        try:
            result = json.loads(repaired)
        except json.JSONDecodeError:
            return None, ""

    text = result.get("text", "")
    vector = result.get("spk")
    if vector is None or any(v is None for v in vector):
        return None, text
    return vector, text

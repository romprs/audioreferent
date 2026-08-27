"""Нечёткое сопоставление активационного слова с распознанным текстом.

Отдельная акустическая wake-word модель под каждое произвольное слово
потребовала бы переобучения при смене слова пользователем. Вместо этого
используется один и тот же (небольшой) речевой движок в режиме постоянного
распознавания, а активационная фраза ищется текстовым сравнением с допуском
на ошибки STT.
"""

from __future__ import annotations


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def contains_wake_word(text: str, wake_word: str, max_distance: int) -> bool:
    """Ищет wake_word (одно или несколько слов) среди слов text, допуская
    расстояние Левенштейна до max_distance на каждое слово окна."""
    text_words = text.lower().split()
    wake_words = wake_word.lower().split()
    window = len(wake_words)
    if window == 0 or len(text_words) < window:
        return False
    for start in range(len(text_words) - window + 1):
        candidate = text_words[start : start + window]
        total = sum(_levenshtein(c, w) for c, w in zip(candidate, wake_words))
        if total <= max_distance * window:
            return True
    return False

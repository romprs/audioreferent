"""Сопоставление распознанного текста команды с настроенными фразами."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import CommandSpec

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = _PUNCT_RE.sub("", text)
    return re.sub(r"\s+", " ", text)


@dataclass
class Match:
    spec: CommandSpec
    phrase: str
    # Остаток фразы после совпавшей команды — например, текст запроса для
    # search_web ("вика найди погоду в москве" -> "погоду в москве").
    remainder: str = ""


class CommandRegistry:
    def __init__(self, commands: list[CommandSpec]):
        self._commands = commands

    def match(self, text: str) -> Match | None:
        normalized = normalize(text)
        if not normalized:
            return None
        best: Match | None = None
        for spec in self._commands:
            for phrase in spec.phrases:
                norm_phrase = normalize(phrase)
                if not norm_phrase:
                    continue
                idx = normalized.find(norm_phrase)
                if idx >= 0 and (best is None or len(norm_phrase) > len(best.phrase)):
                    remainder = normalized[idx + len(norm_phrase):].strip()
                    best = Match(spec=spec, phrase=norm_phrase, remainder=remainder)
        return best

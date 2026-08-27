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
                if norm_phrase and norm_phrase in normalized:
                    if best is None or len(norm_phrase) > len(best.phrase):
                        best = Match(spec=spec, phrase=norm_phrase)
        return best

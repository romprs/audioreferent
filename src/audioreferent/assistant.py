"""Главный цикл: слушать активационное слово -> слушать команду -> выполнить."""

from __future__ import annotations

import logging
import time

from . import actions, feedback
from .audio import microphone_stream
from .commands import CommandRegistry
from .config import Config
from .recognizer import SpeechRecognizer, resolve_model_path
from .wakeword import contains_wake_word

log = logging.getLogger(__name__)


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.registry = CommandRegistry(config.commands)
        model_path = resolve_model_path(config.model_path)
        log.info("Загружаю модель распознавания: %s", model_path)
        self.recognizer = SpeechRecognizer(model_path, config.sample_rate)

    def _on_wake(self) -> None:
        log.info("Активационное слово услышано, жду команду")
        if self.config.feedback.sound:
            feedback.beep()
        self.recognizer.reset()

    def _on_command(self, text: str) -> None:
        log.info("Команда: %r", text)
        match = self.registry.match(text)
        if match is None:
            log.info("Команда не распознана как известная")
            if self.config.feedback.speech:
                feedback.speak("Не поняла команду")
            return
        try:
            actions.execute(match.spec.action, match.spec.args, remainder=match.remainder)
            if self.config.feedback.sound:
                feedback.beep()
        except actions.ActionError:
            log.exception("Не удалось выполнить действие %s", match.spec.action)
            if self.config.feedback.speech:
                feedback.speak("Не удалось выполнить команду")

    def run(self) -> None:
        with microphone_stream(self.config.sample_rate, self.config.input_device) as chunks:
            state = "idle"
            deadline = 0.0
            for chunk in chunks:
                if state == "idle":
                    final = self.recognizer.accept_chunk(chunk)
                    text = final if final is not None else self.recognizer.partial_text()
                    if text and contains_wake_word(
                        text, self.config.wake_word, self.config.wake_word_fuzzy_threshold
                    ):
                        self._on_wake()
                        state = "active"
                        deadline = time.monotonic() + self.config.command_timeout_seconds
                elif state == "active":
                    if time.monotonic() > deadline:
                        log.info("Время ожидания команды истекло")
                        state = "idle"
                        self.recognizer.reset()
                        continue
                    final = self.recognizer.accept_chunk(chunk)
                    if final is not None:
                        if final.strip():
                            self._on_command(final)
                            state = "idle"
                        # пустой финальный результат (тишина) — продолжаем ждать до дедлайна

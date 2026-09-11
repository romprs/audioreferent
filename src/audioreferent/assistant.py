"""Главный цикл: слушать активационное слово -> слушать команду -> выполнить."""

from __future__ import annotations

import logging
import time

from . import actions, feedback, speaker
from .audio import microphone_stream
from .commands import CommandRegistry
from .config import Config
from .recognizer import SpeechRecognizer, resolve_model_path, resolve_spk_model_path
from .wakeword import contains_wake_word, strip_wake_word

log = logging.getLogger(__name__)


class Assistant:
    def __init__(self, config: Config):
        self.config = config
        self.registry = CommandRegistry(config.commands)
        model_path = resolve_model_path(config.model_path)
        log.info("Загружаю модель распознавания: %s", model_path)

        self.speaker_verifier: speaker.SpeakerVerifier | None = None
        spk_model_path = resolve_spk_model_path(config.spk_model_path)
        if config.voice_lock_enabled:
            enrolled = speaker.load_enrolled_vectors()
            if not spk_model_path:
                log.warning("Проверка голоса включена, но spk-модель не найдена — пропускаю проверку")
            elif not enrolled:
                log.warning("Проверка голоса включена, но образцы голоса не записаны — пропускаю проверку")
            else:
                self.speaker_verifier = speaker.SpeakerVerifier(enrolled, config.voice_lock_threshold)
                log.info("Проверка голоса включена: %d образец(ов)", len(enrolled))

        self.recognizer = SpeechRecognizer(
            model_path, config.sample_rate, spk_model_path=spk_model_path if self.speaker_verifier else None
        )

    def _on_wake(self) -> None:
        log.info("Активационное слово услышано")
        if self.config.feedback.sound:
            feedback.beep()

    def _on_command(self, text: str) -> None:
        log.info("Команда: %r", text)
        match = self.registry.match(text)
        if match is None:
            log.info("Команда не распознана как известная: %r", text)
            if self.config.feedback.speech:
                feedback.speak("Команда не распознана")
            return
        try:
            actions.execute(match.spec.action, match.spec.args, remainder=match.remainder)
            log.info("Выполнено действие %s (команда: %r)", match.spec.action, text)
            if self.config.feedback.sound:
                feedback.beep()
        except actions.ActionError as exc:
            log.error("Не удалось выполнить действие %s (команда: %r): %s", match.spec.action, text, exc)
            if self.config.feedback.speech:
                # Команды redmail_* поднимают ActionError с конкретной
                # причиной из фиксированного набора фраз («Событие не
                # найдено» и т.п.) — они озвучиваются записью того же
                # голоса (feedback._PRERECORDED_PHRASES). Для текста, записи
                # которого нет, звучит общее «Не удалось выполнить команду»,
                # а сама причина остаётся в журнале выше.
                feedback.speak(str(exc) or "Не удалось выполнить команду", fallback="Не удалось выполнить команду")

    def run(self) -> None:
        with microphone_stream(self.config.sample_rate, self.config.input_device) as chunks:
            state = "idle"
            deadline = 0.0
            wake_alerted = False
            for chunk in chunks:
                if state == "idle":
                    final = self.recognizer.accept_chunk(chunk)
                    if final:
                        log.info("Распознано (в режиме ожидания активации): %r", final)
                    text = final if final is not None else self.recognizer.partial_text()
                    heard_wake = bool(text) and contains_wake_word(
                        text, self.config.wake_word, self.config.wake_word_fuzzy_threshold
                    )
                    if heard_wake and not wake_alerted:
                        # Бипаем сразу по первому попаданию в промежуточный
                        # (ещё не финальный) результат распознавания — но
                        # recognizer НЕ сбрасываем здесь: если сбросить
                        # прямо сейчас, слова команды, уже произнесённые
                        # тем же дыханием сразу после активационного слова
                        # ("вика открой браузер" без паузы), потеряются —
                        # их аудио уже отдано движку и не сматчится с
                        # текущим partial-текстом, но ещё не попало в
                        # финальный результат этой же фразы.
                        self._on_wake()
                        wake_alerted = True
                    if final is None:
                        continue
                    wake_alerted = False
                    if not heard_wake:
                        continue
                    if self.speaker_verifier is not None:
                        vector = self.recognizer.last_speaker_vector
                        if not self.speaker_verifier.matches(vector):
                            similarity = self.speaker_verifier.best_similarity(vector) if vector else 0.0
                            log.info("Голос не похож на эталон (сходство %.2f) — игнорирую", similarity)
                            if self.config.feedback.speech:
                                feedback.speak("Голос не соответствует эталону")
                            self.recognizer.reset()
                            continue

                    # Фраза целиком завершена (Vosk определил паузу после
                    # неё). Сначала пробуем найти команду прямо в этом же
                    # тексте — на случай, если она была сказана тем же
                    # потоком речи, что и активационное слово: сопоставление
                    # ищет фразу подстрокой, так что префикс "вика" не
                    # помешает. Если команды в этом тексте нет — значит
                    # активационное слово было сказано отдельно, и команду
                    # нужно ждать следующим высказыванием.
                    self.recognizer.reset()
                    if self.registry.match(final) is not None:
                        self._on_command(final)
                    elif strip_wake_word(
                        final, self.config.wake_word, self.config.wake_word_fuzzy_threshold
                    ):
                        # Кроме активационного слова в фразе были и другие
                        # слова ("вика привет"), но команды среди них нет —
                        # это была попытка команды, а не одинокое
                        # активационное слово. Молча ждать ещё одну фразу
                        # здесь неправильно: человек так и не узнает, что
                        # его не поняли. _on_command скажет
                        # «Команда не распознана».
                        self._on_command(final)
                    else:
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

"""Главный цикл: слушать активационное слово -> слушать команду -> выполнить.

Плюс режим заполнения формы встречи (state == "form"): после "вика создай
встречу" окно встречи redmail открыто, и фразы-поля ("тема планёрка",
"участники шилкин", "сохранить") принимаются без активационного слова —
см. redmail_actions.handle_form_phrase."""

from __future__ import annotations

import logging
import time

from . import actions, feedback, redmail_actions, speaker
from .audio import ChunkStream, microphone_stream
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
            model_path,
            config.sample_rate,
            spk_model_path=spk_model_path if self.speaker_verifier else None,
            endpointing=config.recognition_endpointing,
            end_silence_seconds=config.recognition_end_silence_seconds,
        )
        self._chunks: ChunkStream | None = None
        self._partial_since: tuple[str, float] | None = None
        # Движок голосового ответа (Piper) — фиксированные фразы
        # синтезируются в фоне, пока грузится всё остальное.
        if config.feedback.speech:
            feedback.configure(config)
            log.info("Голосовой ответ: %s", feedback.engine_name())

    # -- обратная связь -------------------------------------------------

    def _speak(self, text: str, fallback: str | None = "Не удалось выполнить команду") -> None:
        """Озвучить записью и выбросить эхо: пока ответ звучал в колонках,
        микрофон писал его же — без сброса помощник «слышал» бы свои фразы,
        а в режиме заполнения формы (без активационного слова) мог бы их и
        выполнить."""
        if not self.config.feedback.speech:
            return
        feedback.speak(text, fallback=fallback)
        self._drop_echo()

    def _beep(self, *, drop_echo: bool) -> None:
        """Сигнал. drop_echo=False — для сигнала на активационное слово: он
        звучит, пока человек ещё договаривает команду тем же дыханием, и
        сброс очереди выкинул бы её первые слова."""
        if not self.config.feedback.sound:
            return
        feedback.beep()
        if drop_echo:
            self._drop_echo()

    def _drop_echo(self) -> None:
        if self._chunks is not None:
            dropped = self._chunks.drain()
            if dropped:
                log.debug("Сброшено %d чанков аудио, записанных во время ответа", dropped)
        self.recognizer.reset()

    # -- распознавание -----------------------------------------------------

    def _accept(self, chunk: bytes) -> str | None:
        """Отдать чанк движку; вернуть финальный текст фразы, если она
        закончилась. Конец фразы — либо по детектору Vosk, либо по нашему
        правилу: промежуточный результат не пуст и не менялся дольше
        recognition_end_silence_seconds (vosk 0.3.45 не даёт настроить
        собственный детектор, а он ждёт ~1 с после короткой команды)."""
        final = self._accept(chunk)
        if final is not None:
            self._partial_since = None
            return final
        silence = self.config.recognition_end_silence_seconds
        if not silence:
            return None
        partial = self.recognizer.partial_text()
        now = time.monotonic()
        if not partial:
            self._partial_since = None
            return None
        if self._partial_since is None or self._partial_since[0] != partial:
            self._partial_since = (partial, now)
            return None
        # Страховка на случай, если детектор Vosk (правила из model.conf,
        # см. model_overlay) не сработал: ждём в полтора раза дольше него.
        if now - self._partial_since[1] >= silence * 1.5:
            self._partial_since = None
            return self.recognizer.finalize()
        return None

    # -- команды ---------------------------------------------------------

    def _on_wake(self) -> None:
        log.info("Активационное слово услышано")
        self._beep(drop_echo=False)

    def _on_command(self, text: str) -> bool:
        """Выполнить команду. True — действие открыло форму встречи и пора в
        режим заполнения."""
        log.info("Команда: %r", text)
        match = self.registry.match(text)
        if match is None:
            log.info("Команда не распознана как известная: %r", text)
            self._speak("Команда не распознана")
            return False
        try:
            result = actions.execute(match.spec.action, match.spec.args, remainder=match.remainder)
            log.info("Выполнено действие %s (команда: %r)", match.spec.action, text)
            if getattr(result, "enter_form_mode", False):
                log.info("Открыта форма встречи — режим заполнения (без активационного слова)")
                self._speak("Слушаю", fallback=None)
                self._beep(drop_echo=True)
                return True
            self._beep(drop_echo=True)
        except actions.ActionError as exc:
            log.error("Не удалось выполнить действие %s (команда: %r): %s", match.spec.action, text, exc)
            # Команды redmail_* поднимают ActionError с конкретной причиной
            # из фиксированного набора фраз («Событие не найдено» и т.п.) —
            # они озвучиваются записью того же голоса
            # (feedback._PRERECORDED_PHRASES). Для текста, записи которого
            # нет, звучит общее «Не удалось выполнить команду», а сама
            # причина остаётся в журнале выше.
            self._speak(str(exc) or "Не удалось выполнить команду")
        return False

    def _on_form_phrase(self, text: str) -> bool:
        """Фраза в режиме заполнения. True — режим продолжается."""
        reply = redmail_actions.handle_form_phrase(
            text,
            wake_word=self.config.wake_word,
            fuzzy_threshold=self.config.wake_word_fuzzy_threshold,
            words=self.config.event_form,
        )
        if not reply.handled:
            log.info("В режиме заполнения не поле: %r", text)
            return True
        log.info("Поле формы: %r%s", text, f" -> {reply.spoken}" if reply.spoken else "")
        if reply.spoken:
            self._speak(reply.spoken, fallback=reply.spoken_fallback or "Не удалось выполнить команду")
        else:
            self._beep(drop_echo=True)
        if reply.finished:
            log.info("Режим заполнения окончен")
            return False
        return True

    # -- главный цикл ------------------------------------------------------

    def run(self) -> None:
        with microphone_stream(
            self.config.sample_rate, self.config.input_device, blocksize=self.config.audio_block_samples
        ) as chunks:
            self._chunks = chunks
            state = "idle"
            deadline = 0.0
            wake_alerted = False
            for chunk in chunks:
                if state == "idle":
                    final = self._accept(chunk)
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
                        # Режим заполнения мог погаснуть по таймауту, пока
                        # человек переключался между окнами, а окно встречи
                        # в redmail всё ещё открыто — тогда фраза-поле
                        # («участники шапошников») возвращает режим сама,
                        # без активационного слова и без «продолжи…».
                        if final.strip() and redmail_actions.looks_like_form_phrase(
                            final,
                            wake_word=self.config.wake_word,
                            fuzzy_threshold=self.config.wake_word_fuzzy_threshold,
                            words=self.config.event_form,
                        ) and redmail_actions.form_is_open():
                            log.info("Окно встречи открыто — возвращаюсь в режим заполнения по фразе %r", final)
                            self.recognizer.reset()
                            if self._on_form_phrase(final):
                                state = "form"
                                deadline = time.monotonic() + self.config.form_timeout_seconds
                        continue
                    if self.speaker_verifier is not None:
                        vector = self.recognizer.last_speaker_vector
                        if not self.speaker_verifier.matches(vector):
                            similarity = self.speaker_verifier.best_similarity(vector) if vector else 0.0
                            log.info("Голос не похож на эталон (сходство %.2f) — игнорирую", similarity)
                            self._speak("Голос не соответствует эталону")
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
                        if self._on_command(final):
                            state = "form"
                            deadline = time.monotonic() + self.config.form_timeout_seconds
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
                    final = self._accept(chunk)
                    if final is not None:
                        if final.strip():
                            if self._on_command(final):
                                state = "form"
                                deadline = time.monotonic() + self.config.form_timeout_seconds
                            else:
                                state = "idle"
                        # пустой финальный результат (тишина) — продолжаем ждать до дедлайна
                elif state == "form":
                    if time.monotonic() > deadline:
                        log.info("Режим заполнения формы: тишина %.0f с — выхожу (окно остаётся открытым)",
                                 self.config.form_timeout_seconds)
                        state = "idle"
                        self.recognizer.reset()
                        continue
                    final = self._accept(chunk)
                    if final is None or not final.strip():
                        continue
                    log.info("Распознано (режим заполнения): %r", final)
                    if self._on_form_phrase(final):
                        deadline = time.monotonic() + self.config.form_timeout_seconds
                    else:
                        state = "idle"
                    self.recognizer.reset()

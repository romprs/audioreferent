"""Звуковая/голосовая обратная связь пользователю."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from importlib import resources

log = logging.getLogger(__name__)

_SOUND_CANDIDATES = [
    "/usr/share/sounds/freedesktop/stereo/message.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
]

# Заранее записанные фразы (один и тот же женский голос, записаны один раз
# через narakeet — синтез espeak-ng в реальном времени звучит заметно
# грубее и хуже разборчив, поэтому помощник говорит ТОЛЬКО этими
# записями). Все тексты, которые помощник произносит, обязаны быть в этом
# списке; для текста без записи speak() проигрывает fallback (обычно
# «Не удалось выполнить команду»), а сам текст остаётся в журнале. Синтез
# espeak-ng — лишь резерв на случай, когда записей нет вовсе (mpg123 не
# установлен или файлы потеряны).
_PRERECORDED_PHRASES = {
    "Команда не распознана": "voice/command_not_recognized.mp3",
    "Голос не соответствует эталону": "voice/voice_mismatch.mp3",
    "Не удалось выполнить команду": "voice/action_failed.mp3",
    # --- команды redmail (redmail_actions.py) ---
    "Запускаю почту, повторите команду": "voice/mail_starting.mp3",
    "Почта не настроена": "voice/mail_not_configured.mp3",
    "Не расслышала тему события": "voice/no_subject.mp3",
    "Не расслышала время события": "voice/no_time.mp3",
    "Не расслышала, на какое время перенести": "voice/no_new_time.mp3",
    "Событие не найдено": "voice/event_not_found.mp3",
    "Найдено несколько похожих событий, уточните тему": "voice/several_events.mp3",
    "Изменить можно только свою встречу": "voice/not_your_event.mp3",
    # --- пошаговая форма встречи (redmail_actions.py, режим заполнения) ---
    "Слушаю": "voice/listening.mp3",
    "Не поняла дату": "voice/bad_date.mp3",
    "Не поняла время": "voice/bad_time.mp3",
    "Не поняла продолжительность": "voice/bad_duration.mp3",
    "Не поняла повторение": "voice/bad_recurrence.mp3",
    "Участник не найден": "voice/participant_not_found.mp3",
    "Встреча сохранена": "voice/event_saved.mp3",
    "Отменено": "voice/cancelled.mp3",
    "Нельзя запланировать встречу на прошедшую дату": "voice/past_date.mp3",
}


# paplay — из pulseaudio-utils; на РЭД ОС 8 со штатным PipeWire его может
# не быть вовсе (стоит pipewire-pulseaudio, но не pulseaudio-utils), зато
# есть pw-play из pipewire-utils — он тоже играет .oga.
_PLAYERS = ["paplay", "pw-play"]


def beep() -> None:
    for player in _PLAYERS:
        if not shutil.which(player):
            continue
        for path in _SOUND_CANDIDATES:
            try:
                subprocess.run([player, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
    # Терминальный звонок как последний резерв. В терминале он слышен, но
    # внутри systemd-сервиса stdout уходит в журнал — звука нет, а в
    # journalctl строка с этим байтом показывается как "[N B blob data]".
    log.debug("Нет paplay/pw-play или системных звуков — звуковой сигнал недоступен")
    sys.stdout.write("\a")
    sys.stdout.flush()


def _play_recorded(text: str) -> bool:
    """Проиграть запись фразы. False — записи для этого текста нет (или
    файл отсутствует / mpg123 не установлен / не проигрался)."""
    relative_path = _PRERECORDED_PHRASES.get(text)
    if not relative_path or not shutil.which("mpg123"):
        return False
    try:
        with resources.as_file(resources.files("audioreferent").joinpath(relative_path)) as audio_path:
            if not audio_path.is_file():
                log.warning("Нет файла записи %s для фразы %r", relative_path, text)
                return False
            subprocess.run(
                ["mpg123", "-q", str(audio_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
            )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        log.debug("Не удалось проиграть запись для %r", text)
        return False


# --- движок синтеза (Silero, см. tts.py) ------------------------------
#
# Порядок озвучки в speak(): движок Silero (любой текст, один голос) ->
# заранее записанная фраза -> записанный fallback -> espeak-ng. Движок
# включается configure() из конфига (tts_engine: silero) и молча
# отключается, если нет torch или файла модели, — тогда всё работает как
# раньше, на записях.

_engine = None  # tts.SileroEngine | None

# Ударения, которые модель ставит неверно: «+» перед ударной гласной.
_STRESSED = {
    "Команда не распознана": "Команда не расп+ознана",
}


def configure(cfg, *, warm_up: bool = True) -> None:
    """Подготовить движок по конфигу; фиксированные фразы синтезируются в
    фоне заранее, чтобы первый ответ не ждал загрузки модели.

    warm_up=False — для разовых вызовов (audioreferent say, кнопка
    «Проверить голос»): фоновый поток с torch, живущий на момент выхода
    из процесса, роняет его с «terminate called without an active
    exception»."""
    global _engine
    _engine = None
    if getattr(cfg, "tts_engine", "recordings") != "silero":
        return
    from . import tts

    model_path = tts.resolve_model_path(cfg.silero_model_path)
    if not model_path:
        log.warning("Синтез Silero включён, но модель v4_ru.pt не найдена — отвечаю записями")
        return
    if not tts.torch_available():
        log.warning("Синтез Silero включён, но torch не установлен — отвечаю записями")
        return
    _engine = tts.SileroEngine(model_path, speaker=cfg.silero_speaker or tts.DEFAULT_SPEAKER)
    if warm_up:
        _engine.warm_up([_STRESSED.get(text, text) for text in _PRERECORDED_PHRASES])


def engine_name() -> str:
    return "silero" if _engine is not None else "recordings"


def _play_pcm(pcm: bytes, sample_rate: int) -> None:
    """Проиграть PCM16 mono через устройство вывода по умолчанию. Через
    sounddevice, а не внешний плеер: он уже есть в проекте, а stop() у
    PortAudio дожидается, пока буфер доиграет, — хвост фразы не режется."""
    import sounddevice as sd

    with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as out:
        out.write(pcm)


def _speak_with_engine(text: str) -> bool:
    if _engine is None:
        return False
    try:
        pcm = _engine.synthesize(_STRESSED.get(text, text))
        _play_pcm(pcm, _engine.sample_rate)
        return True
    except Exception as exc:  # noqa: BLE001 — любой сбой движка не должен ронять помощника
        log.warning("Синтез Silero не удался для %r (%s) — пробую записи", text, exc)
        return False


def speak(text: str, fallback: str | None = None) -> None:
    """Озвучить text: движком Silero, если он настроен; иначе записью, а
    если записи для него нет — записью fallback (текст при этом всё равно
    виден в журнале). espeak-ng — только когда не вышло ничего."""
    if _speak_with_engine(text):
        return
    if _play_recorded(text):
        return
    if fallback and fallback != text and _play_recorded(fallback):
        log.debug("Для фразы %r нет записи, озвучено как %r", text, fallback)
        return

    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", "ru", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", "-v", "ru", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        log.debug("Голосовой движок не найден (espeak-ng/espeak), пропускаю: %s", text)

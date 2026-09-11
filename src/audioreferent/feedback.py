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


def speak(text: str, fallback: str | None = None) -> None:
    """Озвучить text записью; если записи для него нет — записью fallback
    (текст при этом всё равно виден в журнале). Синтез — только когда не
    вышло ни то, ни другое."""
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

"""Выполнение действий по имени. Все действия реализованы через
универсальные для Linux механизмы (XDG, systemd-logind, PulseAudio/PipeWire
совместимый pactl), без привязки к конкретному окружению рабочего стола.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from typing import Any

log = logging.getLogger(__name__)


class ActionError(Exception):
    pass


def _run_background(argv: list[str]) -> None:
    subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_app(args: dict[str, Any]) -> None:
    """Запускает приложение. Поддерживает три варианта конфигурации:
    - default_browser: true — запускает браузер по умолчанию (xdg-settings + gtk-launch)
    - target — открывает путь/URL через xdg-open (файловый менеджер, ссылки)
    - candidates — пробует бинарники по очереди, запускает первый найденный
    """
    if args.get("default_browser"):
        desktop_file = None
        if shutil.which("xdg-settings"):
            try:
                out = subprocess.run(
                    ["xdg-settings", "get", "default-web-browser"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                desktop_file = out.stdout.strip()
            except subprocess.CalledProcessError:
                desktop_file = None
        if desktop_file and shutil.which("gtk-launch"):
            try:
                _run_background(["gtk-launch", desktop_file])
                return
            except FileNotFoundError:
                pass

    target = args.get("target")
    if target:
        app = args.get("app", "xdg-open")
        if not shutil.which(app):
            raise ActionError(f"Команда '{app}' не найдена")
        _run_background([app, target])
        return

    for candidate in args.get("candidates", []):
        binary = shlex.split(candidate)[0]
        if shutil.which(binary):
            _run_background(shlex.split(candidate))
            return

    app = args.get("app")
    if app and shutil.which(shlex.split(app)[0]):
        _run_background(shlex.split(app))
        return

    raise ActionError("Не найдено ни одно из указанных приложений")


def volume_change(args: dict[str, Any]) -> None:
    delta = int(args.get("delta", 0))
    sign = "+" if delta >= 0 else "-"
    percent = f"{sign}{abs(delta)}%"
    if shutil.which("pactl"):
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", percent])
        return
    if shutil.which("amixer"):
        _run(["amixer", "set", "Master", percent + ("+" if delta >= 0 else "-")])
        return
    raise ActionError("Не найден pactl/amixer для управления громкостью")


def volume_mute(args: dict[str, Any]) -> None:
    mute = "1" if args.get("mute", True) else "0"
    if shutil.which("pactl"):
        _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", mute])
        return
    if shutil.which("amixer"):
        _run(["amixer", "set", "Master", "mute" if mute == "1" else "unmute"])
        return
    raise ActionError("Не найден pactl/amixer для управления громкостью")


def lock_screen(args: dict[str, Any]) -> None:  # noqa: ARG001
    if shutil.which("loginctl"):
        try:
            _run(["loginctl", "lock-session"])
            return
        except subprocess.CalledProcessError:
            pass
    if shutil.which("xdg-screensaver"):
        _run(["xdg-screensaver", "lock"])
        return
    raise ActionError("Не удалось заблокировать экран: нет loginctl/xdg-screensaver")


ACTIONS = {
    "launch_app": launch_app,
    "volume_change": volume_change,
    "volume_mute": volume_mute,
    "lock_screen": lock_screen,
}


def execute(action: str, args: dict[str, Any]) -> None:
    handler = ACTIONS.get(action)
    if handler is None:
        raise ActionError(f"Неизвестное действие: {action}")
    handler(args)

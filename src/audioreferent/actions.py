"""Выполнение действий по имени. Все действия реализованы через
универсальные для Linux механизмы (XDG, systemd-logind, PulseAudio/PipeWire
совместимый pactl), без привязки к конкретному окружению рабочего стола.
"""

from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
from typing import Any
from urllib.parse import quote_plus

log = logging.getLogger(__name__)


class ActionError(Exception):
    pass


def _run_background(argv: list[str]) -> None:
    """Запустить приложение и не ждать его.

    Помощник работает как systemd --user сервис, и обычный Popen (даже с
    start_new_session) оставляет ребёнка в cgroup сервиса: при перезапуске
    или остановке сервиса systemd убивает всю группу — вместе с браузером,
    почтой, Р7, которые человек открыл голосом (так однажды погиб redmail,
    оставив после себя устаревший файл адреса IPC). Поэтому, где есть
    systemd-run, приложение уходит в собственный transient-юнит
    пользовательского менеджера и живёт независимо от помощника; без
    systemd-run (запуск из терминала, другая init-система) — как раньше.
    """
    if shutil.which("systemd-run"):
        try:
            subprocess.run(
                ["systemd-run", "--user", "--collect", "--quiet", "--"] + argv,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            log.debug("systemd-run недоступен, запускаю %s напрямую", argv[0])
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


def search_web(args: dict[str, Any]) -> None:
    """Открывает браузер с поиском по остатку фразы после команды —
    остаток кладёт сюда execute() под ключом 'remainder' (см. Match.remainder
    в commands.py). Значение args['engine_url'] (опционально) задаёт
    шаблон поисковика, {query} заменяется на текст запроса."""
    query = str(args.get("remainder", "")).strip()
    if not query:
        raise ActionError("Не расслышала, что искать")
    template = args.get("engine_url", "https://www.google.com/search?q={query}")
    url = template.format(query=quote_plus(query))
    if not shutil.which("xdg-open"):
        raise ActionError("Команда 'xdg-open' не найдена")
    _run_background(["xdg-open", url])


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


def _xdotool(argv: list[str]) -> str:
    if not shutil.which("xdotool"):
        raise ActionError("Команда 'xdotool' не найдена (нужна для управления окнами)")
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


def minimize_window(args: dict[str, Any]) -> None:  # noqa: ARG001
    """Сворачивает активное окно."""
    try:
        _xdotool(["xdotool", "getactivewindow", "windowminimize"])
    except subprocess.CalledProcessError as exc:
        raise ActionError("Не удалось свернуть активное окно") from exc


def close_window(args: dict[str, Any]) -> None:  # noqa: ARG001
    """Закрывает активное окно штатным запросом закрытия (как крестик в
    заголовке — приложение может показать диалог сохранения, если есть
    несохранённые изменения), а не принудительно (windowkill)."""
    try:
        _xdotool(["xdotool", "getactivewindow", "windowclose"])
    except subprocess.CalledProcessError as exc:
        raise ActionError("Не удалось закрыть активное окно") from exc


def minimize_all(args: dict[str, Any]) -> None:
    """Сворачивает все видимые окна, кроме панелей/рабочего стола
    (по умолчанию распознаются по заголовку — см. exclude_titles, при
    необходимости расширить под другое DE в конфиге)."""
    exclude = args.get("exclude_titles", ["Нижняя панель", "Рабочий стол"])
    try:
        window_ids = _xdotool(["xdotool", "search", "--onlyvisible", "."]).split()
    except subprocess.CalledProcessError as exc:
        raise ActionError("Не удалось получить список окон") from exc
    for window_id in window_ids:
        try:
            name = subprocess.run(
                ["xdotool", "getwindowname", window_id], capture_output=True, text=True
            ).stdout.strip()
        except subprocess.CalledProcessError:
            continue
        if any(skip in name for skip in exclude):
            continue
        subprocess.run(["xdotool", "windowminimize", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def send_keys(args: dict[str, Any]) -> None:  # noqa: ARG001
    """Отправляет сочетание клавиш активному окну (например, ctrl+s)."""
    keys = args.get("keys")
    if not keys:
        raise ActionError("Не указаны клавиши для отправки")
    try:
        _xdotool(["xdotool", "key", keys])
    except subprocess.CalledProcessError as exc:
        raise ActionError(f"Не удалось отправить сочетание клавиш {keys}") from exc


def open_url(args: dict[str, Any]) -> None:
    """Открывает сайт по остатку фразы после команды ("вика открой сайт
    яндекс" -> remainder "яндекс"). Сопоставление с реальным адресом
    ненадёжно на слух, поэтому: сначала ищем среди алиасов из конфига
    (args['sites'], например {"яндекс": "ya.ru"}); если алиаса нет —
    пробуем понять адрес буквально (произнесённое "точка" -> "."); если
    и это не похоже на домен — открываем как обычный поисковый запрос
    (см. search_web), чтобы не проваливать команду впустую."""
    query = str(args.get("remainder", "")).strip().lower()
    if not query:
        raise ActionError("Не расслышала, какой сайт открыть")
    if not shutil.which("xdg-open"):
        raise ActionError("Команда 'xdg-open' не найдена")

    sites = args.get("sites", {})
    target = None
    for alias, url in sites.items():
        if alias in query:
            target = url
            break

    if target is None:
        condensed = re.sub(r"\bточка\b", ".", query)
        condensed = re.sub(r"\s+", "", condensed)
        if "." in condensed:
            target = condensed

    if target is None:
        template = args.get("engine_url", "https://www.google.com/search?q={query}")
        target = template.format(query=quote_plus(query))
    elif not target.startswith(("http://", "https://")):
        target = "https://" + target

    _run_background(["xdg-open", target])


ACTIONS = {
    "launch_app": launch_app,
    "volume_change": volume_change,
    "volume_mute": volume_mute,
    "lock_screen": lock_screen,
    "search_web": search_web,
    "open_url": open_url,
    "minimize_window": minimize_window,
    "close_window": close_window,
    "minimize_all": minimize_all,
    "send_keys": send_keys,
}


def _redmail_actions() -> dict[str, Any]:
    # Отдельный модуль (redmail_actions.py) и ленивый импорт — он тянет
    # redmail_client/ru_datetime, которые этому файлу самому не нужны;
    # так action_failed вида "неизвестное действие" не зависит от того,
    # что почта вообще как-то настроена.
    from . import redmail_actions

    return redmail_actions.ACTIONS


def execute(action: str, args: dict[str, Any], remainder: str = "") -> None:
    handler = ACTIONS.get(action) or _redmail_actions().get(action)
    if handler is None:
        raise ActionError(f"Неизвестное действие: {action}")
    handler({**args, "remainder": remainder})

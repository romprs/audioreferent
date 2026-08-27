from __future__ import annotations

import argparse
import logging
import sys

from . import actions, config
from .commands import CommandRegistry


def _cmd_run(args: argparse.Namespace) -> int:  # noqa: ARG001
    from .assistant import Assistant  # отложенный импорт: тянет vosk/sounddevice

    cfg = config.load_config()
    Assistant(cfg).run()
    return 0


def _cmd_list_devices(args: argparse.Namespace) -> int:  # noqa: ARG001
    from .audio import list_input_devices

    for line in list_input_devices():
        print(line)
    return 0


def _cmd_set_wakeword(args: argparse.Namespace) -> int:
    config.set_wake_word(args.word)
    print(f"Активационное слово установлено: {args.word}")
    return 0


def _cmd_test_command(args: argparse.Namespace) -> int:
    cfg = config.load_config()
    registry = CommandRegistry(cfg.commands)
    match = registry.match(args.text)
    if match is None:
        print("Команда не распознана")
        return 1
    print(f"Найдено действие: {match.spec.action} {match.spec.args}")
    if not args.dry_run:
        try:
            actions.execute(match.spec.action, match.spec.args)
        except actions.ActionError as exc:
            print(f"Ошибка выполнения: {exc}")
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audioreferent", description="Голосовой помощник для RED OS")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser("run", help="запустить помощника (постоянное прослушивание)")
    p_run.set_defaults(func=_cmd_run)

    p_devices = subparsers.add_parser("list-devices", help="показать доступные устройства ввода")
    p_devices.set_defaults(func=_cmd_list_devices)

    p_wake = subparsers.add_parser("set-wakeword", help="задать активационное слово")
    p_wake.add_argument("word")
    p_wake.set_defaults(func=_cmd_set_wakeword)

    p_test = subparsers.add_parser("test-command", help="проверить сопоставление текста команде без аудио")
    p_test.add_argument("text")
    p_test.add_argument("--dry-run", action="store_true", help="не выполнять действие, только показать")
    p_test.set_defaults(func=_cmd_test_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

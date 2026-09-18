from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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


def _cmd_settings(args: argparse.Namespace) -> int:  # noqa: ARG001
    from .gui import main as gui_main  # отложенный импорт: тянет PySide6

    return gui_main()


def _cmd_say(args: argparse.Namespace) -> int:
    """Озвучить текст тем же путём, что и помощник (движок Piper либо
    записи) — проверка голоса и модели без микрофона."""
    from . import feedback

    cfg = config.load_config()
    if args.voice:
        cfg.piper_voice = args.voice
    feedback.configure(cfg, warm_up=False)
    print(f"Движок: {feedback.engine_name()}")
    feedback.speak(args.text, fallback=None)
    return 0


def _cmd_pregen_phrases(args: argparse.Namespace) -> int:
    """Заранее синтезировать все фиксированные фразы в кэш.

    Синтез на слабой или загруженной машине стоит секунды, поэтому фразы
    готовятся один раз: при сборке пакета (тогда каталог кладут в
    /usr/share/audioreferent/tts-cache и на рабочей машине ничего не
    считается вовсе) либо разово на самой машине."""
    from . import feedback, phrase_cache

    cfg = config.load_config()
    if args.voice:
        cfg.vosk_tts_speaker = int(args.voice)
    feedback.configure(cfg, warm_up=False)
    if feedback.engine_name() == "recordings":
        print("Синтез недоступен — нечего готовить (проверьте tts_engine и модель)")
        return 1
    target = Path(args.out) if args.out else phrase_cache.cache_root()
    done = 0
    for text in feedback.spoken_phrases():
        pcm = feedback.synthesize_to_cache(text, target)
        done += 1 if pcm else 0
        print(f"{'+' if pcm else '!'} {text}")
    print(f"Готово: {done} фраз(ы) в {target}")
    return 0 if done else 1


def _cmd_test_command(args: argparse.Namespace) -> int:
    cfg = config.load_config()
    registry = CommandRegistry(cfg.commands)
    match = registry.match(args.text)
    if match is None:
        print("Команда не распознана")
        return 1
    print(f"Найдено действие: {match.spec.action} {match.spec.args}" + (f" (остаток: {match.remainder!r})" if match.remainder else ""))
    if not args.dry_run:
        try:
            actions.execute(match.spec.action, match.spec.args, remainder=match.remainder)
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

    p_settings = subparsers.add_parser("settings", help="открыть GUI-окно настроек")
    p_settings.set_defaults(func=_cmd_settings)

    p_say = subparsers.add_parser("say", help="озвучить текст голосом помощника (проверка синтеза Piper)")
    p_say.add_argument("text")
    p_say.add_argument("--voice", default="", help="голос Piper, напр. ru_RU-denis-medium, ru_RU-irina-medium")
    p_say.set_defaults(func=_cmd_say)

    p_pregen = subparsers.add_parser(
        "pregen-phrases", help="заранее синтезировать фиксированные фразы в кэш (для сборки пакета)"
    )
    p_pregen.add_argument("--out", default="", help="каталог кэша (по умолчанию ~/.cache/audioreferent/tts)")
    p_pregen.add_argument("--voice", default="", help="голос vosk-tts (0…4)")
    p_pregen.set_defaults(func=_cmd_pregen_phrases)

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

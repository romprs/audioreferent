"""Загрузка конфигурации: значения из умолчаний, переопределённые
пользовательским файлом ~/.config/audioreferent/config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

USER_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "audioreferent"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class Feedback:
    sound: bool = True
    speech: bool = False


@dataclass
class CommandSpec:
    phrases: list[str]
    action: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    wake_word: str
    wake_word_fuzzy_threshold: int
    input_device: int | str | None
    model_path: str | None
    sample_rate: int
    command_timeout_seconds: float
    feedback: Feedback
    commands: list[CommandSpec]
    spk_model_path: str | None = None
    voice_lock_enabled: bool = False
    voice_lock_threshold: float = 0.5
    # Режим заполнения формы встречи (см. assistant.py): сколько секунд без
    # фраз-полей держать режим, прежде чем выйти из него (окно при этом
    # остаётся открытым — дозаполнить можно мышью).
    form_timeout_seconds: float = 60

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        feedback = Feedback(**data.get("feedback", {}))
        commands = [CommandSpec(**c) for c in data.get("commands", [])]
        return cls(
            wake_word=data["wake_word"],
            wake_word_fuzzy_threshold=data.get("wake_word_fuzzy_threshold", 1),
            input_device=data.get("input_device"),
            model_path=data.get("model_path"),
            sample_rate=data.get("sample_rate", 16000),
            command_timeout_seconds=data.get("command_timeout_seconds", 6),
            feedback=feedback,
            commands=commands,
            spk_model_path=data.get("spk_model_path"),
            voice_lock_enabled=data.get("voice_lock_enabled", False),
            voice_lock_threshold=data.get("voice_lock_threshold", 0.5),
            form_timeout_seconds=data.get("form_timeout_seconds", 60),
        )


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _read_default_config() -> dict:
    text = resources.files("audioreferent").joinpath("default_config.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def load_config() -> Config:
    data = _read_default_config()
    if USER_CONFIG_PATH.exists():
        data = _deep_merge(data, _read_yaml(USER_CONFIG_PATH))
    return Config.from_dict(data)


def save_config(cfg: Config) -> None:
    """Полностью перезаписывает пользовательский конфиг текущими
    настройками. В отличие от set_wake_word (который трогает только один
    ключ поверх остального), здесь сохраняются все поля явно — так делает
    GUI-окно настроек, где пользователь одновременно видит и правит их
    все, и частичный merge только запутал бы происходящее."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "wake_word": cfg.wake_word,
        "wake_word_fuzzy_threshold": cfg.wake_word_fuzzy_threshold,
        "input_device": cfg.input_device,
        "model_path": cfg.model_path,
        "sample_rate": cfg.sample_rate,
        "command_timeout_seconds": cfg.command_timeout_seconds,
        "feedback": {"sound": cfg.feedback.sound, "speech": cfg.feedback.speech},
        "spk_model_path": cfg.spk_model_path,
        "voice_lock_enabled": cfg.voice_lock_enabled,
        "voice_lock_threshold": cfg.voice_lock_threshold,
        "form_timeout_seconds": cfg.form_timeout_seconds,
    }
    # Список команд пишем ТОЛЬКО если он отличается от умолчаний пакета.
    # Иначе каждое «Сохранить» в GUI замораживало бы в пользовательском
    # файле полный снимок команд на тот момент, и ни одна новая фраза из
    # обновлённого пакета больше не подхватывалась бы (списки при загрузке
    # не сливаются — пользовательский целиком заменяет умолчания).
    commands = _commands_as_dicts(
        [{"phrases": c.phrases, "action": c.action, "args": c.args} for c in cfg.commands]
    )
    if commands != _commands_as_dicts(_read_default_config().get("commands", [])):
        data["commands"] = [
            {"phrases": c.phrases, "action": c.action, "args": c.args} for c in cfg.commands
        ]
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _commands_as_dicts(commands: list[dict]) -> list[dict]:
    """Нормализованный вид для сравнения: отсутствующий args == {}."""
    return [
        {"phrases": list(c.get("phrases", [])), "action": c.get("action"), "args": c.get("args") or {}}
        for c in commands
    ]


def set_wake_word(word: str) -> None:
    """Сохраняет активационное слово в пользовательский конфиг, не трогая
    остальные настройки (в т.ч. пользовательские команды)."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_yaml(USER_CONFIG_PATH) if USER_CONFIG_PATH.exists() else {}
    data["wake_word"] = word
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)

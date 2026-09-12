# Сторонние компоненты audioreferent и их лицензии

Перечень для пакета документов на регистрацию. Все компоненты работают
офлайн, на компьютере пользователя; сетевых сервисов продукт не использует.

| Компонент | Назначение | Версия | Лицензия | Где в пакете |
|---|---|---|---|---|
| Vosk (vosk-api, Kaldi) | распознавание речи | 0.3.45 | Apache License 2.0 | `/opt/audioreferent/venv` |
| Модель Vosk `vosk-model-ru-0.42` (без `rescore/`, `rnnlm/`) | акустическая/языковая модель русского языка | 0.42 | Apache License 2.0 | `/usr/share/audioreferent/vosk-model` |
| Модель Vosk `vosk-model-spk-0.4` | голосовая биометрия (x-vector) | 0.4 | Apache License 2.0 | `/usr/share/audioreferent/vosk-model-spk` |
| python-sounddevice (PortAudio) | захват микрофона, вывод звука | 0.4.6+ | MIT (PortAudio — MIT-подобная) | venv / системный `portaudio` |
| PyYAML | конфигурация | 6.0+ | MIT | venv |
| PySide6 (Qt 6) | окно настроек | системный пакет РЕД ОС | LGPL v3 | системный `python3-pyside6` |
| Piper TTS (rhasspy/piper, сборка 2023.11.14-2) | синтез речи; внутри onnxruntime (MIT), espeak-ng (GPL v3, используется как отдельная библиотека фонемизации в составе сборки Piper) и данные espeak-ng | 2023.11.14-2 | MIT (Piper), MIT (onnxruntime), GPL v3 (libespeak-ng) | `/opt/audioreferent/piper` |
| Голос Piper `ru_RU-irina-medium` | голос ответов по умолчанию (женский) | v1.0.0 (rhasspy/piper-voices) | Обучен на данных RHVoice (голос Irina). Голоса RHVoice — CC BY-NC-ND 4.0 с оговоркой о включении в продукт по разрешению лаборатории; **разрешение подтверждено письмом Tiflo RHVoice от 12.09.2026** (см. `RHVoice_Irina_permission.md`) | `/usr/share/audioreferent/piper` |
| Голоса Piper `ru_RU-denis-medium`, `ru_RU-dmitri-medium` | запасные голоса (мужские) | v1.0.0 | CC0 1.0 (датасет NabuCasa voice-datasets) | `/usr/share/audioreferent/piper` |
| xdotool, wmctrl, pactl/pw-play, mpg123, espeak-ng | управление окнами, громкость, проигрывание | системные пакеты РЕД ОС | GPL/LGPL (не входят в пакет, вызываются как внешние программы) | — |

Примечания:

- Записанные фразы `voice/*.mp3` (резерв на случай отсутствия Piper)
  сгенерированы сервисом narakeet.com по подписке правообладателя продукта.
- Silero TTS в продукте **не используется** (модели CC BY-NC-SA — только
  некоммерческое использование); был рассмотрен и отклонён 12.09.2026.
- Python-пакет `piper-tts` версий новее 1.2 (GPL) не используется —
  применяется бинарная сборка rhasspy/piper под MIT.

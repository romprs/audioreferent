# RPM-пакет для РЭД ОС

## Важная оговорка

Логика сборки (venv → pip install → перенос site-packages в буллрут →
упаковка) проверена — спека реально собирается `rpmbuild`-ом и даёт
рабочий `.rpm` (~10 МБ, 712 файлов). Но проверялась она не на самой
РЭД ОС, а на Debian/Ubuntu-окружении с вручную подставленными макросами
`%{python3_sitelib}` и `%{_userunitdir}` — на настоящей РЭД ОС их
подставит `python3-rpm-macros`/`systemd-rpm-macros`, но это не
проверялось. Наиболее вероятные места, которые может понадобиться
поправить на месте:
- Точные имена пакетов `portaudio`, `alsa-lib`, `espeak-ng` в репозиториях
  РЭД ОС (даны по аналогии с RHEL/Fedora).
- Наличие макроса `%{_userunitdir}` (из пакета `systemd-rpm-macros`) —
  если сборка ругнётся на неизвестный макрос, установите этот пакет или
  замените путь на `/usr/lib/systemd/user` напрямую.
- `python3_sitelib` — обычно определяется пакетом `python3-rpm-macros`,
  должен быть уже доступен там, где есть `python3-devel`.

Присылайте вывод `rpmbuild`, если что-то не соберётся — поправлю.

## Почему сборка вкладывает зависимости в приватный venv (`/opt/audioreferent/venv`)

`vosk`, `sounddevice` и `PyYAML` не входят в штатные репозитории РЭД ОС.
Первая версия спеки ставила зависимости через временный venv и копировала
его `site-packages` прямо в системный `%{python3_sitelib}` — на реальной
РЭД ОС это дало **конфликт файлов при установке**: `vosk` жёстко
импортирует `requests` в своём `__init__.py` (не только для скачивания
моделей по сети — этой функцией мы не пользуемся, но импорт всё равно
происходит при `import vosk`), а `python3-requests` (и его зависимости —
`urllib3`, `idna`, `charset-normalizer`, `cffi`, `pycparser`) уже стоят в
РЭД ОС системными RPM-пакетами. Наши копии тех же файлов по тем же путям
`rpm` ставить отказывается.

Решение — ставить всё в **приватный** venv по `/opt/audioreferent/venv`
(тот же приём, что и в проекте `redmail`): никаких пересечений с
системными путями, полностью самодостаточно и не зависит от того, что
уже стоит на целевой машине (важно для закрытого контура — сеть нужна
только на машине **сборки**, не установки). venv создаётся с
`--system-site-packages`, чтобы видеть системный `python3-pyside6` (не
вкладывать отдельной копией Qt — это лишние ~150+ МБ, и в дистрибутиве
уже есть), а сам `audioreferent` и его PyPI-зависимости ставятся в
собственный `site-packages` venv'а, не пересекаясь с системными.

Собирать именно через отдельный venv, а не системным
`pip3 install --target=...`, надёжнее и по другой причине: на некоторых
дистрибутивах системный python3 пропатчен так, что ломает сборку колеса
для части пакетов из старых sdist (столкнулись с этим при проверке на
Ubuntu — с venv проблема не воспроизводится).

**Важно**: venv создаётся сразу по конечному пути (`%{buildroot}/opt/audioreferent/venv`)
в `%install`, а не в `%build` с последующим копированием — иначе
pip-сгенерированные shebang'и в `venv/bin/*` и `pyvenv.cfg` содержат путь
сборочной директории, а не установочный, и `rpmbuild`'ов
`check-buildroot` абортит сборку. После установки в venv эти пути
подчищаются `sed`'ом от префикса `%{buildroot}`.

- `rpmbuild` нужен доступ к сети (один раз, при сборке).
- Готовый `.rpm` самодостаточен и ставится на РЭД ОС без сети.

## Сборка

Пакет вкладывает модели Vosk внутрь себя (см. "Почему сборка вкладывает
модели" ниже) — их архивы (`Source1`/`Source2` в spec) не хранятся в git
(слишком большие для репозитория) и должны лежать в `~/rpmbuild/SOURCES/`
до запуска `rpmbuild` отдельно от исходного тарбола проекта:

```bash
sudo dnf install rpm-build python3-devel python3-pip systemd-rpm-macros

mkdir -p ~/rpmbuild/{SOURCES,SPECS}

# 1. Исходный тарбол из этого репозитория
VERSION=0.1.0
git archive --prefix="audioreferent-$VERSION/" -o "audioreferent-$VERSION.tar.gz" HEAD
cp "audioreferent-$VERSION.tar.gz" ~/rpmbuild/SOURCES/

# 2. Модели — см. "Как подготовить архивы моделей" ниже, если их ещё нет
cp vosk-model-ru-0.42-noextras.tar.gz vosk-model-spk-0.4.tar.gz ~/rpmbuild/SOURCES/

cp packaging/audioreferent.spec ~/rpmbuild/SPECS/
rpmbuild -ba ~/rpmbuild/SPECS/audioreferent.spec
```

Готовый пакет появится в `~/rpmbuild/RPMS/<arch>/audioreferent-0.1.0-1*.rpm`.

## Синтез речи Piper (`Source3`–`Source7`)

Голосовые ответы синтезирует Piper TTS (`src/audioreferent/tts.py`):
внешняя программа `piper` (бинарная сборка rhasspy/piper, MIT; внутри
onnxruntime и данные espeak-ng, ~20 МБ) и файлы голосов (~63 МБ каждый).
В пакет кладутся программа в `/opt/audioreferent/piper/` и голоса в
`/usr/share/audioreferent/piper/`. Положите в `~/rpmbuild/SOURCES/`:

```bash
cd ~/rpmbuild/SOURCES
curl -LO https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
for v in irina denis dmitri; do for ext in onnx onnx.json; do
  curl -LO "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/$v/medium/ru_RU-$v-medium.$ext"
done; done
```

Лицензии: программа Piper — MIT (именно сборка 2023.11.14; Python-пакет
`piper-tts` новее 1.2 — GPL, поэтому он не используется). Голос по
умолчанию `ru_RU-irina-medium` (женский) обучен на данных RHVoice; голоса
RHVoice распространяются под CC BY-NC-ND 4.0 с оговоркой «для включения в
продукт — по разрешению лаборатории», и такое подтверждение получено:
письмо руководителя лаборатории Tiflo RHVoice А. Плаксина от 12.09.2026
(«Для Ирины не требуется дополнительное разрешение») — храните его вместе с
документами продукта. `ru_RU-denis-medium` и `ru_RU-dmitri-medium` (мужские)
— CC0.

Без программы/голоса помощник не ломается: `feedback.py` переходит на
записанные фразы `voice/*.mp3`.

## Как подготовить архивы моделей (`Source1`/`Source2`)

Нужны один раз (или заново — если меняется версия модели). `Source1` —
НЕ оригинальный `vosk-model-ru-0.42.zip` с alphacephei.com напрямую: из
него убраны каталоги `rescore/` и `rnnlm/` — с используемой версией
`vosk` они не грузятся (`rescore` — ошибка чтения, `rnnlm` — сегфолт
всего процесса, см. README проекта), базовый граф без них всё равно
заметно точнее маленькой модели:

```bash
curl -L -o model.zip https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip
unzip -q model.zip
rm -rf vosk-model-ru-0.42/rescore vosk-model-ru-0.42/rnnlm
tar czf vosk-model-ru-0.42-noextras.tar.gz vosk-model-ru-0.42

curl -L -o spk.zip https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip
unzip -q spk.zip
tar czf vosk-model-spk-0.4.tar.gz vosk-model-spk-0.4
```

Крупные файлы (~470 МБ архив с моделью) скачивать напрямую на самой РЭД
ОС может быть ненадёжно — на тестовом стенде наблюдался тихий обрыв
скачивания без ошибки (см. память проекта); надёжнее скачать на другой
машине и перенести `scp`.

## Установка

```bash
sudo dnf install ~/rpmbuild/RPMS/*/audioreferent-0.1.0-1*.rpm
```

После установки — та же настройка, что и при установке через pip (см.
корневой README.md): `audioreferent set-wakeword "..."`, установка модели
Vosk (`VOSK_MODEL_PATH`), включение systemd user-сервиса.

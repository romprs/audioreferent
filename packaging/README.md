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

```bash
sudo dnf install rpm-build python3-devel python3-pip systemd-rpm-macros

# Собрать исходный тарбол из этого репозитория
VERSION=0.1.0
git archive --prefix="audioreferent-$VERSION/" -o "audioreferent-$VERSION.tar.gz" HEAD

mkdir -p ~/rpmbuild/{SOURCES,SPECS}
cp "audioreferent-$VERSION.tar.gz" ~/rpmbuild/SOURCES/
cp packaging/audioreferent.spec ~/rpmbuild/SPECS/

rpmbuild -ba ~/rpmbuild/SPECS/audioreferent.spec
```

Готовый пакет появится в `~/rpmbuild/RPMS/<arch>/audioreferent-0.1.0-1*.rpm`.

## Установка

```bash
sudo dnf install ~/rpmbuild/RPMS/*/audioreferent-0.1.0-1*.rpm
```

После установки — та же настройка, что и при установке через pip (см.
корневой README.md): `audioreferent set-wakeword "..."`, установка модели
Vosk (`VOSK_MODEL_PATH`), включение systemd user-сервиса.

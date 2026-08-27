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

## Почему сборка вкладывает зависимости в пакет

`vosk`, `sounddevice` и `PyYAML` не входят в штатные репозитории РЭД ОС.
Вместо того чтобы требовать их как системные RPM (которых нет), спека на
этапе **сборки** пакета создаёт временный venv, ставит зависимости в него
через pip и переносит его `site-packages` в собираемый пакет. Собирать
именно через отдельный venv, а не системным `pip3 install --target=...`
надёжнее: на некоторых дистрибутивах системный python3 пропатчен так, что
ломает сборку колеса для части пакетов из старых sdist (столкнулись с
этим при проверке на Ubuntu — с venv проблема не воспроизводится). Из-за
такого подхода:
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

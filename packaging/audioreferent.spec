Name:           audioreferent
Version:        0.1.0
Release:        1%{?dist}
Summary:        Голосовой помощник с командами на русском языке для РЭД ОС

# Плейсхолдер — в репозитории пока нет файла LICENSE. Замените на
# реальную лицензию, когда она будет выбрана.
License:        Proprietary
URL:            https://github.com/romprs/audioreferent
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel
BuildRequires:  python3-pip

Requires:       python3
Requires:       portaudio
Requires:       alsa-lib
Requires:       xdotool
Requires:       python3-pyside6
Requires:       mpg123
Recommends:     espeak-ng

# vosk/sounddevice — готовые .so внутри их wheel-пакетов, у rpmbuild нет
# для них debug-символов и пытаться собрать debuginfo-пакет бессмысленно.
%global debug_package %{nil}
# Наш venv не должен участвовать в автосканировании зависимостей/provides —
# внутри него есть свои .so (vosk, cffi), но это не системные библиотеки
# для остального дистрибутива, и сканирование только зря тянет левые
# Requires/Provides.
%global __requires_exclude_from ^/opt/%{name}/venv/.*$
%global __provides_exclude_from ^/opt/%{name}/venv/.*$
%global __brp_mangle_shebangs_exclude_from ^/opt/%{name}/venv/.*$

%description
Голосовой помощник, слушающий настраиваемое активационное слово (по
умолчанию «Вика») и выполняющий команды на русском языке через
универсальные для Linux механизмы (XDG, systemd-logind, pactl), без
привязки к конкретному окружению рабочего стола. Распознавание речи —
офлайн (Vosk), после установки сеть в работе не требуется.

%prep
%autosetup -n %{name}-%{version}

%build
# Заглушка: реальная сборка/установка зависимостей происходит в секции
# %%install, venv нужно создавать сразу по конечному пути
# (/opt/%{name}/venv) — если создать его здесь и потом скопировать, у
# pip-сгенерированных shebang'ов скриптов и pyvenv.cfg останется путь
# сборочной директории, а не установочный (тот же приём, что и в пакете
# redmail).

%install
# vosk тянет requests/urllib3/idna/charset-normalizer/certifi/cffi как
# жёсткие зависимости (import verhaupt в самом __init__.py, не только
# для сетевой загрузки моделей, которой мы не пользуемся) — версии этих
# пакетов в РЭД ОС уже есть системными RPM, и класть свои копии рядом в
# %{python3_sitelib} даёт конфликт файлов при установке (обнаружено при
# первой сборке). Поэтому ставим всё через приватный venv в /opt —
# полностью самодостаточный, без пересечений с системными путями и без
# зависимости от того, что уже стоит на целевой машине (закрытый контур,
# сеть нужна только на машине СБОРКИ, не установки).
#
# --system-site-packages: чтобы venv видел системный python3-pyside6
# (тяжёлый Qt, вкладывать отдельной копией — то же самое, что уже стоит
# в дистрибутиве, лишние ~150+ МБ) — сам audioreferent и его PyPI-зависимости
# при этом ставятся в СВОИ site-packages venv'а, не пересекаясь с системными.
mkdir -p %{buildroot}/opt/%{name}
python3 -m venv --system-site-packages %{buildroot}/opt/%{name}/venv
%{buildroot}/opt/%{name}/venv/bin/pip install --no-cache-dir --upgrade pip
%{buildroot}/opt/%{name}/venv/bin/pip install --no-cache-dir %{_builddir}/%{name}-%{version}

# pip/venv записали в pyvenv.cfg и в шебанги venv/bin/* абсолютный путь
# СБОРОЧНОГО буллрута — check-buildroot иначе ругается на утечку этого
# пути в установленный пакет.
sed -i "s|%{buildroot}||g" %{buildroot}/opt/%{name}/venv/pyvenv.cfg
grep -rlZ "%{buildroot}" %{buildroot}/opt/%{name}/venv/bin/ 2>/dev/null | xargs -0 -r sed -i "s|%{buildroot}||g"

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/audioreferent <<'WRAPPER'
#!/bin/sh
exec /opt/audioreferent/venv/bin/python3 -m audioreferent.cli "$@"
WRAPPER
chmod 0755 %{buildroot}%{_bindir}/audioreferent

mkdir -p %{buildroot}%{_userunitdir}
install -m 0644 systemd/audioreferent.service %{buildroot}%{_userunitdir}/audioreferent.service

mkdir -p %{buildroot}%{_datadir}/applications
install -m 0644 packaging/audioreferent-settings.desktop %{buildroot}%{_datadir}/applications/audioreferent-settings.desktop

%files
/opt/%{name}
%{_bindir}/audioreferent
%{_userunitdir}/audioreferent.service
%{_datadir}/applications/audioreferent-settings.desktop
%doc README.md

%post
echo "Активационное слово по умолчанию — «Вика»."
echo "Изменить: audioreferent set-wakeword \"<слово>\""
echo "Включить автозапуск: systemctl --user enable --now audioreferent.service"

%changelog
* Thu Aug 27 2026 romprs <romprs@gmail.com> - 0.1.0-1
- Первая версия пакета

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
Recommends:     espeak-ng

# vosk/sounddevice — готовые .so внутри их wheel-пакетов, у rpmbuild нет
# для них debug-символов и пытаться собрать debuginfo-пакет бессмысленно.
%global debug_package %{nil}

%description
Голосовой помощник, слушающий настраиваемое активационное слово (по
умолчанию «Вика») и выполняющий команды на русском языке через
универсальные для Linux механизмы (XDG, systemd-logind, pactl), без
привязки к конкретному окружению рабочего стола. Распознавание речи —
офлайн (Vosk), после установки сеть в работе не требуется.

%prep
%autosetup -n %{name}-%{version}

%build
# vosk, sounddevice и PyYAML не входят в штатные репозитории РЭД ОС,
# поэтому вкладываем их в сам пакет на этапе сборки (rpmbuild должен
# запускаться с доступом к сети/PyPI) — итоговый .rpm самодостаточен и
# ставится без сети.
#
# Собираем во временном venv, а не через системный pip3 --target: у
# некоторых дистрибутивов system-python пропатчен так, что ломает сборку
# колёс из старых sdist-пакетов (см. packaging/README.md).
python3 -m venv venv
venv/bin/pip install --no-cache-dir --upgrade pip
venv/bin/pip install --no-cache-dir .

%install
mkdir -p %{buildroot}%{python3_sitelib}
cp -a venv/lib/python*/site-packages/. %{buildroot}%{python3_sitelib}/
# Сам venv нам не нужен — нужны только пакеты из его site-packages
rm -rf %{buildroot}%{python3_sitelib}/pip* %{buildroot}%{python3_sitelib}/setuptools* %{buildroot}%{python3_sitelib}/wheel* %{buildroot}%{python3_sitelib}/_distutils_hack* %{buildroot}%{python3_sitelib}/distutils-precedence.pth

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/audioreferent <<'WRAPPER'
#!/bin/sh
exec python3 -m audioreferent.cli "$@"
WRAPPER
chmod 0755 %{buildroot}%{_bindir}/audioreferent

mkdir -p %{buildroot}%{_userunitdir}
install -m 0644 systemd/audioreferent.service %{buildroot}%{_userunitdir}/audioreferent.service

%files
%{python3_sitelib}/*
%{_bindir}/audioreferent
%{_userunitdir}/audioreferent.service
%doc README.md

%post
echo "Активационное слово по умолчанию — «Вика»."
echo "Изменить: audioreferent set-wakeword \"<слово>\""
echo "Включить автозапуск: systemctl --user enable --now audioreferent.service"

%changelog
* Thu Aug 27 2026 romprs <romprs@gmail.com> - 0.1.0-1
- Первая версия пакета

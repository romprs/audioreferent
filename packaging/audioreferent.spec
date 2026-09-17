Name:           audioreferent
Version:        0.1.0
Release:        10%{?dist}
Summary:        Голосовой помощник с командами на русском языке для РЭД ОС

# Стандартное для РЭД ОС payload-сжатие (zstd) дало битый архив на одном
# огромном файле модели (graph/HCLG.fst, ~850 МБ) — "cpio: Digest mismatch"
# при установке, при абсолютно целом источнике (сверено md5). Переключаем
# на gzip как более простой и надёжный на таком большом одиночном файле.
%define _binary_payload w9.gzdio

# Плейсхолдер — в репозитории пока нет файла LICENSE. Замените на
# реальную лицензию, когда она будет выбрана.
License:        Proprietary
URL:            https://github.com/romprs/audioreferent
Source0:        %{name}-%{version}.tar.gz
# Заранее подготовленные модели Vosk — не собираются из чего-либо, просто
# вкладываются как есть (см. комментарий у их распаковки в %%install про
# то, почему это НЕ оригинальные zip с alphacephei.com напрямую). Кладите
# такие же файлы в rpmbuild/SOURCES/ перед сборкой — они не входят в git
# (слишком большие для репозитория), см. packaging/README.md.
Source1:        vosk-model-ru-0.42-noextras.tar.gz
Source2:        vosk-model-spk-0.4.tar.gz
# Синтез речи Piper TTS (см. src/audioreferent/tts.py): бинарная сборка
# rhasspy/piper 2023.11.14-2 (MIT; onnxruntime и данные espeak-ng внутри,
# ~20 МБ) и голоса с huggingface.co/rhasspy/piper-voices (<имя>.onnx +
# <имя>.onnx.json, ~63 МБ каждый). irina — женский голос RHVoice (лаборатория
# Tiflo RHVoice письмом от 12.09.2026 подтвердила, что дополнительного
# разрешения не требуется), denis/dmitri — мужские, CC0.
# Всё — в SOURCES/, см. packaging/README.md.
Source3:        piper_linux_x86_64.tar.gz
Source4:        ru_RU-irina-medium.onnx
Source5:        ru_RU-irina-medium.onnx.json
Source6:        ru_RU-denis-medium.onnx
Source7:        ru_RU-denis-medium.onnx.json
Source8:        ru_RU-dmitri-medium.onnx
Source9:        ru_RU-dmitri-medium.onnx.json

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
%global __requires_exclude_from ^(/opt/%{name}/(venv|piper)/|%{_datadir}/%{name}/(vosk-model|piper)).*$
%global __provides_exclude_from ^(/opt/%{name}/(venv|piper)/|%{_datadir}/%{name}/(vosk-model|piper)).*$
%global __brp_mangle_shebangs_exclude_from ^/opt/%{name}/(venv|piper)/.*$

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

# Модели Vosk — вкладываем прямо в пакет, чтобы установка на закрытом
# контуре (без интернета) сразу давала рабочего помощника, без отдельного
# ручного шага "скачайте и положите модель руками". Source1 — НЕ
# оригинальный vosk-model-ru-0.42.zip с alphacephei.com: у его каталогов
# rescore/ и rnnlm/ не грузится с используемой версией vosk (rescore —
# ошибка чтения JSON, rnnlm — сегфолт всего процесса, см. README) — Source1
# это тот же архив с уже убранными этими двумя каталогами, распознаёт
# по-прежнему заметно точнее маленькой модели, просто без этих надстроек.
mkdir -p %{buildroot}%{_datadir}/%{name}
tar xzf %{SOURCE1} -C %{buildroot}%{_datadir}/%{name}
mv %{buildroot}%{_datadir}/%{name}/vosk-model-ru-0.42 %{buildroot}%{_datadir}/%{name}/vosk-model
tar xzf %{SOURCE2} -C %{buildroot}%{_datadir}/%{name}
mv %{buildroot}%{_datadir}/%{name}/vosk-model-spk-0.4 %{buildroot}%{_datadir}/%{name}/vosk-model-spk

# Piper: программа в /opt/audioreferent/piper/ (архив содержит каталог
# piper/ с бинарником, libonnxruntime и espeak-ng-data — распаковываем как
# есть), голоса — в /usr/share/audioreferent/piper/ (пути, которые tts.py
# проверяет первыми).
tar xzf %{SOURCE3} -C %{buildroot}/opt/%{name}
chmod 0755 %{buildroot}/opt/%{name}/piper/piper
mkdir -p %{buildroot}%{_datadir}/%{name}/piper
install -m 0644 %{SOURCE4} %{SOURCE5} %{SOURCE6} %{SOURCE7} %{SOURCE8} %{SOURCE9} %{buildroot}%{_datadir}/%{name}/piper/

mkdir -p %{buildroot}%{_userunitdir}
install -m 0644 systemd/audioreferent.service %{buildroot}%{_userunitdir}/audioreferent.service

mkdir -p %{buildroot}%{_datadir}/applications
install -m 0644 packaging/audioreferent-settings.desktop %{buildroot}%{_datadir}/applications/audioreferent-settings.desktop

%files
/opt/%{name}
%{_bindir}/audioreferent
%{_userunitdir}/audioreferent.service
%{_datadir}/applications/audioreferent-settings.desktop
%{_datadir}/%{name}/vosk-model
%{_datadir}/%{name}/vosk-model-spk
%{_datadir}/%{name}/piper
%doc README.md

%post
echo "Активационное слово по умолчанию — «Вика»."
echo "Изменить: audioreferent set-wakeword \"<слово>\""
echo "Включить автозапуск: systemctl --user enable --now audioreferent.service"

%changelog
* Thu Sep 17 2026 romprs <romprs@gmail.com> - 0.1.0-10
- Разговор создания встречи: после однозначного ответа (тема, день, время, длительность, повтор, календарь, место) — пауза полсекунды и следующий вопрос; «дальше» нужно только для участников и описания
- В разговор добавлены вопросы о повторении и описании
- Участники: «Найдено 5, выберите номер» — номер сразу добавляет, «принять» не нужно; не разобрала — просит повторить
- Такой же пошаговый разговор для отмены и изменения встречи: какую встречу, номер, только этот день или вся серия, подтверждение
- Перенос и изменение встречи — один разговор: «перенеси планёрку на завтра в десять», «на 30 минут», «на час раньше» подставляет новое время и спрашивает «Сохранить изменения?»
- Короткие команды «перенеси», «измени», «отмени» без слова «встречу»; тема ищется по основам слов («планерку» — «Планёрка»)
* Wed Sep 16 2026 romprs <romprs@gmail.com> - 0.1.0-9
- Разговорный режим формы встречи: помощник сам спрашивает тему, день, время, длительность, календарь, участников и место; ответ — просто значение, «дальше» и «назад» переходят между вопросами, в конце «Сохранить встречу?»
- Выбор календаря голосом: «календарь эксчейндж», «календарь вк», «календарь два»; если не найден — перечисляет, какие есть
- Поле, о котором спрашивают, подсвечивается в окне почты (нужен redmail 0.0.1-117)

* Sun Sep 13 2026 romprs <romprs@gmail.com> - 0.1.0-8
- Конец фразы по уровню тишины микрофона и наложение на модель (короче ожидание); участники: тише, одна книга за раз, нечёткие фамилии; даты в родительном падеже; перенос только по дате

* Sun Sep 13 2026 romprs <romprs@gmail.com> - 0.1.0-7
- Адресная книга: «N принять» одной фразой, очередь неоднозначных фамилий, книга закрыта вручную — без сбоя; «добавь <фамилии>», «назови участников»

* Sun Sep 13 2026 romprs <romprs@gmail.com> - 0.1.0-6
- Участники встречи: при неоднозначной фамилии открывается адресная книга redmail, выбор по номеру или имени, «принять»; уточнение по имени/фамилии; установленный голос вместо отсутствующего, без espeak

* Sat Sep 12 2026 romprs <romprs@gmail.com> - 0.1.0-5
- Голос irina (RHVoice, с разрешения RHVoice Lab) в пакете и по умолчанию; перечень сторонних лицензий

* Sat Sep 12 2026 romprs <romprs@gmail.com> - 0.1.0-4
- Голосовой ответ синтезом Piper TTS (программа piper, голоса irina/denis/dmitri в пакете); записи — резерв
- Слова формы встречи в конфиге и GUI; пользовательские команды сливаются с умолчаниями пакета; инфинитивы фраз

* Sat Sep 12 2026 romprs <romprs@gmail.com> - 0.1.0-3
- Пошаговое голосовое заполнение открытой формы встречи redmail, поиск контактов по фамилии на слух
- Ответы записанными фразами без синтеза; запуск приложений в отдельном юните; устаревший канал redmail считается «не запущен»
* Wed Sep 09 2026 romprs <romprs@gmail.com> - 0.1.0-2
- Голосовые команды управления redmail через его локальный IPC-канал
  (открой почту / создай встречу / перенеси встречу / отмени встречу)

* Thu Aug 27 2026 romprs <romprs@gmail.com> - 0.1.0-1
- Первая версия пакета

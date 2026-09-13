"""Окно настроек audioreferent (PySide6). Показывает и позволяет
редактировать тот же config.yaml, что читает Assistant — без этого окна
доступны те же настройки через ~/.config/audioreferent/config.yaml и
`audioreferent set-wakeword`, GUI просто удобнее для регулярной подстройки
(активационное слово, порог нечёткости, микрофон, список команд)."""

from __future__ import annotations

import html
import json
import locale
import re
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

import sounddevice as sd
from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import actions, config, speaker
from .audio import record_raw
from .recognizer import resolve_model_path, resolve_spk_model_path

# Порядок важен: первый совпавший шаблон определяет цвет строки лога —
# так по цвету сразу видно, где именно застряла команда: не расслышала
# активационное слово, расслышала, но не поняла команду (или само
# действие не смогло выполниться, например xdotool не нашёл активное
# окно), или всё прошло успешно.
LOG_LINE_STYLES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Выполнено действие"), "#2e7d32"),
    (re.compile(r"Не удалось выполнить действие|Ошибка выполнения"), "#c62828"),
    (re.compile(r"Команда не распознана"), "#e65100"),
    (re.compile(r"Активационное слово услышано"), "#1565c0"),
    (re.compile(r"Распознано \(в режиме ожидания"), "#757575"),
]


class SettingsWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Настройки audioreferent")
        self.resize(820, 620)

        self.cfg = config.load_config()
        self.log_process: QProcess | None = None
        self._voice_models_cache: tuple[str, str, object, object] | None = None

        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        tabs.addTab(self._build_settings_tab(), "Настройки")
        tabs.addTab(self._build_log_tab(), "Лог")

        self._load_into_widgets()
        self._start_log_stream()

    def closeEvent(self, event) -> None:  # noqa: N802 — переопределение Qt-метода
        if self.log_process is not None:
            self.log_process.kill()
            self.log_process.waitForFinished(1000)
        super().closeEvent(event)

    # -- построение UI --------------------------------------------------

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._build_general_group())
        layout.addWidget(self._build_voice_lock_group())
        layout.addWidget(self._build_feedback_group())
        layout.addWidget(self._build_commands_group(), stretch=1)
        layout.addWidget(self._build_event_form_group())
        layout.addLayout(self._build_buttons())
        return tab

    def _build_log_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Лог сервиса audioreferent.service в реальном времени:"))
        controls.addStretch(1)
        self.log_autoscroll_check = QCheckBox("Автопрокрутка")
        self.log_autoscroll_check.setChecked(True)
        controls.addWidget(self.log_autoscroll_check)
        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(lambda: self.log_view.clear())
        controls.addWidget(clear_btn)
        layout.addLayout(controls)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("monospace"))
        layout.addWidget(self.log_view, stretch=1)

        legend = QLabel(
            '<span style="color:#1565c0">■</span>&nbsp;активация&nbsp;&nbsp;'
            '<span style="color:#757575">■</span>&nbsp;услышано без активации&nbsp;&nbsp;'
            '<span style="color:#e65100">■</span>&nbsp;команда не распознана&nbsp;&nbsp;'
            '<span style="color:#2e7d32">■</span>&nbsp;выполнено&nbsp;&nbsp;'
            '<span style="color:#c62828">■</span>&nbsp;ошибка выполнения'
        )
        layout.addWidget(legend)

        return tab

    def _build_general_group(self) -> QGroupBox:
        box = QGroupBox("Активация и распознавание")
        form = QFormLayout(box)

        self.wake_word_edit = QLineEdit()
        form.addRow("Активационное слово:", self.wake_word_edit)

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 3)
        self.threshold_spin.setToolTip(
            "Допустимое расстояние Левенштейна между произнесённым и "
            "настроенным словом. Больше — активируется охотнее, но чаще "
            "ложно; меньше — строже, но легче не расслышать в шуме."
        )
        form.addRow("Порог нечёткости слова:", self.threshold_spin)

        self.device_combo = QComboBox()
        self.device_combo.addItem("По умолчанию", None)
        try:
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) > 0:
                    self.device_combo.addItem(f"{idx}: {info['name']}", idx)
        except Exception as exc:  # noqa: BLE001 — отображаем как есть, не роняем окно
            self.device_combo.addItem(f"(не удалось получить список устройств: {exc})", None)
        form.addRow("Микрофон:", self.device_combo)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1, 30)
        self.timeout_spin.setSuffix(" сек")
        form.addRow("Время ожидания команды после активации:", self.timeout_spin)

        return box

    def _build_voice_lock_group(self) -> QGroupBox:
        box = QGroupBox("Голосовая биометрия (чей это голос)")
        layout = QVBoxLayout(box)

        top_row = QHBoxLayout()
        self.voice_lock_check = QCheckBox("Включить проверку голоса")
        self.voice_lock_check.setToolTip(
            "Пока нет ни одного записанного образца, эта настройка ничего "
            "не меняет — команды выполняются как обычно, чей бы голос ни "
            "произнёс активационное слово."
        )
        top_row.addWidget(self.voice_lock_check)
        top_row.addWidget(QLabel("Порог схожести:"))
        self.voice_threshold_spin = QDoubleSpinBox()
        self.voice_threshold_spin.setRange(0.0, 1.0)
        self.voice_threshold_spin.setSingleStep(0.05)
        self.voice_threshold_spin.setToolTip(
            "Косинусное сходство x-векторов голоса, начиная с которого "
            "голос считается «своим». Выше — строже, ниже — мягче."
        )
        top_row.addWidget(self.voice_threshold_spin)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        self.voice_samples_label = QLabel("Образцов записано: 0")
        bottom_row.addWidget(self.voice_samples_label)
        bottom_row.addStretch(1)
        record_btn = QPushButton("Записать образец голоса (10 сек)")
        record_btn.clicked.connect(self._record_voice_sample)
        bottom_row.addWidget(record_btn)
        clear_btn = QPushButton("Очистить образцы")
        clear_btn.clicked.connect(self._clear_voice_samples)
        bottom_row.addWidget(clear_btn)
        layout.addLayout(bottom_row)

        return box

    def _build_feedback_group(self) -> QGroupBox:
        box = QGroupBox("Обратная связь")
        layout = QHBoxLayout(box)
        self.sound_check = QCheckBox("Звуковой сигнал")
        self.speech_check = QCheckBox("Голосовой ответ")
        layout.addWidget(self.sound_check)
        layout.addWidget(self.speech_check)

        layout.addSpacing(16)
        layout.addWidget(QLabel("Движок:"))
        self.tts_engine_combo = QComboBox()
        self.tts_engine_combo.addItem("Piper (синтез, любой текст)", "piper")
        self.tts_engine_combo.addItem("Записанные фразы (voice/*.mp3)", "recordings")
        layout.addWidget(self.tts_engine_combo)
        layout.addWidget(QLabel("Голос:"))
        self.tts_speaker_combo = QComboBox()
        self.tts_speaker_combo.setEditable(True)
        from . import tts

        # Только установленные голоса: раньше список включал и известные
        # имена без файлов — выбор такого голоса тихо выключал синтез, и
        # человек слышал записи/espeak, думая, что это «кривой голос».
        voices = tts.available_voices(self.cfg.piper_voices_dir)
        self.tts_speaker_combo.addItems(voices)
        if not voices:
            self.tts_speaker_combo.addItem("(голоса не установлены)")
        self.tts_speaker_combo.setToolTip(
            "Установленные голоса Piper (/usr/share/audioreferent/piper). irina — женский голос RHVoice "
            "(разрешение лаборатории получено 12.09.2026); denis/dmitri — мужские, CC0"
        )
        layout.addWidget(self.tts_speaker_combo)
        test_btn = QPushButton("Проверить голос")
        test_btn.setToolTip("Озвучить пробную фразу выбранным движком и голосом (без сохранения)")
        test_btn.clicked.connect(self._on_test_voice)
        layout.addWidget(test_btn)
        layout.addStretch(1)
        return box

    def _on_test_voice(self) -> None:
        from . import feedback

        cfg = config.Config.from_dict(config._read_default_config())
        cfg.tts_engine = self.tts_engine_combo.currentData()
        cfg.piper_voice = self.tts_speaker_combo.currentText().strip()
        cfg.piper_binary_path = self.cfg.piper_binary_path
        cfg.piper_voices_dir = self.cfg.piper_voices_dir
        try:
            feedback.configure(cfg, warm_up=False)
            feedback.speak("Команда не распознана", fallback="Не удалось выполнить команду")
            if feedback.engine_name() != "piper":
                QMessageBox.warning(
                    self,
                    "Проверка голоса",
                    "Синтез Piper недоступен (нет программы piper или ни одного голоса) — "
                    "прозвучала заранее записанная фраза, а не выбранный голос.",
                )
            elif feedback.voice_name() != cfg.piper_voice:
                QMessageBox.warning(
                    self,
                    "Проверка голоса",
                    f"Голос «{cfg.piper_voice}» не установлен — прозвучал «{feedback.voice_name()}».",
                )
            else:
                QMessageBox.information(self, "Проверка голоса", f"Озвучено: Piper, голос {feedback.voice_name()}")
        except Exception as exc:  # noqa: BLE001 — показать пользователю, а не уронить окно
            QMessageBox.warning(self, "Проверка голоса", str(exc))

    def _build_commands_group(self) -> QGroupBox:
        box = QGroupBox("Команды")
        layout = QVBoxLayout(box)

        self.commands_table = QTableWidget(0, 3)
        self.commands_table.setHorizontalHeaderLabels(["Фразы (через ;)", "Действие", "Аргументы (JSON)"])
        self.commands_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.commands_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.commands_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.commands_table)

        row_buttons = QHBoxLayout()
        add_btn = QPushButton("Добавить команду")
        add_btn.clicked.connect(lambda: self._add_command_row())
        remove_btn = QPushButton("Удалить выбранную")
        remove_btn.clicked.connect(self._remove_selected_row)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(remove_btn)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        return box

    def _build_event_form_group(self) -> QGroupBox:
        """Слова режима заполнения формы встречи — после «создай встречу»
        окно redmail открыто, и фразы принимаются без активационного слова:
        первое слово выбирает поле, остальное — значение; «Сохранить»/
        «Отменить» — отдельные слова. Строки фиксированы (это поля окна),
        правятся только слова."""
        box = QGroupBox("Форма встречи (после «создай / измени встречу», без активационного слова)")
        layout = QVBoxLayout(box)
        hint = QLabel(
            "Первое слово фразы — поле, остальное — значение: «тема планёрка», «дата следующий "
            "понедельник», «время восемь тридцать», «продолжительность два часа», «повторение каждую "
            "неделю», «участники шилкин пономарёв» (по фамилии из адресной книги), «место …», «описание …». "
            "Отдельно: «сохранить» / «отменить»."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        rows = config.EVENT_FORM_FIELDS + [("save", "Сохранить (нажать кнопку)"), ("cancel", "Отменить (нажать кнопку)")]
        self.event_form_table = QTableWidget(len(rows), 2)
        self.event_form_table.setHorizontalHeaderLabels(["Поле", "Слова (через ;)"])
        self.event_form_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.event_form_table.verticalHeader().setVisible(False)
        self.event_form_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._event_form_keys = [key for key, _label in rows]
        for row, (key, label) in enumerate(rows):
            label_item = QTableWidgetItem(label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            label_item.setData(Qt.UserRole, key)
            self.event_form_table.setItem(row, 0, label_item)
            self.event_form_table.setItem(row, 1, QTableWidgetItem(""))
        self.event_form_table.setMaximumHeight(self.event_form_table.verticalHeader().defaultSectionSize() * (len(rows) + 1) + 8)
        layout.addWidget(self.event_form_table)
        return box

    def _load_event_form_words(self, words: config.EventFormWords) -> None:
        for row, key in enumerate(self._event_form_keys):
            if key == "save":
                values = words.save
            elif key == "cancel":
                values = words.cancel
            else:
                values = words.fields.get(key, [])
            self.event_form_table.item(row, 1).setText("; ".join(values))

    def _collect_event_form_words(self) -> config.EventFormWords:
        result = config.EventFormWords()
        for row, key in enumerate(self._event_form_keys):
            item = self.event_form_table.item(row, 1)
            values = [w.strip().lower() for w in (item.text() if item else "").split(";") if w.strip()]
            if key == "save":
                result.save = values
            elif key == "cancel":
                result.cancel = values
            else:
                result.fields[key] = values
        return result

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.status_label = QLabel("")
        row.addWidget(self.status_label, stretch=1)

        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(lambda: self._save(restart=False))
        row.addWidget(save_btn)

        save_restart_btn = QPushButton("Сохранить и перезапустить сервис")
        save_restart_btn.clicked.connect(lambda: self._save(restart=True))
        row.addWidget(save_restart_btn)

        return row

    # -- загрузка/сохранение --------------------------------------------

    def _load_into_widgets(self) -> None:
        cfg = self.cfg
        self.wake_word_edit.setText(cfg.wake_word)
        self.threshold_spin.setValue(cfg.wake_word_fuzzy_threshold)
        self.timeout_spin.setValue(cfg.command_timeout_seconds)
        self.sound_check.setChecked(cfg.feedback.sound)
        self.speech_check.setChecked(cfg.feedback.speech)
        engine_idx = self.tts_engine_combo.findData(cfg.tts_engine)
        self.tts_engine_combo.setCurrentIndex(engine_idx if engine_idx >= 0 else 0)
        speaker_idx = self.tts_speaker_combo.findText(cfg.piper_voice)
        if speaker_idx >= 0:
            self.tts_speaker_combo.setCurrentIndex(speaker_idx)
        else:
            self.tts_speaker_combo.setCurrentText(cfg.piper_voice)

        device_idx = self.device_combo.findData(cfg.input_device)
        self.device_combo.setCurrentIndex(device_idx if device_idx >= 0 else 0)

        self.voice_lock_check.setChecked(cfg.voice_lock_enabled)
        self.voice_threshold_spin.setValue(cfg.voice_lock_threshold)
        self._refresh_voice_samples_label()

        self.commands_table.setRowCount(0)
        for spec in cfg.commands:
            self._add_command_row(spec.phrases, spec.action, spec.args)
        self._load_event_form_words(cfg.event_form)

    def _add_command_row(
        self, phrases: list[str] | None = None, action: str | None = None, args: dict[str, Any] | None = None
    ) -> None:
        row = self.commands_table.rowCount()
        self.commands_table.insertRow(row)

        self.commands_table.setItem(row, 0, QTableWidgetItem("; ".join(phrases or [])))

        action_combo = QComboBox()
        action_combo.setEditable(True)
        # Локальные действия плюс действия redmail (они подключаются в
        # actions.execute лениво и в actions.ACTIONS не входят).
        action_combo.addItems(sorted(set(actions.ACTIONS) | set(actions._redmail_actions())))
        if action:
            idx = action_combo.findText(action)
            if idx >= 0:
                action_combo.setCurrentIndex(idx)
            else:
                action_combo.setCurrentText(action)
        self.commands_table.setCellWidget(row, 1, action_combo)

        self.commands_table.setItem(row, 2, QTableWidgetItem(json.dumps(args or {}, ensure_ascii=False)))

    def _remove_selected_row(self) -> None:
        rows = {idx.row() for idx in self.commands_table.selectedIndexes()}
        for row in sorted(rows, reverse=True):
            self.commands_table.removeRow(row)

    def _collect_commands(self) -> list[config.CommandSpec]:
        commands: list[config.CommandSpec] = []
        for row in range(self.commands_table.rowCount()):
            phrases_item = self.commands_table.item(row, 0)
            phrases = [p.strip() for p in (phrases_item.text() if phrases_item else "").split(";") if p.strip()]
            if not phrases:
                continue

            action_widget = self.commands_table.cellWidget(row, 1)
            action_name = action_widget.currentText().strip() if action_widget else ""
            if not action_name:
                continue

            args_item = self.commands_table.item(row, 2)
            args_text = (args_item.text() if args_item else "").strip() or "{}"
            try:
                args = json.loads(args_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Строка {row + 1}: аргументы не похожи на JSON ({exc})") from exc
            if not isinstance(args, dict):
                raise ValueError(f"Строка {row + 1}: аргументы должны быть JSON-объектом ({{...}})")

            commands.append(config.CommandSpec(phrases=phrases, action=action_name, args=args))
        return commands

    # -- голосовая биометрия ----------------------------------------------

    @staticmethod
    def _pcm16_peak_rms(data: bytes) -> tuple[int, float]:
        if not data:
            return 0, 0.0
        samples = struct.unpack(f"<{len(data) // 2}h", data)
        peak = max(abs(s) for s in samples)
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
        return peak, rms

    def _get_cached_voice_models(self, model_path: str, spk_model_path: str):
        """Грузит Model+SpkModel один раз на всю жизнь окна и переиспользует
        при повторных записях — см. docstring speaker.load_voice_models
        насчёт того, почему грузить их заново на каждый клик небезопасно."""
        cached = self._voice_models_cache
        if cached is not None and cached[0] == model_path and cached[1] == spk_model_path:
            return cached[2], cached[3]
        model, spk_model = speaker.load_voice_models(model_path, spk_model_path)
        self._voice_models_cache = (model_path, spk_model_path, model, spk_model)
        return model, spk_model

    def _refresh_voice_samples_label(self) -> None:
        count = len(speaker.load_enrolled_vectors())
        self.voice_samples_label.setText(f"Образцов записано: {count}")

    def _record_voice_sample(self) -> None:
        QMessageBox.information(
            self,
            "Запись образца голоса",
            "Сейчас начнётся запись на 10 секунд. Нажмите OK и сразу "
            "начните говорить — например, несколько раз активационное "
            "слово и обычные фразы, без долгих пауз.",
        )
        self.status_label.setText("Идёт запись... говорите")
        QApplication.processEvents()

        sample_rate = self.cfg.sample_rate
        device = self.device_combo.currentData()
        try:
            recording = record_raw(sample_rate, device, duration_seconds=10.0)
        except Exception as exc:  # noqa: BLE001 — показываем пользователю как есть
            self.status_label.setText("")
            QMessageBox.warning(self, "Ошибка записи", f"Не удалось записать с микрофона:\n{exc}")
            return

        self.status_label.setText("Обрабатываю запись...")
        QApplication.processEvents()

        spk_model_path = resolve_spk_model_path(self.cfg.spk_model_path)
        if not spk_model_path:
            self.status_label.setText("")
            QMessageBox.warning(
                self,
                "Модель не найдена",
                "Не найдена spk-модель для проверки голоса (vosk-model-spk-0.4). "
                "Установите её в ~/.local/share/vosk/vosk-model-spk-0.4 или "
                "укажите путь в spk_model_path конфига.",
            )
            return

        try:
            model_path = resolve_model_path(self.cfg.model_path)
            model, spk_model = self._get_cached_voice_models(model_path, spk_model_path)
            vector, recognized_text = speaker.extract_voice_vector(model, spk_model, sample_rate, recording)
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText("")
            QMessageBox.warning(self, "Ошибка обработки записи", str(exc))
            return

        if vector is None:
            self.status_label.setText("")
            debug_path = Path.home() / "audioreferent_debug_sample.wav"
            try:
                with wave.open(str(debug_path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(recording)
            except OSError:
                debug_path = None
            peak, rms = self._pcm16_peak_rms(recording)
            if peak < 200:
                diagnosis = "Похоже, микрофон вообще не пишет звук — проверьте выбор устройства и уровень записи в настройках звука системы."
            elif not recognized_text:
                diagnosis = (
                    "Vosk вообще не распознала ни одного слова в записи (текст пуст), хотя сигнал есть — "
                    "возможно, дело не в громкости, а в качестве/чёткости звука (эхо, расстояние до микрофона, "
                    "шум) либо всё ещё в паузе перед началом речи."
                )
            else:
                diagnosis = "Речь распозналась как текст, но x-вектор голоса не посчитался — попробуйте ещё раз, подольше и без пауз."
            debug_note = f"\n\nЗапись сохранена для диагностики: {debug_path}" if debug_path else ""
            QMessageBox.warning(
                self,
                "Не удалось выделить голос",
                f"В записи не нашлось достаточно речи для анализа.\n"
                f"Уровень записи: пик {peak}/32768, RMS {rms:.0f}.\n"
                f"Распознанный текст: {recognized_text or '(пусто)'}\n\n{diagnosis}{debug_note}\n\n"
                f"[диагностика] model_path={model_path}\nspk_model_path={spk_model_path}\n"
                f"sample_rate={sample_rate}, bytes={len(recording)}",
            )
            return

        speaker.add_enrolled_vector(vector)
        self._refresh_voice_samples_label()
        self.status_label.setText(f"Образец голоса записан (услышано: {recognized_text!r}).")

    def _clear_voice_samples(self) -> None:
        answer = QMessageBox.question(
            self, "Очистить образцы", "Удалить все записанные образцы голоса?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        speaker.clear_enrolled_vectors()
        self._refresh_voice_samples_label()

    # -- лог сервиса ------------------------------------------------------

    def _start_log_stream(self) -> None:
        self.log_process = QProcess(self)
        self.log_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.log_process.readyReadStandardOutput.connect(self._on_log_output)
        self.log_process.errorOccurred.connect(self._on_log_process_error)
        # -o cat: без штампа самого journald — наши строки уже содержат
        # собственную метку времени/уровня из logging.basicConfig.
        self.log_process.start(
            "journalctl", ["--user", "-u", "audioreferent.service", "-n", "200", "-f", "-o", "cat"]
        )

    def _on_log_process_error(self, error) -> None:  # noqa: ARG002
        self._append_log_line(f"[не удалось запустить journalctl: {self.log_process.errorString()}]")

    def _on_log_output(self) -> None:
        if self.log_process is None:
            return
        data = bytes(self.log_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            if line:
                self._append_log_line(line)

    def _append_log_line(self, line: str) -> None:
        color = None
        for pattern, candidate in LOG_LINE_STYLES:
            if pattern.search(line):
                color = candidate
                break
        escaped = html.escape(line)
        html_line = f'<span style="color:{color}">{escaped}</span>' if color else escaped
        self.log_view.append(html_line)
        if self.log_autoscroll_check.isChecked():
            self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _save(self, restart: bool) -> None:
        try:
            commands = self._collect_commands()
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка в командах", str(exc))
            return

        cfg = config.Config(
            wake_word=self.wake_word_edit.text().strip() or "вика",
            wake_word_fuzzy_threshold=self.threshold_spin.value(),
            input_device=self.device_combo.currentData(),
            model_path=self.cfg.model_path,
            sample_rate=self.cfg.sample_rate,
            command_timeout_seconds=self.timeout_spin.value(),
            feedback=config.Feedback(sound=self.sound_check.isChecked(), speech=self.speech_check.isChecked()),
            commands=commands,
            spk_model_path=self.cfg.spk_model_path,
            voice_lock_enabled=self.voice_lock_check.isChecked(),
            voice_lock_threshold=self.voice_threshold_spin.value(),
            form_timeout_seconds=self.cfg.form_timeout_seconds,
            event_form=self._collect_event_form_words(),
            tts_engine=self.tts_engine_combo.currentData(),
            piper_binary_path=self.cfg.piper_binary_path,
            piper_voices_dir=self.cfg.piper_voices_dir,
            piper_voice=self.tts_speaker_combo.currentText().strip() or "ru_RU-denis-medium",
        )
        config.save_config(cfg)
        self.cfg = cfg

        if restart:
            result = subprocess.run(
                ["systemctl", "--user", "restart", "audioreferent.service"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                QMessageBox.warning(
                    self,
                    "Сохранено, но сервис не перезапущен",
                    f"Настройки сохранены в config.yaml, но перезапуск сервиса не удался:\n{result.stderr}",
                )
                return
            self.status_label.setText("Сохранено, сервис перезапущен.")
        else:
            self.status_label.setText("Сохранено. Изменения применятся при следующем запуске сервиса.")


def main() -> int:
    app = QApplication([])
    # QApplication на старте переключает C-локаль всего процесса под
    # системную (у нас — ru_RU.UTF-8, отсюда "6,00 сек" в полях выше). Но
    # эта же locale-зависимость ломает Vosk/Kaldi: их JSON с x-вектором
    # голоса пишется через locale-зависимый printf, и под ru_RU числа
    # получаются с запятой ("0,97"), а не точкой — невалидный JSON, из-за
    # чего распознанный текст/вектор голоса не читались вообще. LC_NUMERIC
    # возвращаем на "C" сразу после QApplication — сама Qt-локаль (даты,
    # интерфейс) не трогаем, только числовой разбор для C-библиотек.
    locale.setlocale(locale.LC_NUMERIC, "C")
    window = SettingsWindow()
    window.show()
    return app.exec()

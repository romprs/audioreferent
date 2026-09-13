import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import redmail_actions
from audioreferent.actions import ActionError
from audioreferent.redmail_client import RedmailError, RedmailNotRunning

TODAY = date(2026, 9, 8)


def _event(uid="uid-1", summary="Совещание", start="2026-09-08T10:00:00+00:00"):
    return {"uid": uid, "summary": summary, "start": start, "end": start, "calendar_id": "default"}


# ---------------------------------------------------------------------------
# redmail_focus
# ---------------------------------------------------------------------------


def test_focus_calls_client():
    with patch("audioreferent.redmail_actions._redmail_focus") as mock_focus:
        redmail_actions.redmail_focus({})
    mock_focus.assert_called_once()


def test_focus_wraps_redmail_error():
    with patch("audioreferent.redmail_actions._redmail_focus", side_effect=RedmailError("Канал занят")):
        with pytest.raises(ActionError, match="Канал занят"):
            redmail_actions.redmail_focus({})


def test_focus_launches_redmail_when_not_running():
    with patch(
        "audioreferent.redmail_actions._redmail_focus", side_effect=RedmailNotRunning("Почта не запущена")
    ), patch("audioreferent.redmail_actions.launch_app") as mock_launch:
        redmail_actions.redmail_focus({"candidates": ["redmail"]})  # не должно поднимать ActionError
    mock_launch.assert_called_once_with({"candidates": ["redmail"]})


def test_other_commands_launch_redmail_and_ask_to_repeat():
    with patch(
        "audioreferent.redmail_actions._redmail_create_event",
        side_effect=RedmailNotRunning("Почта не запущена"),
    ), patch("audioreferent.redmail_actions.launch_app") as mock_launch:
        with pytest.raises(ActionError, match="повторите"):
            redmail_actions.redmail_create_event({"remainder": "совещание завтра в десять"})
    mock_launch.assert_called_once_with({"candidates": ["redmail"]})


# ---------------------------------------------------------------------------
# redmail_create_event
# ---------------------------------------------------------------------------


def test_create_event_parses_subject_date_time():
    with patch("audioreferent.redmail_actions._redmail_create_event") as mock_create, patch(
        "audioreferent.redmail_actions.date_cls"
    ) as mock_date:
        mock_date.today.return_value = TODAY
        redmail_actions.redmail_create_event({"remainder": "совещание завтра в десять"})
    mock_create.assert_called_once_with(
        subject="совещание", start="2026-09-09T10:00:00", duration_minutes=60
    )


def test_create_event_requires_subject():
    with pytest.raises(ActionError, match="тему"):
        redmail_actions.redmail_create_event({"remainder": "завтра в десять"})


def test_create_event_requires_time():
    with pytest.raises(ActionError, match="время"):
        redmail_actions.redmail_create_event({"remainder": "совещание завтра"})


# ---------------------------------------------------------------------------
# redmail_reschedule_event
# ---------------------------------------------------------------------------


def test_reschedule_finds_event_and_updates_start():
    with patch(
        "audioreferent.redmail_actions._redmail_find_events", return_value=[_event()]
    ) as mock_find, patch("audioreferent.redmail_actions._redmail_update_event") as mock_update, patch(
        "audioreferent.redmail_actions.date_cls"
    ) as mock_date:
        mock_date.today.return_value = TODAY
        redmail_actions.redmail_reschedule_event(
            {"remainder": "совещание на десятое сентября в пятнадцать тридцать"}
        )
    mock_find.assert_called_once_with(subject="совещание", date="2026-09-08")
    mock_update.assert_called_once_with("uid-1", start="2026-09-10T15:30:00")


def test_reschedule_requires_na_separator():
    with pytest.raises(ActionError, match="перенести"):
        redmail_actions.redmail_reschedule_event({"remainder": "совещание в десять"})


def test_reschedule_requires_new_time():
    with pytest.raises(ActionError, match="время"):
        redmail_actions.redmail_reschedule_event({"remainder": "совещание на завтра"})


def test_reschedule_no_matching_event():
    with patch("audioreferent.redmail_actions._redmail_find_events", return_value=[]):
        with pytest.raises(ActionError, match="не найдено"):
            redmail_actions.redmail_reschedule_event({"remainder": "совещание на завтра в десять"})


def test_reschedule_ambiguous_events_narrowed_by_old_time():
    other = _event(uid="uid-other", start="2026-09-08T09:00:00+00:00")
    matching = _event(uid="uid-match", start="2026-09-08T12:00:00+00:00")
    hour_minutes = {other["start"]: (9, 0), matching["start"]: (12, 0)}
    with patch(
        "audioreferent.redmail_actions._redmail_find_events", return_value=[other, matching]
    ), patch("audioreferent.redmail_actions._redmail_update_event") as mock_update, patch(
        "audioreferent.redmail_actions._local_hour_minute", side_effect=lambda iso: hour_minutes[iso]
    ), patch("audioreferent.redmail_actions.date_cls") as mock_date:
        mock_date.today.return_value = TODAY
        # старое время "в двенадцать" должно выбрать событие uid-match среди двух
        redmail_actions.redmail_reschedule_event(
            {"remainder": "совещание в двенадцать на завтра в десять"}
        )
    mock_update.assert_called_once_with("uid-match", start="2026-09-09T10:00:00")


def test_reschedule_ambiguous_without_hint_raises():
    with patch(
        "audioreferent.redmail_actions._redmail_find_events",
        return_value=[_event(uid="a"), _event(uid="b")],
    ):
        with pytest.raises(ActionError, match="несколько"):
            redmail_actions.redmail_reschedule_event({"remainder": "совещание на завтра в десять"})


# ---------------------------------------------------------------------------
# redmail_cancel_event
# ---------------------------------------------------------------------------


def test_cancel_event_finds_and_cancels():
    with patch(
        "audioreferent.redmail_actions._redmail_find_events", return_value=[_event(uid="uid-9")]
    ), patch("audioreferent.redmail_actions._redmail_cancel_event") as mock_cancel:
        redmail_actions.redmail_cancel_event({"remainder": "совещание"})
    mock_cancel.assert_called_once_with("uid-9")


def test_cancel_event_wraps_redmail_error_on_cancel():
    with patch(
        "audioreferent.redmail_actions._redmail_find_events", return_value=[_event(uid="uid-9")]
    ), patch(
        "audioreferent.redmail_actions._redmail_cancel_event",
        side_effect=RedmailError("Отменить можно только встречу, которую организовали вы сами."),
    ):
        # свободный текст redmail сводится к фиксированной фразе, для которой есть запись
        with pytest.raises(ActionError, match="^Изменить можно только свою встречу$"):
            redmail_actions.redmail_cancel_event({"remainder": "совещание"})


# ---------------------------------------------------------------------------
# Пошаговая форма встречи
# ---------------------------------------------------------------------------

FORM = "audioreferent.redmail_actions."


def test_event_form_opens_with_fields_from_first_phrase():
    with patch(FORM + "_redmail_event_form_open") as mock_open, patch(FORM + "date_cls") as mock_date:
        mock_date.today.return_value = TODAY
        result = redmail_actions.redmail_event_form({"remainder": "планёрка на 15 сентября в восемь тридцать"})
    assert result.enter_form_mode is True
    mock_open.assert_called_once_with(subject="планёрка", date="2026-09-15", time="08:30")


def test_event_form_opens_empty_when_nothing_said():
    with patch(FORM + "_redmail_event_form_open") as mock_open:
        redmail_actions.redmail_event_form({"remainder": ""})
    mock_open.assert_called_once_with()


def test_event_form_edit_finds_own_event_by_subject():
    with patch(FORM + "_redmail_find_events", return_value=[_event(uid="uid-7")]) as mock_find, patch(
        FORM + "_redmail_event_form_open"
    ) as mock_open, patch(FORM + "date_cls") as mock_date:
        mock_date.today.return_value = TODAY
        redmail_actions.redmail_event_form({"remainder": "планёрка", "edit": True})
    mock_find.assert_called_once_with(subject="планёрка", date="2026-09-08")
    mock_open.assert_called_once_with(uid="uid-7")


def _form_phrase(text):
    return redmail_actions.handle_form_phrase(text, wake_word="вика", fuzzy_threshold=1)


@pytest.mark.parametrize(
    "phrase, expected_kwargs",
    [
        ("тема планёрка", {"subject": "планёрка"}),
        ("вика тема планёрка", {"subject": "планёрка"}),  # активационное слово допускается
        ("время восемь тридцать", {"time": "08:30"}),
        ("время в девять", {"time": "09:00"}),
        ("продолжительность два часа", {"duration_minutes": 120}),
        ("повторение каждую неделю", {"recurrence": "weekly"}),
        ("повторять нет", {"recurrence": "none"}),
        ("место кабинет сто двадцать один", {"location": "кабинет сто двадцать один"}),
        ("описание утренняя планёрка", {"description": "утренняя планёрка"}),
    ],
)
def test_form_phrase_sets_field(phrase, expected_kwargs):
    with patch(FORM + "_redmail_event_form_set") as mock_set:
        reply = _form_phrase(phrase)
    assert reply.handled and reply.spoken is None and not reply.finished
    mock_set.assert_called_once_with(**expected_kwargs)


def test_form_phrase_date_uses_current_year():
    with patch(FORM + "_redmail_event_form_set") as mock_set:
        reply = _form_phrase("дата 15 сентября")
    assert reply.handled and reply.spoken is None
    assert mock_set.call_args[1]["date"].endswith("-09-15")


@pytest.mark.parametrize(
    "phrase, spoken",
    [
        ("дата когда нибудь", "Не поняла дату"),
        ("время попозже", "Не поняла время"),
        ("продолжительность долго", "Не поняла продолжительность"),
        ("повторение по пятницам", "Не поняла повторение"),
    ],
)
def test_form_phrase_unparsed_value_is_spoken(phrase, spoken):
    with patch(FORM + "_redmail_event_form_set") as mock_set:
        reply = _form_phrase(phrase)
    assert reply.handled and reply.spoken == spoken
    mock_set.assert_not_called()


BOOK = [
    {"name": "Шилкин Александр", "email": "shilkin.a@example.com"},
    {"name": "Шилкин Евгений Александрович", "email": "shilkin.e@example.com"},
    {"name": "Будько Евгений", "email": "budko@example.com"},
    {"name": "Пономарев Роман", "email": "ponomarev@example.com"},
    {"name": "Андронов Евгений", "email": "andronov@example.com"},
]


def _fake_find_contacts(query: str) -> list[dict]:
    """Та же логика, что у redmail.ipc_server.match_contacts: все слова
    запроса должны совпасть с каким-то словом контакта."""
    return redmail_actions._local_matches(query.split(), BOOK)


def _participants(phrase: str):
    redmail_actions._pending_candidates.clear()
    with patch(FORM + "_redmail_find_contacts", side_effect=_fake_find_contacts), patch(
        FORM + "_redmail_event_form_set"
    ) as mock_set:
        reply = _form_phrase(phrase)
    return reply, mock_set


def test_participants_single_match_is_added_and_named():
    reply, mock_set = _participants("участники будько и пономарева")
    mock_set.assert_called_once_with(add_participants=["budko@example.com", "ponomarev@example.com"])
    assert reply.spoken == "Добавлены: Будько Евгений, Пономарев Роман"
    assert reply.spoken_fallback is None


def test_participants_words_are_grouped_into_one_person():
    # «шилкин евгений александрович» — один запрос, а не три слова порознь
    reply, mock_set = _participants("участники шилкин евгений александрович")
    mock_set.assert_called_once_with(add_participants=["shilkin.e@example.com"])
    assert reply.spoken == "Добавлен Шилкин Евгений Александрович"


def test_participants_ambiguous_surname_lists_candidates_and_asks():
    reply, mock_set = _participants("участник шилкин")
    mock_set.assert_not_called()
    assert reply.spoken == "Шилкин: найдено двое — Александр, Евгений Александрович. Уточните имя"
    assert reply.spoken_fallback == "Участник не найден"
    # уточнение одним именем выбирает среди запомненных кандидатов
    with patch(FORM + "_redmail_find_contacts", side_effect=_fake_find_contacts), patch(
        FORM + "_redmail_event_form_set"
    ) as mock_set2:
        follow_up = _form_phrase("участники евгений")
    mock_set2.assert_called_once_with(add_participants=["shilkin.e@example.com"])
    assert follow_up.spoken == "Добавлен Шилкин Евгений Александрович"


def test_bare_name_answers_the_clarification_question():
    _participants("участник шилкин")  # -> «уточните имя», кандидаты запомнены
    with patch(FORM + "_redmail_find_contacts", side_effect=_fake_find_contacts), patch(
        FORM + "_redmail_event_form_set"
    ) as mock_set:
        reply = _form_phrase("евгений")  # без слова «участники»
    assert reply.handled and reply.spoken == "Добавлен Шилкин Евгений Александрович"
    mock_set.assert_called_once_with(add_participants=["shilkin.e@example.com"])
    # в режиме ожидания такое имя тоже считается фразой формы
    _participants("участник шилкин")
    assert redmail_actions.looks_like_form_phrase("александр", wake_word="вика", fuzzy_threshold=1)
    redmail_actions._pending_candidates.clear()
    assert not redmail_actions.looks_like_form_phrase("александр", wake_word="вика", fuzzy_threshold=1)
    assert _form_phrase("евгений") == redmail_actions.FormReply(handled=False)


def test_lone_first_name_with_too_many_matches_asks_for_surname():
    many = [{"name": f"Фамилия{i} Александр", "email": f"a{i}@x"} for i in range(12)]
    redmail_actions._pending_candidates.clear()
    with patch(FORM + "_redmail_find_contacts", return_value=many), patch(FORM + "_redmail_event_form_set") as mock_set:
        reply = _form_phrase("участников александр")  # «участников» — падежная форма слова-поля
    mock_set.assert_not_called()
    assert reply.spoken == "Александр: совпадений слишком много, назовите фамилию"
    assert redmail_actions._pending_candidates == []  # сотни кандидатов не запоминаем


# --- адресная книга на экране ---------------------------------------------


def _picker_state(query, candidates):
    return {"query": query, "candidates": [dict(c, number=i + 1, checked=False) for i, c in enumerate(candidates)]}


def test_ambiguous_surname_opens_picker_and_describes_numbered_candidates():
    redmail_actions._picker_open = False
    shilkins = [c for c in BOOK if c["name"].startswith("Шилкин")]
    with patch(FORM + "_redmail_find_contacts", side_effect=_fake_find_contacts), patch(
        FORM + "_redmail_event_form_set"
    ) as mock_set, patch(FORM + "_redmail_picker_open", return_value=_picker_state("шилкин", shilkins)) as mock_open:
        reply = _form_phrase("участники шилкин")
    mock_set.assert_not_called()
    mock_open.assert_called_once_with("шилкин")
    assert reply.spoken == (
        "Шилкин: двое — первый Александр, второй Евгений Александрович. Номер или имя, затем принять"
    )
    assert redmail_actions.picker_is_open()
    # книга открыта -> любая фраза считается фразой формы даже без активационного слова
    assert redmail_actions.looks_like_form_phrase("второй", wake_word="вика", fuzzy_threshold=1)

    with patch(FORM + "_redmail_picker_select", return_value={"touched": 1}) as mock_select:
        assert _form_phrase("второй") == redmail_actions.FormReply(handled=True)
        mock_select.assert_called_once_with(number=2, checked=True)
    with patch(FORM + "_redmail_picker_select", return_value={"touched": 1}) as mock_select:
        _form_phrase("первый и третий")
        assert [c[1]["number"] for c in mock_select.call_args_list] == [1, 3]
    with patch(FORM + "_redmail_picker_select", return_value={"touched": 1}) as mock_select:
        _form_phrase("убери второго")
        mock_select.assert_called_once_with(number=2, checked=False)
    with patch(FORM + "_redmail_picker_select", return_value={"touched": 1}) as mock_select:
        _form_phrase("евгений")
        mock_select.assert_called_once_with(query="евгений", checked=True)
    with patch(FORM + "_redmail_picker_select", return_value={"touched": 0}):
        assert _form_phrase("сидоров").spoken == "Сидоров: в списке нет"
    with patch(FORM + "_redmail_picker_select", return_value={"touched": 2}) as mock_select:
        _form_phrase("все")
        mock_select.assert_called_once_with(all_visible=True, checked=True)
    with patch(FORM + "_redmail_picker_accept", return_value=[{"name": "Шилкин Евгений Александрович", "email": "e@x"}]):
        reply = _form_phrase("принять")
    assert reply.spoken == "Участники: Шилкин Евгений Александрович" and not reply.finished
    assert not redmail_actions.picker_is_open()


def test_number_and_accept_in_one_phrase():
    redmail_actions._picker_open = True
    redmail_actions._picker_queue.clear()
    with patch(FORM + "_redmail_picker_select", return_value={"touched": 1}) as mock_select, patch(
        FORM + "_redmail_picker_accept", return_value=[{"name": "Шилкин Евгений Александрович", "email": "e@x"}]
    ) as mock_accept:
        reply = _form_phrase("два принять")
    mock_select.assert_called_once_with(number=2, checked=True)
    mock_accept.assert_called_once()
    assert reply.spoken == "Участники: Шилкин Евгений Александрович"
    assert not redmail_actions.picker_is_open()


def test_second_ambiguous_surname_is_queued_and_opened_after_accept():
    redmail_actions._picker_open = False
    redmail_actions._picker_queue.clear()
    shilkins = [c for c in BOOK if c["name"].startswith("Шилкин")]
    book2 = BOOK + [{"name": "Шапошников Андрей", "email": "sh.a@x"}, {"name": "Шапошникова Алевтина", "email": "sh.b@x"}]
    find = lambda q: redmail_actions._local_matches(q.split(), book2)  # noqa: E731
    opens: list[str] = []

    def fake_open(query):
        opens.append(query)
        cands = find(query)
        return _picker_state(query, cands)

    with patch(FORM + "_redmail_find_contacts", side_effect=find), patch(FORM + "_redmail_event_form_set") as mock_set, patch(
        FORM + "_redmail_picker_open", side_effect=fake_open
    ):
        reply = _form_phrase("участники будько шилкин шапошников")
        mock_set.assert_called_once_with(add_participants=["budko@example.com"])
        assert opens == ["шилкин"]  # книга открыта для первой фамилии
        assert reply.spoken == (
            "Добавлен Будько Евгений. Шилкин: двое — первый Александр, второй Евгений Александрович. "
            "Номер или имя, затем принять. Шапошников: двое — спрошу следом"
        )
        with patch(FORM + "_redmail_picker_select", return_value={"touched": 1}), patch(
            FORM + "_redmail_picker_accept", return_value=[shilkins[1]]
        ):
            reply = _form_phrase("второй принять")
        assert opens == ["шилкин", "шапошников"]  # после «принять» открылась книга для следующей фамилии
        assert reply.spoken == (
            "Участники: Шилкин Евгений Александрович. Далее Шапошников: двое — первый Андрей, второй Алевтина. "
            "Номер или имя, затем принять"
        )
        assert redmail_actions.picker_is_open()
    redmail_actions._picker_open = False


def test_book_closed_by_mouse_lets_the_phrase_through_as_a_field():
    redmail_actions._picker_open = True
    with patch(FORM + "_redmail_picker_select", side_effect=RedmailError("Адресная книга не открыта.")), patch(
        FORM + "_redmail_event_form_set"
    ) as mock_set:
        reply = _form_phrase("тема планёрка")
    mock_set.assert_called_once_with(subject="планёрка")  # фраза ушла в форму, режим не окончен
    assert reply.handled and not reply.finished
    assert not redmail_actions.picker_is_open()


def test_picker_falls_back_to_spoken_list_when_book_cannot_open():
    redmail_actions._picker_open = False
    with patch(FORM + "_redmail_find_contacts", side_effect=_fake_find_contacts), patch(
        FORM + "_redmail_event_form_set"
    ), patch(FORM + "_redmail_picker_open", side_effect=RedmailError("Форма встречи не открыта.")):
        reply = _form_phrase("участники шилкин")
    assert reply.spoken == "Шилкин: найдено двое — Александр, Евгений Александрович. Уточните имя"
    assert not redmail_actions.picker_is_open()


def test_open_address_book_command_and_cancel():
    redmail_actions._picker_open = False
    with patch(FORM + "_redmail_picker_open", return_value=_picker_state("шапошников", [{"name": "Шапошников Андрей", "email": "s@x"}])) as mock_open:
        reply = _form_phrase("открой адресную книгу шапошников")
    mock_open.assert_called_once_with("шапошников")
    assert reply.spoken.startswith("Адресная книга открыта, в списке 1")
    with patch(FORM + "_redmail_picker_cancel") as mock_cancel:
        reply = _form_phrase("отмена")
    mock_cancel.assert_called_once()
    assert reply.spoken == "Книга закрыта" and not redmail_actions.picker_is_open()


def test_participants_not_found_names_who():
    reply, mock_set = _participants("пригласить жилкин")
    mock_set.assert_not_called()
    assert reply.spoken == "Участник Жилкин не найден"
    assert reply.spoken_fallback == "Участник не найден"


def test_participants_mixed_outcomes_in_one_phrase():
    reply, mock_set = _participants("участники будько шилкин жилкин")
    mock_set.assert_called_once_with(add_participants=["budko@example.com"])
    assert reply.spoken == (
        "Добавлен Будько Евгений. Шилкин: найдено двое — Александр, Евгений Александрович. Уточните имя. "
        "Участник Жилкин не найден"
    )


def test_form_phrase_date_with_time_sets_both():
    with patch(FORM + "_redmail_event_form_set") as mock_set:
        reply = _form_phrase("дата пятнадцатое сентября четырнадцать ноль ноль")
    assert reply.handled and reply.spoken is None
    kwargs = mock_set.call_args[1]
    assert kwargs["date"].endswith("-09-15") and kwargs["time"] == "14:00"


def test_looks_like_form_phrase_and_resume():
    assert redmail_actions.looks_like_form_phrase("участники шапошников", wake_word="вика", fuzzy_threshold=1)
    assert redmail_actions.looks_like_form_phrase("вика сохранить", wake_word="вика", fuzzy_threshold=1)
    assert not redmail_actions.looks_like_form_phrase("открой браузер", wake_word="вика", fuzzy_threshold=1)
    with patch(FORM + "_redmail_event_form_state", return_value={"summary": "x"}):
        assert redmail_actions.redmail_event_form_resume({}).enter_form_mode is True
    with patch(FORM + "_redmail_event_form_state", side_effect=RedmailError("Форма встречи не открыта.")):
        with pytest.raises(ActionError, match="не открыто"):
            redmail_actions.redmail_event_form_resume({})


def test_form_phrase_save_and_cancel_finish_the_mode():
    with patch(FORM + "_redmail_event_form_save") as mock_save:
        reply = _form_phrase("сохранить")
    mock_save.assert_called_once()
    assert reply == redmail_actions.FormReply(handled=True, spoken="Встреча сохранена", finished=True)
    with patch(FORM + "_redmail_event_form_cancel") as mock_cancel:
        reply = _form_phrase("отменить")
    mock_cancel.assert_called_once()
    assert reply == redmail_actions.FormReply(handled=True, spoken="Отменено", finished=True)


def test_form_phrase_save_rejected_keeps_mode_open():
    with patch(FORM + "_redmail_event_form_save", side_effect=RedmailError("Нельзя запланировать встречу на прошедшую дату/время.")):
        reply = _form_phrase("сохранить")
    assert reply == redmail_actions.FormReply(handled=True, spoken="Нельзя запланировать встречу на прошедшую дату")


def test_form_phrase_window_closed_by_mouse_ends_mode_silently():
    with patch(FORM + "_redmail_event_form_set", side_effect=RedmailError("Форма встречи не открыта.")):
        reply = _form_phrase("тема планёрка")
    assert reply == redmail_actions.FormReply(handled=True, spoken=None, finished=True)


def test_form_phrase_unrelated_speech_is_ignored():
    reply = _form_phrase("ну что там с обедом")
    assert reply == redmail_actions.FormReply(handled=False)


def test_every_spoken_phrase_has_a_recording_entry():
    """Все фразы, которые redmail-команды могут произнести, обязаны быть в
    feedback._PRERECORDED_PHRASES — иначе вместо них прозвучит общее
    «Не удалось выполнить команду»."""
    from audioreferent import feedback
    from audioreferent.redmail_actions import _REDMAIL_ERROR_PHRASES

    spoken = {
        "Запускаю почту, повторите команду",
        "Не расслышала тему события",
        "Не расслышала время события",
        "Не расслышала, на какое время перенести",
        "Событие не найдено",
        "Найдено несколько похожих событий, уточните тему",
        # режим заполнения формы
        "Слушаю",
        "Не поняла дату",
        "Не поняла время",
        "Не поняла продолжительность",
        "Не поняла повторение",
        "Участник не найден",
        "Встреча сохранена",
        "Отменено",
        "Нельзя запланировать встречу на прошедшую дату",
    } | {phrase for _marker, phrase in _REDMAIL_ERROR_PHRASES}
    missing = spoken - set(feedback._PRERECORDED_PHRASES)
    assert not missing, missing

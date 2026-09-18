import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from audioreferent import memory_saver

# Кусок настоящего /proc/self/maps: куча, большая безымянная область (в ней
# и лежит модель), маленькая безымянная, файловое отображение, стек.
MAPS = """\
55d0f0a00000-55d0f0a21000 r--p 00000000 103:05 1234567 /usr/bin/python3.11
55d0f2000000-55d0f2a00000 rw-p 00000000 00:00 0 [heap]
7f2a00000000-7f2a4b000000 rw-p 00000000 00:00 0
7f2a4b000000-7f2a4b100000 rw-p 00000000 00:00 0
7f2a80000000-7f2ac0000000 r--p 00000000 103:05 7654321 /usr/share/audioreferent/vosk-model/graph/HCLG.fst
7f2ad0000000-7f2ad4000000 r-xp 00000000 103:05 1111111 /lib64/libvosk.so
7ffd12340000-7ffd12361000 rw-p 00000000 00:00 0 [stack]
"""


def test_large_anonymous_ranges_picks_heap_and_big_anon_only():
    ranges = memory_saver.large_anonymous_ranges(MAPS, min_bytes=8 * 1024 * 1024)
    sizes = [size for _start, size in ranges]
    assert sizes == [0xA00000, 0x4B000000]  # куча 10 МБ и безымянная область 1,2 ГБ
    starts = [start for start, _size in ranges]
    assert starts == [0x55D0F2000000, 0x7F2A00000000]


def test_large_anonymous_ranges_skips_files_stack_and_small():
    ranges = memory_saver.large_anonymous_ranges(MAPS, min_bytes=8 * 1024 * 1024)
    covered = {start for start, _ in ranges}
    assert 0x7F2A80000000 not in covered  # файл модели — и так без свопа
    assert 0x7F2AD0000000 not in covered  # код библиотеки
    assert 0x7FFD12340000 not in covered  # стек
    assert 0x7F2A4B000000 not in covered  # 1 МБ — мельче порога


def test_page_out_advises_each_range_and_reports_megabytes():
    calls = []

    class FakeLibc:
        def madvise(self, addr, size, advice):
            calls.append((addr.value, size.value, advice))
            return 0

    with patch("audioreferent.memory_saver.sys.platform", "linux"), patch(
        "audioreferent.memory_saver.ctypes.CDLL", return_value=FakeLibc()
    ), patch("audioreferent.memory_saver.Path.read_text", return_value=MAPS), patch(
        "audioreferent.memory_saver.rss_mb", return_value=1148.0
    ):
        advised = memory_saver.page_out()
    assert [advice for _addr, _size, advice in calls] == [memory_saver.MADV_PAGEOUT] * 2
    assert advised == (0xA00000 + 0x4B000000) / 1024 / 1024


def test_page_out_is_a_no_op_off_linux():
    with patch("audioreferent.memory_saver.sys.platform", "win32"), patch(
        "audioreferent.memory_saver.ctypes.CDLL"
    ) as cdll:
        assert memory_saver.page_out() == 0.0
    cdll.assert_not_called()


def test_page_out_survives_a_failing_madvise():
    class FakeLibc:
        def madvise(self, addr, size, advice):
            return -1  # ядро отказало — просто ничего не вытеснили

    with patch("audioreferent.memory_saver.sys.platform", "linux"), patch(
        "audioreferent.memory_saver.ctypes.CDLL", return_value=FakeLibc()
    ), patch("audioreferent.memory_saver.Path.read_text", return_value=MAPS):
        assert memory_saver.page_out() == 0.0

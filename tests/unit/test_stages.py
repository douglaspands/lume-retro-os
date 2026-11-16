import pytest

from r36os.stages import StageTimer, format_duration


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_summary_lists_stages_skipped_and_total():
    clock = Clock()
    timer = StageTimer(clock=clock)
    with timer.stage("kernel"):
        clock.t += 125
    timer.skip("u-boot", "not needed")
    with timer.stage("rootfs"):
        clock.t += 4.5
    lines = timer.summary()
    assert lines[0] == "build summary:"
    assert lines[1] == "  kernel  2m05s"
    assert lines[2] == "  u-boot  skipped (not needed)"
    assert lines[3] == "  rootfs  4.5s"
    assert lines[4] == "  total   2m10s"


def test_error_marks_stage_and_reraises():
    clock = Clock()
    timer = StageTimer(clock=clock)
    with pytest.raises(RuntimeError):
        with timer.stage("kernel"):
            clock.t += 3
            raise RuntimeError("boom")
    assert "  kernel  3.0s (failed)" in timer.summary()


def test_print_summary_in_finally_still_prints_on_error():
    clock = Clock()
    printed = []
    timer = StageTimer(clock=clock, out=printed.append)
    with pytest.raises(ValueError):
        try:
            with timer.stage("a"):
                clock.t += 1
                raise ValueError("x")
        finally:
            timer.print_summary()
    assert any("failed" in line for line in printed)
    assert printed[-1].strip().startswith("total")


def test_extra_lines_come_after_total():
    timer = StageTimer(clock=Clock())
    timer.add_line("max temp: 80C")
    assert timer.summary()[-1] == "max temp: 80C"


def test_format_duration():
    assert format_duration(0.04) == "0.0s"
    assert format_duration(59.9) == "59.9s"
    assert format_duration(3723) == "1h02m03s"

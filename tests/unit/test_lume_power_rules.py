"""udev rules of lume-power that open sysfs switches to the video group."""
from pathlib import Path

RULES = Path(__file__).resolve().parents[2] / "aports/lume-power/files/etc/udev/rules.d"


def _rule(name: str) -> str:
    lines = [l for l in (RULES / name).read_text().splitlines() if l and not l.startswith("#")]
    assert len(lines) == 1, lines
    return lines[0]


def test_backlight_writable_by_video():
    r = _rule("90-lume-backlight.rules")
    assert 'SUBSYSTEM=="backlight"' in r
    assert 'RUN+="/bin/chgrp video /sys%p/brightness"' in r
    assert 'RUN+="/bin/chmod g+w /sys%p/brightness"' in r


def test_readahead_only_on_the_r36s_card():
    # device-fixes 5.5: 512 KiB from the R36S J1 measurement (D6); the GA36 keeps the default
    r = _rule("90-lume-readahead.rules")
    assert 'SUBSYSTEM=="block"' in r
    assert 'KERNEL=="mmcblk[0-9]"' in r
    assert 'DRIVERS=="dwmmc_rockchip"' in r
    assert 'ATTR{queue/read_ahead_kb}="512"' in r


def test_panfrost_profiling_writable_by_video():
    # lume-hud-actions 4.4: the R36S J1 found profiling root-only (0644)
    r = _rule("90-lume-gpu-profiling.rules")
    assert 'SUBSYSTEM=="platform"' in r
    assert 'ACTION=="add|bind"' in r
    assert 'DRIVER=="panfrost"' in r
    assert 'RUN+="/bin/chgrp video /sys%p/profiling"' in r
    assert 'RUN+="/bin/chmod g+w /sys%p/profiling"' in r

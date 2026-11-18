"""Tests for the power profile validator (openspec game-governor, node 1.1).

The library is POSIX shell, so every test runs it with `sh` against a fake sysfs tree.
"""

import subprocess
from pathlib import Path

from lume_tool.paths import REPO_ROOT

LIB = REPO_ROOT / "aports/lume-power/files/usr/libexec/lume/power-profiles.sh"

GA36_FREQS = "120000 240000 408000 600000 816000 1008000"


def make_sysfs(root: Path, freqs=GA36_FREQS, governors="performance schedutil ondemand", cores=4,
               gpu="144000000 288000000 432000000") -> Path:
    cpufreq = root / "devices/system/cpu/cpu0/cpufreq"
    cpufreq.mkdir(parents=True)
    (cpufreq / "scaling_available_frequencies").write_text(freqs + "\n")
    (cpufreq / "scaling_available_governors").write_text(governors + "\n")
    for n in range(1, cores):
        (root / f"devices/system/cpu/cpu{n}").mkdir(parents=True)
    # files that are not cores must not be counted
    (root / "devices/system/cpu/cpufreq").mkdir(exist_ok=True)
    (root / "devices/system/cpu/online").write_text("0-3\n")
    if gpu:
        gd = root / "class/devfreq/1c40000.gpu"
        gd.mkdir(parents=True)
        (gd / "available_frequencies").write_text(gpu + "\n")
    return root


def run(sysfs: Path, call: str):
    script = f'PP_SYS="{sysfs}"; . "{LIB}"; {call}'
    p = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


VALID = """\
# a comment
profile boot    governor=performance
profile menu    governor=schedutil min=120000 max=816000 cores=2 gpu_max=144000000   # trailing
profile idle    governor=schedutil min=120000 max=408000 cores=1
profile light   governor=schedutil min=600000 max=1008000 cores=2
profile heavy   governor=performance cores=4
profile game    governor=schedutil cores=4
profile ond     governor=ondemand min=816000 max=1008000 cores=4 up_threshold=30 sampling_down_factor=10 controller=load
limit game_min=600000
class nes light
class psx heavy
core snes9x2005_plus ond
battery warn=5 critical=3
"""


def lines(out: str):
    return out.splitlines()


def test_valid_file_is_accepted_and_floor_added_to_game_profiles(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", VALID)
    rc, out, err = run(sys, f'pp_load "{img}"')
    assert rc == 0, err
    got = lines(out)
    assert "profile image boot governor=performance" in got
    # not a game profile: no floor added
    assert "profile image menu governor=schedutil min=120000 max=816000 cores=2 gpu_max=144000000" in got
    # game profiles without min get the floor
    assert "profile image heavy governor=performance cores=4 min=600000" in got
    assert "profile image game governor=schedutil cores=4 min=600000" in got
    # explicit min above the floor stays
    assert "profile image ond governor=ondemand min=816000 max=1008000 cores=4 up_threshold=30 sampling_down_factor=10 controller=load" in got
    assert "limit image game_min=600000" in got
    assert "class image nes light" in got
    assert "core image snes9x2005_plus ond" in got
    assert "battery image warn=5 critical=3" in got
    assert not any(line.startswith("refused") for line in got)
    assert err == ""


def test_clock_outside_the_table_refuses_the_profile(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", "profile light governor=schedutil min=600000 max=1000000\nprofile boot governor=performance\n")
    rc, out, err = run(sys, f'pp_load "{img}"')
    assert rc == 1
    assert "refused image profile light max=1000000 not in the clock table" in out
    assert not any(line.startswith("profile image light") for line in lines(out))
    assert "profile image boot governor=performance" in lines(out)  # the rest still loads
    assert "rejected profile light" in err


def test_governor_not_available_and_cores_range(tmp_path):
    sys = make_sysfs(tmp_path / "sys", governors="performance schedutil")
    img = write(tmp_path / "x.conf", "profile a governor=ondemand\nprofile b cores=5\nprofile c cores=0\nprofile d gpu_max=1\nprofile e bogus=1\nprofile f cores=4\n")
    rc, out, _ = run(sys, f'pp_load "{img}"')
    assert rc == 1
    got = lines(out)
    assert "refused image profile a governor ondemand not available" in got
    assert "refused image profile b cores=5 out of range 1..4" in got
    assert "refused image profile c cores=0 out of range 1..4" in got
    assert "refused image profile d gpu_max=1 not in the devfreq table" in got
    assert "refused image profile e unknown key bogus" in got
    assert "profile image f cores=4" in got


def test_unknown_line_is_reported_and_skipped(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "x.conf", "turbo on\nprofile boot governor=performance\n")
    rc, out, err = run(sys, f'pp_load "{img}"')
    assert rc == 1
    assert "refused image turbo - unknown line turbo" in lines(out)
    assert "profile image boot governor=performance" in lines(out)
    assert "FAIL" in err


def test_card_overrides_lines_and_a_refused_card_line_keeps_the_image(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", VALID)
    card = write(
        tmp_path / "power.conf",
        "profile light governor=ondemand min=816000 max=1008000 cores=3\n"  # valid override
        "profile heavy governor=performance min=240000\n"  # below the floor: refused
        "class nes game\n"
        "idle after=300\n"
        "enabled 0\n",
    )
    rc, out, err = run(sys, f'pp_load "{img}" "{card}"')
    assert rc == 1
    got = lines(out)
    assert "profile card light governor=ondemand min=816000 max=1008000 cores=3" in got
    assert not any(line.startswith("profile image light") for line in got)
    assert "refused card profile heavy min 240000 below game floor 600000" in got
    assert "profile image heavy governor=performance cores=4 min=600000" in got  # image stands
    assert "class card nes game" in got
    assert not any(line.startswith("class image nes") for line in got)
    assert "class image psx heavy" in got
    assert "idle card after=300" in got
    assert "enabled card 0" in got


def test_missing_card_file_is_not_an_error(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", VALID)
    rc, _, _ = run(sys, f'pp_load "{img}" "{tmp_path}/none.conf"')
    assert rc == 0


def test_game_profile_min_below_floor_is_refused_and_class_falls_back(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", "limit game_min=600000\nprofile low governor=schedutil min=240000\nclass nes low\nprofile menu min=120000\n")
    rc, out, _ = run(sys, f'pp_load "{img}"')
    assert rc == 1
    got = lines(out)
    assert "refused image profile low min 240000 below game floor 600000" in got
    assert "refused image class nes profile low is refused or unknown" in got
    assert "profile image menu min=120000" in got  # menu is not a game profile
    # max below the floor is refused too
    img2 = write(tmp_path / "b.conf", "limit game_min=600000\nprofile game max=408000\n")
    _, out2, _ = run(sys, f'pp_load "{img2}"')
    assert "refused image profile game max 408000 below game floor 600000" in lines(out2)


def test_limit_in_the_card_file_is_ignored(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", "limit game_min=600000\nprofile game governor=schedutil\n")
    card = write(tmp_path / "power.conf", "limit game_min=120000\n")
    rc, out, err = run(sys, f'pp_load "{img}" "{card}"')
    assert rc == 1
    got = lines(out)
    assert "refused card limit - limit is only accepted in the image file" in got
    assert "limit image game_min=600000" in got
    assert "profile image game governor=schedutil min=600000" in got
    assert "FAIL" in err
    rc, floor, _ = run(sys, f'pp_floor "{img}"')
    assert floor.strip() == "600000"


def test_game_min_not_an_opp_refuses_the_file_and_falls_back_to_the_largest_opp(tmp_path):
    sys = make_sysfs(tmp_path / "sys", freqs="120000 240000 408000 504000 648000 1008000")
    img = write(tmp_path / "ga36.conf", "limit game_min=600000\nprofile boot governor=performance\n")
    rc, out, err = run(sys, f'pp_load "{img}"')
    assert rc == 2
    assert lines(out) == ["refused image limit game_min game_min 600000 is not an OPP"]
    assert "whole file refused" in err
    _, floor, _ = run(sys, f'pp_floor "{img}"')
    assert floor.strip() == "504000"  # largest OPP <= 600000


def test_no_limit_means_no_floor(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "r36s.conf", "profile game governor=schedutil\n")
    rc, out, _ = run(sys, f'pp_load "{img}"')
    assert rc == 0
    assert lines(out) == ["profile image game governor=schedutil"]
    _, floor, _ = run(sys, f'pp_floor "{img}"')
    assert floor.strip() == ""


def test_floor_from_cpuinfo_range_when_there_is_no_table(tmp_path):
    sys = tmp_path / "sys"
    cf = sys / "devices/system/cpu/cpu0/cpufreq"
    cf.mkdir(parents=True)
    (cf / "cpuinfo_min_freq").write_text("120000\n")
    (cf / "cpuinfo_max_freq").write_text("1008000\n")
    (cf / "scaling_available_governors").write_text("schedutil\n")
    img = write(tmp_path / "x.conf", "limit game_min=600000\nprofile game governor=schedutil\n")
    rc, out, _ = run(sys, f'pp_load "{img}"')
    assert rc == 0
    assert "profile image game governor=schedutil min=600000" in lines(out)


def test_unreadable_image_file(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    rc, out, _ = run(sys, f'pp_load "{tmp_path}/missing.conf"')
    assert rc == 2
    assert out.strip() == "refused image file - unreadable"


def test_enabled_and_idle_values_are_checked(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    card = write(tmp_path / "power.conf", "enabled 2\nidle after=abc\nbattery warn=3 critical=5\n")
    img = write(tmp_path / "x.conf", "profile boot governor=performance\n")
    rc, out, _ = run(sys, f'pp_load "{img}" "{card}"')
    assert rc == 1
    got = lines(out)
    assert "refused card enabled - enabled needs 0 or 1" in got
    assert "refused card idle - idle needs after=<seconds>" in got
    assert any(x.startswith("refused card battery -") for x in got)


def test_gpu_min_and_controller_auto(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "x.conf",
                "profile a controller=auto gpu_min=144000000 gpu_max=432000000\n"
                "profile b gpu_min=1\n"
                "profile c gpu_min=432000000 gpu_max=144000000\n"
                "profile d controller=turbo\n")
    rc, out, _ = run(sys, f'pp_load "{img}"')
    assert rc == 1
    got = lines(out)
    assert "profile image a controller=auto gpu_min=144000000 gpu_max=432000000" in got
    assert "refused image profile b gpu_min=1 not in the devfreq table" in got
    assert "refused image profile c gpu_min 432000000 above gpu_max 144000000" in got
    assert "refused image profile d controller=turbo unknown" in got


KEY = "0123456789abcdef"


def test_game_lines_only_on_the_card_with_a_hex_key(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", VALID + f"game {KEY} heavy\n")
    card = write(tmp_path / "power.conf",
                 f"profile mine min=240000\ngame {KEY} light\n"
                 "game Some-Game-Name light\ngame fedcba9876543210 nope\n"
                 "game 1111222233334444 mine\n")
    rc, out, _ = run(sys, f'pp_load "{img}" "{card}"')
    assert rc == 1
    got = lines(out)
    assert f"game card {KEY} light" in got
    assert f"refused image game {KEY} game is only accepted in the card file" not in got  # card won
    assert "refused card game Some-Game-Name game key Some-Game-Name is not 16 hex digits" in got
    assert "refused card game fedcba9876543210 profile nope is refused or unknown" in got
    # a profile used by a game line is a game profile: the floor applies
    assert "refused card profile mine min 240000 below game floor 600000" in got
    img2 = write(tmp_path / "b.conf", VALID + f"game {KEY} heavy\n")
    _, out2, _ = run(sys, f'pp_load "{img2}"')
    assert f"refused image game {KEY} game is only accepted in the card file" in lines(out2)


def test_state_header_and_records(tmp_path):
    sys = make_sysfs(tmp_path / "sys")
    img = write(tmp_path / "ga36.conf", VALID)
    card = write(tmp_path / "power.conf", "idle after=300\nprofile heavy min=240000\n")
    rc, out, _ = run(sys, f'PP_SCENARIO=game PP_PROFILE=light pp_state ga36 "{img}" "{card}"')
    assert rc == 0
    got = lines(out)
    assert got[0] == "console ga36"
    assert "enabled default 1" in got
    assert f"cpu_freqs {GA36_FREQS}" in got
    assert "cpu_governors performance schedutil ondemand" in got
    assert "cpu_cores 4" in got
    assert "gpu_freqs 144000000 288000000 432000000" in got
    assert "game_min 600000" in got
    assert "idle card after=300" in got
    assert "idle default after=120" not in got
    assert "refused card profile heavy min 240000 below game floor 600000" in got
    assert got[-2:] == ["scenario game", "current light"]

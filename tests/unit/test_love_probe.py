"""The LÖVE probe (game-experience-tuning 2.3): packaging, script validity, push_love step."""
import io
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from lume_tool import dev_run, lovepack, scripts

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests" / "device" / "love-probe"
SCRIPT = ROOT / "tests" / "device" / "scripts" / "love-probe.toml"


def test_love_package_is_reproducible_and_has_main_lua():
    a, b = lovepack.build_love(PROBE), lovepack.build_love(PROBE)
    assert a == b
    z = zipfile.ZipFile(io.BytesIO(a))
    assert z.namelist() == ["conf.lua", "main.lua"]
    assert z.testzip() is None
    assert all(i.date_time == lovepack.FIXED_TIME for i in z.infolist())


def test_love_package_refuses_a_dir_without_main_lua(tmp_path):
    (tmp_path / "x.lua").write_text("")
    with pytest.raises(lovepack.LovePackError):
        lovepack.build_love(tmp_path)
    with pytest.raises(lovepack.LovePackError):
        lovepack.build_love(tmp_path / "missing")


def test_hidden_files_are_not_packed(tmp_path):
    (tmp_path / "main.lua").write_text("")
    (tmp_path / ".swp").write_text("x")
    assert zipfile.ZipFile(io.BytesIO(lovepack.build_love(tmp_path))).namelist() == ["main.lua"]


def test_probe_source_writes_the_expected_keys():
    text = (PROBE / "main.lua").read_text(encoding="utf-8")
    for key in ("LANG=", "LANGUAGE=", "locales=", "TZ=", "time="):
        assert f'"{key}' in text
    assert "/run/lume/love-probe.txt" in text
    assert "getPreferredLocales" in text and "love.event.quit" in text


def test_probe_script_is_valid_and_private():
    script = scripts.load(SCRIPT)
    assert script.consoles == ["ga36", "r36s"]
    types = [s.type for s in script.steps]
    assert types.count("open_game") == 2 and types.count("push_love") == 1
    text = SCRIPT.read_text(encoding="utf-8")
    assert "LANG=en_US.UTF-8" in text and "LANG=pt_BR.UTF-8" in text
    # the cleanup restores the language and removes the probe
    assert "restore the launcher language" in text and "rm -f /storage/roms/love/0-lume-probe.love" in text


def _sh_steps(prefix):
    return [s for s in scripts.load(SCRIPT).steps if s.type == "sh" and s.name.startswith(prefix)]


def test_value_check_commands_work_against_a_probe_output(tmp_path):
    out = tmp_path / "love-probe.txt"
    good = ("LANG=pt_BR.UTF-8\nLANGUAGE=pt_BR:pt\nlocales=pt_BR,pt\n"
            "TZ=:/usr/share/zoneinfo/Europe/Lisbon\ntime=2026-11-19 10:00\n")
    cmd = _sh_steps("check the values (pt)")[0].fields["command"].replace(
        "/run/lume/love-probe.txt", str(out))

    def run():
        return subprocess.run(["sh", "-c", cmd], capture_output=True).returncode

    out.write_text(good)
    assert run() == 0
    out.write_text(good.replace("pt_BR.UTF-8", "en_US.UTF-8"))
    assert run() != 0
    # LÖVE 11.5 (the image) has no love.system.getPreferredLocales (GA36, 2026-11-20): the probe
    # writes n/a and LANG/LANGUAGE carry the language; a wrong locale still fails
    out.write_text(good.replace("locales=pt_BR,pt", "locales=n/a"))
    assert run() == 0
    out.write_text(good.replace("locales=pt_BR,pt", "locales=en_US,en"))
    assert run() != 0
    out.write_text("")
    assert run() != 0


def test_time_check_accepts_now_and_a_minute_ago_only(tmp_path):
    if subprocess.run(["date", "-d", "@0"], capture_output=True).returncode != 0:
        pytest.skip("date -d @epoch not available")
    out = tmp_path / "love-probe.txt"
    base = _sh_steps("check the time against the console (en)")[0].fields["command"]
    base = base.replace("/run/lume/love-probe.txt", str(out)).replace(
        "$(head -n 1 /etc/timezone)", "UTC")

    def run(shift):
        stamp = subprocess.run(
            ["date", "-u", "-d", f"@{int(subprocess.run(['date', '+%s'], capture_output=True, text=True).stdout) + shift}",
             "+%Y-%m-%d %H:%M"], capture_output=True, text=True).stdout.strip()
        out.write_text(f"time={stamp}\n")
        return subprocess.run(["sh", "-c", base], capture_output=True).returncode

    assert run(0) == 0
    assert run(-60) == 0
    assert run(-300) != 0
    assert run(3600) != 0


def test_push_love_step_sends_the_packed_game():
    sent = []
    script = scripts.loads(
        'consoles = ["ga36"]\n[[step]]\nname = "send"\ntype = "push_love"\n'
        'source = "tests/device/love-probe"\ndest = "/storage/roms/love/p.love"\n')

    class Console:
        def __call__(self, cmd):
            return "0\n" if "wc -l" in cmd else ""

    ctx = dev_run.Context("h", run=Console(), push_love=lambda s, d: sent.append((s, d)))
    assert dev_run.run_script(script, ctx, "ga36", out=io.StringIO()) == 0
    assert sent == [("tests/device/love-probe", "/storage/roms/love/p.love")]


@pytest.mark.parametrize("source,dest", [
    ("../x", "/a/b.love"), ("/abs/x", "/a/b.love"), ("tests/device", "/a/b.love"),
    ("tests/other/x", "/a/b.love"), ("tests/device/x", "rel/b.love"),
    ("tests/device/x", "/a/b.zip"), ("tests/device/x", "/a/../b.love"),
    ("tests/device/x", "/a b/c.love"),
])
def test_push_love_validation(source, dest):
    text = ('consoles = ["ga36"]\n[[step]]\nname = "s"\ntype = "push_love"\n'
            f'source = "{source}"\ndest = "{dest}"\n')
    with pytest.raises(scripts.ScriptError):
        scripts.loads(text)

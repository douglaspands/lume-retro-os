"""build-speed 9.3 (D7, P-36): ARM compiles through distcc to a native cross gcc, opt-in."""

from contextlib import contextmanager

from r36os import distcc, packages
from r36os.heat import BUILD_LABEL
from r36os.targets import get_target


def test_selected_reads_names_and_all_from_the_environment():
    assert distcc.selected({}) == set()
    assert distcc.selected({"R36OS_DISTCC": "a, b,,c"}) == {"a", "b", "c"}
    assert distcc.selected({"R36OS_DISTCC": "all"}) == {"all"}


def test_only_emulated_architectures_use_distcc():
    assert distcc.uses_distcc("core", "armv7", {"core"})
    assert distcc.uses_distcc("core", "aarch64", {"all"})
    assert not distcc.uses_distcc("core", "x86_64", {"all"})
    assert not distcc.uses_distcc("other", "armv7", {"core"})


def test_groups_keep_the_build_order():
    names = ["a", "core1", "core2", "b", "core3"]
    chosen = {"core1", "core2", "core3"}
    assert distcc.groups(names, "armv7", chosen) == [
        (False, ["a"]), (True, ["core1", "core2"]), (False, ["b"]), (True, ["core3"])]
    assert distcc.groups(names, "armv7", set()) == [(False, names)]
    assert distcc.groups([], "armv7", chosen) == []


def test_client_env_never_falls_back_to_a_local_compile():
    env = distcc.client_env("aarch64", 6)
    assert env["CCACHE_PREFIX"] == "distcc"
    assert env["DISTCC_HOSTS"] == "127.0.0.1:3633/6"  # an IP: "localhost" compiles locally
    assert env["DISTCC_FALLBACK"] == "0"


def test_distccd_is_low_priority_loopback_only_and_paused_by_the_heat_guard():
    argv = distcc.distccd_argv("armv7", 4)
    assert argv[:6] == ["nice", "-n", "19", "ionice", "-c", "3"]
    assert ["--label", BUILD_LABEL] == argv[argv.index("--label"):argv.index("--label") + 2]
    assert argv[argv.index("--listen") + 1] == "127.0.0.1"
    assert argv[argv.index("--allow") + 1] == "127.0.0.1"
    assert argv[argv.index("--port") + 1] == "3632"
    assert argv[argv.index("--jobs") + 1] == "4"
    assert "localhost/r36os-distcc:armv7" in argv


def test_remote_compiles_counts_the_ok_jobs():
    log = ("distccd[1] (dcc_job_summary) client: 127.0.0.1:1 COMPILE_OK exit:0 x\n"
           "distccd[1] job complete\n"
           "distccd[2] (dcc_job_summary) client: 127.0.0.1:2 COMPILE_OK exit:0 y\n")
    assert distcc.remote_compiles(log) == 2


def test_gcc_pin_names_a_commit_and_a_version():
    assert len(distcc.GCC_COMMIT) == 40
    assert distcc.GCC_VERSION.count("-r") == 1
    assert set(distcc.PORTS) == set(distcc.TRIPLETS)


def test_abuild_container_gets_distcc_env_and_its_own_ccache(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("R36OS_JOBS", "3")
    monkeypatch.delenv("R36OS_CCACHE", raising=False)
    monkeypatch.setattr(packages, "ensure_builder", lambda t: "b")
    ga36 = get_target("ga36")
    plain = packages._container(ga36, tmp_path)
    assert "CCACHE_PREFIX" not in plain.env and "CCACHE_DISABLE" not in plain.env
    assert plain.volumes[tmp_path / "cache" / "ccache" / "armv7"] == "/cache/ccache"
    c = packages._container(ga36, tmp_path, distcc=True)
    assert c.env["DISTCC_HOSTS"] == "127.0.0.1:3632/3"
    assert c.volumes[tmp_path / "cache" / "ccache" / "armv7-distcc"] == "/cache/ccache"
    monkeypatch.setenv("R36OS_CCACHE", "0")
    assert packages._container(ga36, tmp_path).env["CCACHE_DISABLE"] == "1"


def test_build_packages_runs_distccd_only_around_the_chosen_packages(tmp_path, monkeypatch):
    calls = []

    class FakeContainer:
        def __init__(self, through):
            self.through = through
            self.volumes, self.env = {}, {}

        def sh(self, script):
            calls.append(("sh", self.through, script))

    @contextmanager
    def fake_distccd(arch):
        calls.append(("distccd-start", arch))
        yield
        calls.append(("distccd-stop", arch))

    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setattr(packages, "_container",
                        lambda t, a, cargo_target=False, distcc=False, repodest=None:
                        FakeContainer(distcc))
    monkeypatch.setattr(distcc, "distccd", fake_distccd)
    # one container per aport (build-speed 6.1); what it built is not looked at here
    monkeypatch.setattr(packages, "_settle", lambda *a, **kw: [])
    monkeypatch.setattr(packages, "clean_repo", lambda arch: False)
    aports = tmp_path / "aports"
    for n in ("a", "core"):
        (aports / n).mkdir(parents=True)
        (aports / n / "APKBUILD").write_text(f"pkgname={n}\npkgver=1\npkgrel=0\n")
    ga36 = get_target("ga36")

    monkeypatch.delenv("R36OS_DISTCC", raising=False)
    packages.build_packages(ga36, ["a", "core"], aports=aports)
    assert [c[:2] for c in calls] == [("sh", False)] * 2  # unchanged without the variable

    calls.clear()
    monkeypatch.setenv("R36OS_DISTCC", "core")
    packages.build_packages(ga36, ["a", "core"], aports=aports)
    assert [c[:2] for c in calls] == [
        ("sh", False), ("distccd-start", "armv7"), ("sh", True), ("distccd-stop", "armv7")]
    assert "apk add -q distcc" in calls[2][2] and "/core &&" in calls[2][2]
    assert "distcc" not in calls[0][2]

    calls.clear()
    packages.build_packages(ga36, ["core"], aports=aports, checksum=True)
    assert [c[:2] for c in calls] == [("sh", False)]  # checksum never needs a compiler

    calls.clear()
    packages.build_packages(get_target("vm"), ["core"], aports=aports)
    assert [c[:2] for c in calls] == [("sh", False)]  # x86_64 is native already

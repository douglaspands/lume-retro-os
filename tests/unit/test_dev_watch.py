"""`r36os dev watch`: change grouping with a fake clock, build and push."""

import pytest

from r36os import dev_watch
from r36os.dev_watch import Watcher


class Rig:
    def __init__(self, build_fail=False, push_fail=False):
        self.now = 0.0
        self.files = {"a": 1, "b": 1}
        self.lines = []
        self.builds = 0
        self.on_build = None
        self.build_fail, self.push_fail = build_fail, push_fail
        self.w = Watcher("lume-core", lambda: dict(self.files), self.build, self.push,
                         emit=self.lines.append, clock=lambda: self.now)

    def build(self, name):
        self.builds += 1
        if self.on_build:
            self.on_build()
        self.now += 52
        if self.build_fail:
            raise RuntimeError("compile\nerror")

    def push(self, name):
        if self.push_fail:
            raise RuntimeError("no console")
        return "restart frontend"

    def tick(self, dt=0.5):
        self.now += dt
        return self.w.poll()


def test_saves_within_a_second_make_one_cycle():
    r = Rig()
    r.files["a"] = 2
    r.tick()
    r.files["b"] = 2
    r.tick()
    r.files["a"] = 3
    assert not r.tick()
    assert not r.tick()          # 0.5 s after the last change
    assert r.tick()              # 1 s
    assert r.builds == 1
    assert r.lines == ["watch lume-core: changed 2 files, build 52s, hot push ok "
                       "(restart frontend)"]
    assert not r.tick(5)         # nothing more to do


def test_change_during_a_cycle_makes_another_cycle():
    r = Rig()
    r.files["a"] = 2
    r.tick()
    r.on_build = lambda: r.files.__setitem__("b", 9)
    r.tick(); assert r.tick()
    r.on_build = None
    assert r.builds == 1 and r.w.pending == {"b"}
    assert not r.tick(0.5)
    assert r.tick(0.5)
    assert r.builds == 2
    assert "changed 1 file," in r.lines[1]


def test_build_failure_is_one_line_and_skips_the_push():
    r = Rig(build_fail=True)
    r.files["a"] = 2
    r.tick(); r.tick(1)
    assert r.lines == ["watch lume-core: changed 1 file, build failed: compile error"]
    assert r.tick(1) is False    # keeps watching


def test_push_failure_is_reported():
    r = Rig(push_fail=True)
    r.files["a"] = 2
    r.tick(); r.tick(1)
    assert r.lines[0].endswith("build 52s, hot push failed: no console")


def test_deleted_and_new_files_count(tmp_path):
    assert dev_watch.changed_paths({"a": (1, 1)}, {"b": (1, 1)}) == {"a", "b"}


def test_snapshot_watches_aport_and_lume_sources(tmp_path):
    (tmp_path / "aports/lume-launcher/stage").mkdir(parents=True)
    (tmp_path / "aports/lume-launcher/APKBUILD").write_text("x")
    (tmp_path / "lume/lume-ui/src").mkdir(parents=True)
    (tmp_path / "lume/lume-ui/src/a.rs").write_text("x")
    (tmp_path / "lume/target").mkdir()
    (tmp_path / "lume/target/junk").write_text("x")
    snap = dev_watch.snapshot("lume-launcher", tmp_path)
    names = sorted(p.removeprefix(str(tmp_path)) for p in snap)
    assert names == ["/aports/lume-launcher/APKBUILD", "/lume/lume-ui/src/a.rs"]


def test_refused_fragment_does_not_start(monkeypatch):
    from r36os.push import PushError

    with pytest.raises(PushError):
        dev_watch.cmd_watch("linux-r36s", None)

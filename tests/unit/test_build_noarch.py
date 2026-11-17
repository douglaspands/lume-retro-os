"""build-speed 4.2 and 6.1: `r36os build` hands the noarch fragments to build_noarch (once,
in the x86_64 builder), which decides by inputs and content; the changed ones are published
as the same .apk for every arch, before the arch packages and rootfs. Fakes only: no podman."""

import pytest

from r36os import build, packages
from r36os.stages import StageTimer
from r36os.targets import get_image, get_target


class _Log(list):
    """The calls, plus `changed`: which fragments build_noarch reports as changed."""


@pytest.fixture
def calls(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    log = _Log()
    changed = {"names": None}  # None: every fragment changed

    def fake_build(names, aports=None, force=False):
        log.append(("build_noarch", list(names), force))
        out = names if changed["names"] is None else changed["names"]
        return [tmp_path / f"{n}-1.0-r0.apk" for n in out]

    def fake_publish(apks, arches=packages.REPO_ARCHES):
        log.append(("publish_noarch", [a.name for a in apks]))
        return []

    monkeypatch.setattr(build, "build_noarch", fake_build)
    monkeypatch.setattr(build, "publish_noarch", fake_publish)
    log.changed = changed
    return log


def test_lume_core_is_a_noarch_fragment():
    assert "lume-core" in build.noarch_fragments()
    assert "retroarch" not in build.noarch_fragments()


def test_a_changed_fragment_is_built_once_and_published(calls):
    build.build_noarch_fragments()
    every = build.noarch_fragments()
    assert "lume-core" in every and "lume-usb" in every
    assert calls[0] == ("build_noarch", every, False)
    assert calls[1] == ("publish_noarch", [f"{n}-1.0-r0.apk" for n in every])


def test_an_unchanged_fragment_is_not_published(calls):
    calls.changed["names"] = []          # build_noarch found the same inputs or content
    build.build_noarch_fragments()
    assert calls == [("build_noarch", build.noarch_fragments(), False)]


def test_rebuild_packages_forces_the_build(calls):
    build.build_noarch_fragments(rebuild_packages=True)
    assert calls[0] == ("build_noarch", build.noarch_fragments(), True)


def test_the_noarch_stage_comes_before_every_layer(calls, monkeypatch):
    order = calls
    monkeypatch.setattr(build.version, "current", lambda: build.version.BuildVersion(
        "20260101-000000", "2026-01-01T00:00:00", "abc", False))
    monkeypatch.setattr(build, "_build_layers",
                        lambda img, v, lang, rebuild, timer, timers: order.append(("layers",))
                        or {})

    class StopHere(Exception):
        pass

    def stop(v, language="en"):
        raise StopHere

    monkeypatch.setattr(build.image, "build_console_image", stop)  # layers are done
    with pytest.raises(StopHere):
        build._build_image_target(get_image("console"), False, "en",
                                  StageTimer(out=lambda s: None))
    assert [c[0] for c in order] == ["build_noarch", "publish_noarch", "layers"]


def test_layers_never_build_a_noarch_fragment_per_arch(calls, monkeypatch):
    built = []
    monkeypatch.setattr(build, "ensure_key", lambda t: None)
    monkeypatch.setattr(build, "build_packages",
                        lambda t, names, force=False: built.append((list(names), force)))
    monkeypatch.setattr(build.stage_inputs, "run_stage", lambda *a, **k: None)
    monkeypatch.setattr(build, "_initramfs_stage", lambda *a, **k: None)
    monkeypatch.setattr(build.rootfs, "system_limit_mib", lambda t: 1)
    build.build_layer(get_target("vm"), None, "en", rebuild_packages=True,
                      timer=StageTimer(out=lambda s: None))
    names, force = built[0]
    assert "lume-core" not in names and "retroarch" in names and force is True

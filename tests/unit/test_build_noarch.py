"""build-speed 4.2: `r36os build` makes the missing noarch fragments (once, in the x86_64
builder) and publishes the same .apk for every arch, before the arch packages and rootfs.
Fakes only: no podman."""

import pytest

from r36os import build, packages
from r36os.stages import StageTimer
from r36os.targets import get_image, get_target


@pytest.fixture
def calls(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    log = []

    def fake_build(names, aports=None):
        log.append(("build_noarch", list(names)))
        return [tmp_path / f"{n}-1.0-r0.apk" for n in names]

    def fake_publish(apks, arches=packages.REPO_ARCHES):
        log.append(("publish_noarch", [a.name for a in apks]))
        return []

    monkeypatch.setattr(build, "build_noarch", fake_build)
    monkeypatch.setattr(build, "publish_noarch", fake_publish)
    return log


def _publish(tmp_path, name, arches=packages.REPO_ARCHES):
    for a in arches:
        d = tmp_path / "out/repo" / a
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}-1.0-r0.apk").write_bytes(b"x")


def test_lume_core_is_a_noarch_fragment():
    assert "lume-core" in build.noarch_fragments()
    assert "retroarch" not in build.noarch_fragments()


def test_a_missing_fragment_is_built_once_and_published(calls):
    build.build_noarch_fragments()
    assert calls == [("build_noarch", ["lume-core"]),
                     ("publish_noarch", ["lume-core-1.0-r0.apk"])]


def test_a_fragment_in_every_arch_repository_is_not_rebuilt(calls, tmp_path):
    _publish(tmp_path, "lume-core")
    timer = StageTimer(out=lambda s: None)
    build.build_noarch_fragments(timer=timer)
    assert calls == []
    assert ("noarch fragments", None, "all in the repository") in timer._rows


def test_a_fragment_missing_in_one_arch_is_built(calls, tmp_path):
    _publish(tmp_path, "lume-core", arches=("armv7", "x86_64"))
    build.build_noarch_fragments()
    assert [c[0] for c in calls] == ["build_noarch", "publish_noarch"]


def test_rebuild_packages_rebuilds_and_replaces_the_published_files(calls, tmp_path,
                                                                    monkeypatch):
    _publish(tmp_path, "lume-core")
    seen = []
    monkeypatch.setattr(build, "publish_noarch", lambda apks: seen.append(
        [p.exists() for a in packages.REPO_ARCHES
         for p in (tmp_path / "out/repo" / a).glob("lume-core-*.apk")]))
    build.build_noarch_fragments(rebuild_packages=True)
    assert calls == [("build_noarch", ["lume-core"])]
    assert seen == [[]]  # the old files were gone before publishing


def test_the_noarch_stage_comes_before_every_layer(calls, monkeypatch):
    order = calls
    monkeypatch.setattr(build.version, "current", lambda: build.version.BuildVersion(
        "20260101-000000", "2026-01-01T00:00:00", "abc", False))
    monkeypatch.setattr(build, "build_layer",
                        lambda target, *a, **k: order.append(("layer", target.name)))
    monkeypatch.setattr(build, "_layer_info", lambda t: {})

    class StopHere(Exception):
        pass

    def stop(v, language="en"):
        raise StopHere

    monkeypatch.setattr(build.image, "build_console_image", stop)  # layers are done
    with pytest.raises(StopHere):
        build._build_image_target(get_image("console"), False, "en", StageTimer(out=lambda s: None))
    assert [c[0] for c in order[:2]] == ["build_noarch", "publish_noarch"]
    assert order[2:] == [("layer", "ga36"), ("layer", "r36s")]


def test_layers_never_build_a_noarch_fragment_per_arch(calls, monkeypatch):
    built = []
    monkeypatch.setattr(build, "ensure_key", lambda t: None)
    monkeypatch.setattr(build, "build_packages", lambda t, names: built.append(list(names)))
    monkeypatch.setattr(build.stage_inputs, "run_stage", lambda *a, **k: None)
    monkeypatch.setattr(build, "_initramfs_stage", lambda *a, **k: None)
    monkeypatch.setattr(build.rootfs, "system_limit_mib", lambda t: 1)
    build.build_layer(get_target("vm"), None, "en", rebuild_packages=True,
                      timer=StageTimer(out=lambda s: None))
    assert built and "lume-core" not in built[0] and "retroarch" in built[0]

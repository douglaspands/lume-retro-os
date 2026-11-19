"""Experiment kernels (device-fixes 6.3, D12, D13): the variants of kernel/variants/, their
panel modes and clocks, and the build that archives them without touching the default
image (lume_tool.kernel_variants)."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from lume_tool import bootimg, image, kernel, kernel_variants, manifests
from lume_tool.paths import REPO_ROOT, cache_dir

GA36 = kernel_variants.available("ga36")
PANEL_FILE = "drivers/gpu/drm/panel/panel-ga36mb-jd9366.c"
PATCH_0005 = REPO_ROOT / "kernel/patches/0005-drm-panel-add-GA36-MB-JD9366-panels.patch"
MODE_FIELDS = ("clock", "hdisplay", "hsync_start", "hsync_end", "htotal",
               "vdisplay", "vsync_start", "vsync_end", "vtotal")
PLL_VIDEO_KHZ = 297_000      # locked by the DSI block (clk_set_rate_exclusive of its mod clock)
EXPERIMENTS = {"e1", "e4-slow", "e4-nonburst", "e4-eotp", "60hz", "60hz-porch"}


def _mode(lines: list[str]) -> dict[str, int]:
    """Fields of jd9366_mode from `.field = expr,` lines (numbers and + only)."""
    out = {}
    for line in lines:
        m = re.match(r"^[+ ]?\s*\.(\w+) = ([0-9 +]+),$", line)
        if m and m.group(1) in MODE_FIELDS:
            out[m.group(1)] = eval(m.group(2), {"__builtins__": {}})  # noqa: S307
    return out


def default_mode() -> dict[str, int]:
    block = PATCH_0005.read_text().split("jd9366_mode = {", 1)[1].split("};", 1)[0]
    return _mode(block.splitlines())


def variant_mode(name: str) -> dict[str, int] | None:
    """The panel mode of a variant, or None when its patches leave the mode alone."""
    added = [line for p in kernel_variants.load("ga36", name).patches
             for line in p.read_text().splitlines() if line.startswith("+")]
    changes = _mode(added)
    return {**default_mode(), **changes} if changes else None


def hz(mode: dict[str, int]) -> float:
    return mode["clock"] * 1000 / (mode["htotal"] * mode["vtotal"])


def pll_mipi_rates_khz() -> set[Fraction]:
    """Every rate of pll-mipi = pll-video x N x K / M (N 1-16, K 1-4, M 1-16; A33 manual,
    PLL_MIPI_CTRL_REG; ccu-sun8i-a33.c)."""
    return {Fraction(PLL_VIDEO_KHZ * n * k, m)
            for n in range(1, 17) for k in range(1, 5) for m in range(1, 17)}


def test_the_experiments_of_the_task_exist():
    assert set(GA36) == EXPERIMENTS


@pytest.mark.parametrize("name", GA36)
def test_variant_loads_and_patches_only_drivers_built_into_the_image(name):
    v = kernel_variants.load("ga36", name)
    assert v.description
    config = (REPO_ROOT / "board/ga36/kernel.config").read_text()
    for p in v.patches:
        for path in kernel_variants.touched_files(p):
            # a module would need the modules image, which a variant never sends
            assert f"{kernel_variants.BUILTIN_FILES[path]}=y" in config.splitlines(), path
        # the running variant says so in the boot log
        assert re.search(r'^\+.*dev_info\(.*"experiment kernel ' + re.escape(name) + ":",
                         p.read_text(), re.M), p.name


def test_variants_stay_out_of_the_default_series():
    assert not any("experiment" in p.read_text().split("\n---", 1)[0].lower()
                   for p in kernel.patches())
    assert kernel.series() == kernel.patches()


@pytest.mark.parametrize("name", GA36)
def test_variant_rate_matches_its_panel_mode(name):
    # test_ga36_refresh_rate_matches_panel_mode per variant: the default rate stays in
    # retroarch-ga36.cfg, a variant that changes the mode declares its own
    v = kernel_variants.load("ga36", name)
    mode = variant_mode(name)
    if mode is None:
        assert v.video_refresh_rate is None
        return
    assert v.video_refresh_rate is not None, "the mode changes: declare video_refresh_rate"
    assert abs(float(v.video_refresh_rate) - hz(mode)) < 1e-5
    assert f'{hz(mode):.6f}' == v.video_refresh_rate


def test_default_mode_runs_at_29_7_mhz_not_30():
    # Finding of 6.3 (to measure on the device): the 30 MHz of the mode needs pll-mipi at
    # 360 MHz, which 297 MHz x N x K / M cannot give; the clock framework takes the closest
    # rate below, 356.4 MHz (measured, docs/referencia/a33-clocks.md): 29.7 MHz, 55.13 Hz.
    mode = default_mode()
    wanted = Fraction(mode["clock"] * 12)
    best = max(r for r in pll_mipi_rates_khz() if r <= wanted)
    assert wanted not in pll_mipi_rates_khz() and best == Fraction(356_400)
    assert round(float(best / 12) * 1000 / (mode["htotal"] * mode["vtotal"]), 2) == 55.13


@pytest.mark.parametrize("name", [n for n in GA36 if variant_mode(n) is not None])
def test_variant_mode_is_an_exact_clock_inside_conservative_limits(name):
    mode = variant_mode(name)
    base = default_mode()
    # 24 bits over 2 lanes: pll-mipi = 12 x pixel clock, and it must be exact so that the
    # declared rate is the real one
    assert Fraction(mode["clock"] * 12) in pll_mipi_rates_khz()
    assert 25_000 <= mode["clock"] <= 33_000
    assert 50 <= hz(mode) <= 61
    # only the clock and the horizontal front porch move; sync, back porch and the vertical
    # timing are the vendor's
    assert mode["hdisplay"] == 640 and mode["hsync_end"] - mode["hsync_start"] == 40
    assert mode["htotal"] - mode["hsync_end"] == base["htotal"] - base["hsync_end"]
    assert mode["hsync_start"] - mode["hdisplay"] >= 150
    assert {k: mode[k] for k in ("vdisplay", "vsync_start", "vsync_end", "vtotal")} == \
        {k: base[k] for k in ("vdisplay", "vsync_start", "vsync_end", "vtotal")}


def test_sixty_hz_variants():
    assert round(hz(variant_mode("60hz")), 3) == 60.013          # 386.1 MHz pll-mipi
    assert round(hz(variant_mode("60hz-porch")), 3) == 59.975    # the link of today
    assert variant_mode("60hz")["clock"] * 12 == 386_100
    assert variant_mode("60hz-porch")["clock"] * 12 == 356_400
    assert variant_mode("e4-slow")["clock"] * 12 == 330_000


def test_nonburst_and_eotp_variants_change_only_the_link():
    nonburst = kernel_variants.load("ga36", "e4-nonburst").patches[0].read_text()
    assert "+\tdsi->mode_flags = MIPI_DSI_MODE_VIDEO | MIPI_DSI_MODE_VIDEO_SYNC_PULSE |" in nonburst
    assert variant_mode("e4-nonburst") is None
    eotp = kernel_variants.load("ga36", "e4-eotp").patches[0].read_text()
    assert "SUN6I_DSI_BASIC_CTL0_HS_EOTP_EN" in eotp and "MIPI_DSI_MODE_NO_EOT_PACKET" in eotp


def test_e1_sets_dcdc1_to_3v3_inside_the_axp223_range():
    v = kernel_variants.load("ga36", "e1")
    assert v.patches == () and v.dtsi is not None
    code = re.sub(r"/\*.*?\*/", "", v.dtsi.read_text(), flags=re.S)
    node = re.search(r"&reg_dcdc1 \{(.*?)\};", code, re.S).group(1)
    volts = [int(x) for x in re.findall(r"regulator-(?:min|max)-microvolt = <(\d+)>", node)]
    assert volts == [3_300_000, 3_300_000]
    # AXP22x DCDC1: 1.6 to 3.4 V in 100 mV steps (axp20x-regulator.c)
    assert all(1_600_000 <= uv <= 3_400_000 and uv % 100_000 == 0 for uv in volts)
    # nothing else of the board changes
    assert code.count("&") == 1
    # the default DTS leaves DCDC1 at the 3.0 V of the vendor U-Boot
    dtsi = (REPO_ROOT / "board/ga36/dts/sun8i-a33-ga36-mb-v1.2.dtsi").read_text()
    default = re.search(r"^&reg_dcdc1 \{(.*?)^\};", dtsi, re.S | re.M).group(1)
    assert "microvolt" not in default


def test_stage_dts_includes_the_overrides_at_the_end_of_every_dts(tmp_path):
    src = REPO_ROOT / "board/ga36/dts"
    before = {p.name: p.read_text() for p in src.iterdir()}
    dtsi = kernel_variants.load("ga36", "e1").dtsi
    staged = kernel_variants.stage_dts(src, dtsi, tmp_path / "dts")
    assert {p.name: p.read_text() for p in src.iterdir()} == before          # untouched
    assert (staged / kernel_variants.STAGED_DTSI).read_text() == dtsi.read_text()
    for name, text in before.items():
        out = (staged / name).read_text()
        if name.endswith(".dts"):
            assert out.startswith(text)
            assert out.rstrip().endswith(f'#include "{kernel_variants.STAGED_DTSI}"')
        else:
            assert out == text


def _patch(path: str, old: str, new: str, comment: str = "") -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-{old}\n+{new}\n{comment}"


def test_load_refuses_what_is_not_an_experiment(tmp_path):
    root = tmp_path / "variants"
    (root / "ga36/ok").mkdir(parents=True)
    (root / "ga36/ok/variant.toml").write_text('description = "x"\n')
    (root / "ga36/ok/0001-a.patch").write_text(_patch(PANEL_FILE, "a", "b"))
    assert kernel_variants.load("ga36", "ok", root).patches[0].name == "0001-a.patch"
    with pytest.raises(kernel_variants.VariantError, match="known: ok"):
        kernel_variants.load("ga36", "nope", root)
    with pytest.raises(kernel_variants.VariantError, match="bad variant name"):
        kernel_variants.load("ga36", "../ok", root)
    # a module or any other file of the kernel
    (root / "ga36/ok/0002-b.patch").write_text(_patch("drivers/other.c", "a", "b"))
    with pytest.raises(kernel_variants.VariantError, match="drivers/other.c"):
        kernel_variants.load("ga36", "ok", root)
    (root / "ga36/ok/0002-b.patch").unlink()
    (root / "ga36/ok/variant.toml").write_text('description = "x"\nvideo_refresh_rate = 60\n')
    with pytest.raises(kernel_variants.VariantError, match="video_refresh_rate"):
        kernel_variants.load("ga36", "ok", root)
    (root / "ga36/empty").mkdir()
    (root / "ga36/empty/variant.toml").write_text('description = "x"\n')
    with pytest.raises(kernel_variants.VariantError, match="nothing to try"):
        kernel_variants.load("ga36", "empty", root)


def test_replace_boot_files_changes_only_files_the_base_has():
    sha = lambda c: hashlib.sha256(c.encode()).hexdigest()  # noqa: E731
    base = [("ga36/zImage", sha("k")), ("r36s/Image", sha("r")), ("VERSION", sha("v"))]
    out = kernel_variants.replace_boot_files(base, {"ga36/zImage": sha("k2"),
                                                    "VERSION": sha("v2")})
    assert out == {"ga36/zImage": sha("k2"), "r36s/Image": sha("r"), "VERSION": sha("v2")}
    with pytest.raises(kernel_variants.VariantError, match="ga36/new"):
        kernel_variants.replace_boot_files(base, {"ga36/new": sha("x"), "VERSION": sha("v")})
    with pytest.raises(kernel_variants.VariantError, match="VERSION"):
        kernel_variants.replace_boot_files(base, {"ga36/zImage": sha("k2")})


# --- the variant patches against the real series ------------------------------------------

LINUX_GIT = cache_dir() / "src" / f"linux-{kernel.KERNEL_VERSION}.git"


def _git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)


@pytest.mark.skipif(not LINUX_GIT.is_dir() or shutil.which("git") is None,
                    reason="no kernel source in the cache (lume build kernel makes it)")
@pytest.mark.parametrize("name", [n for n in GA36 if kernel_variants.load("ga36", n).patches])
def test_variant_patches_apply_on_top_of_the_series(name, tmp_path):
    # The files the variants may touch, from the pristine upstream (read-only), then every
    # series patch limited to them, then the variant: what _series_commit does in the build
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_DIR=str(LINUX_GIT), GIT_WORK_TREE=str(tmp_path / "unused"),
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    work = tmp_path / "linux"
    work.mkdir()
    clean = {k: v for k, v in env.items() if not k.startswith("GIT_DIR")
             and not k.startswith("GIT_WORK_TREE")}
    clean["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    assert _git(work, "init", "-q", env=clean).returncode == 0
    for path in kernel_variants.BUILTIN_FILES:
        r = _git(tmp_path, "cat-file", "blob", f"{kernel.UPSTREAM_TAG}:{path}", env=env)
        if r.returncode == 0:
            (work / path).parent.mkdir(parents=True, exist_ok=True)
            (work / path).write_text(r.stdout)
    include = [f"--include={p}" for p in kernel_variants.BUILTIN_FILES]
    for p in kernel.patches():
        if kernel_variants.touched_files(p) & set(kernel_variants.BUILTIN_FILES):
            r = _git(work, "apply", *include, str(p), env=clean)
            assert r.returncode == 0, f"{p.name}: {r.stderr}"
    for p in kernel_variants.load("ga36", name).patches:
        r = _git(work, "apply", "--check", str(p), env=clean)
        assert r.returncode == 0, f"{p.name}: {r.stderr}"


# --- the build: archived beside the default, latest untouched ------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def base_build(tmp_path, monkeypatch):
    """out/ with a console build (latest) whose GA36 kernel is the one in kernel-pkg/."""
    out = tmp_path / "out"
    monkeypatch.setenv("LUME_OUT", str(out))
    pkg = out / "ga36/kernel-pkg/boot"
    (pkg / "dtbs/a33").mkdir(parents=True)
    (pkg / "zImage").write_bytes(b"default kernel")
    for panel in ("panel1", "panel2"):
        (pkg / f"dtbs/a33/sun8i-a33-ga36-mb-v1.2-{panel}.dtb").write_bytes(f"dtb {panel}".encode())
    base = out / "images/console/20261118-100000"
    base.mkdir(parents=True)
    files = {"ga36/zImage": pkg / "zImage",
             "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel1.dtb":
                 pkg / "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel1.dtb",
             "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel2.dtb":
                 pkg / "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel2.dtb"}
    shas = {p: _sha(src) for p, src in files.items()}
    shas["r36s/Image"] = hashlib.sha256(b"r36s").hexdigest()
    shas["VERSION"] = hashlib.sha256(b"base version").hexdigest()
    manifests.write_boot_list(base / image.BOOT_LIST, shas)
    parts = {image.AREA_PART: hashlib.sha256(b"area").hexdigest(),
             image.PANEL1_PART: hashlib.sha256(b"panel1 default").hexdigest()}
    (base / image.IMAGE_PARTS).write_text(image.format_image_parts(parts))
    (base / "build.json").write_text(json.dumps({"kind": "fragments", "language": "pt",
                                                 "alpine": "3.22", "layers": {}}))
    (base / "manifest-ga36.txt").write_text("pkg 1\n")
    (out / "images/console/latest").symlink_to(base.name)
    return out, base, shas, parts


@pytest.fixture
def fake_builders(monkeypatch, tmp_path):
    calls = []

    def build_kernel(board, out, initramfs_dir=None):
        calls.append(("kernel", board, [p.name for p in kernel.series()], initramfs_dir))
        out.mkdir(parents=True, exist_ok=True)
        (out / "zImage").write_bytes(b"variant kernel")
        return out / "zImage"

    def build_dtbs(board, arch, vendor, out, dts_dir=None):
        calls.append(("dtbs", board, dts_dir))
        out.mkdir(parents=True, exist_ok=True)
        for dts in sorted(dts_dir.glob("*.dts")):
            assert kernel_variants.STAGED_DTSI in dts.read_text()
            (out / f"{dts.stem}.dtb").write_bytes(b"variant " + dts.stem.encode())

    monkeypatch.setattr(kernel, "build_kernel", build_kernel)
    monkeypatch.setattr(kernel, "build_dtbs", build_dtbs)
    monkeypatch.setattr(kernel, "patches", lambda: [Path("0001-default.patch")])
    return calls


def test_variant_build_is_archived_without_moving_latest(base_build, fake_builders):
    out, base, shas, parts = base_build
    dest = kernel_variants.build_variant("ga36", "e4-nonburst")
    assert os.readlink(out / "images/console/latest") == base.name     # untouched
    assert dest.parent == base.parent and dest != base
    # the extra patches were applied in the build and are gone afterwards
    (_, board, series, initramfs), = fake_builders
    assert board == "ga36" and series[0] == "0001-default.patch" and len(series) == 2
    assert initramfs == out / "ga36" and kernel.series() == [Path("0001-default.patch")]
    info = json.loads((dest / "build.json").read_text())
    assert info["kind"] == "kernel-variant" and info["base"] == base.name
    assert info["variant"]["name"] == "e4-nonburst" and info["language"] == "pt"
    new = dict(image.read_boot_list(dest / image.BOOT_LIST))
    changed = {p for p in new if new[p] != shas[p]}
    assert changed == {"ga36/zImage", "VERSION"}                        # DTBs, R36S: same
    assert new["ga36/zImage"] == hashlib.sha256(b"variant kernel").hexdigest()
    objects = out / "images/objects"
    version = (objects / new["VERSION"]).read_text()
    assert "kernel variant: ga36 e4-nonburst (base 20261118-100000)" in version
    assert "language: pt" in version
    new_parts = image.read_image_parts(dest / image.IMAGE_PARTS)
    assert new_parts[image.AREA_PART] == parts[image.AREA_PART]
    panel1 = dest / "ga36-android-boot-panel1.img"
    assert new_parts[image.PANEL1_PART] == _sha(panel1)
    assert panel1.read_bytes() == bootimg.make(b"variant kernel" + b"dtb panel1")
    assert (dest / "ga36-android-boot-panel2.img").read_bytes() == \
        bootimg.make(b"variant kernel" + b"dtb panel2")
    assert (dest / "manifest-ga36.txt").read_text() == "pkg 1\n"
    # nothing of the default kernel was touched
    assert (out / "ga36/kernel-pkg/boot/zImage").read_bytes() == b"default kernel"


def test_dts_only_variant_keeps_the_default_kernel(base_build, fake_builders):
    out, base, shas, _ = base_build
    dest = kernel_variants.build_variant("ga36", "e1")
    assert [c[0] for c in fake_builders] == ["dtbs"]
    new = dict(image.read_boot_list(dest / image.BOOT_LIST))
    assert {p for p in new if new[p] != shas[p]} == {
        "VERSION", "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel1.dtb",
        "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel2.dtb"}
    assert (dest / "ga36-android-boot-panel1.img").read_bytes() == bootimg.make(
        b"default kernel" + b"variant sun8i-a33-ga36-mb-v1.2-panel1")


def test_variant_refuses_a_base_whose_kernel_is_not_the_built_one(base_build, fake_builders):
    out, _, _, _ = base_build
    (out / "ga36/kernel-pkg/boot/zImage").write_bytes(b"something else")
    with pytest.raises(kernel_variants.VariantError, match="lume build --console ga36 kernel"):
        kernel_variants.build_variant("ga36", "e4-slow")
    assert fake_builders == []


def test_variant_is_not_a_base(base_build, fake_builders):
    out, _, _, _ = base_build
    dest = kernel_variants.build_variant("ga36", "e4-slow")
    latest = out / "images/console/latest"
    latest.unlink()
    latest.symlink_to(dest.name)
    with pytest.raises(kernel_variants.VariantError, match="is an experiment kernel"):
        kernel_variants.build_variant("ga36", "e4-slow")


def test_cli_variant_only_with_kernel_and_console(capsys):
    from lume_tool import cli

    assert cli.main(["build", "kernel", "--variant", "e4-slow"]) == 2
    assert cli.main(["build", "--console", "ga36", "lume-core", "--variant", "e4-slow"]) == 2
    assert "--variant goes with" in capsys.readouterr().err
    assert cli.main(["build", "--console", "ga36", "kernel", "--variant", "nope"]) == 2
    assert "known: 60hz" in capsys.readouterr().err

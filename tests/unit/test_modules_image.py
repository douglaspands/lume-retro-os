"""kernel-modules-image: the console kernel modules live in BOOT/<console>/modules, not in
SYSTEM (D1-D3)."""

from r36os import build, rootfs
from r36os.paths import REPO_ROOT
from r36os.targets import get_target


def test_modules_image_command(tmp_path, monkeypatch):
    # task 1.1: mksquashfs -tar from the modules.tar with lib/modules/ taken off, owned by
    # root, with no build times, in the x86_64 builder
    seen = {}

    class FakeContainer:
        def __init__(self, image, volumes):
            seen["image"], seen["volumes"] = image, volumes

        def sh(self, script):
            seen["script"] = script

    monkeypatch.setattr(rootfs, "Container", FakeContainer)
    monkeypatch.setattr(rootfs, "ensure_builder", lambda t: f"builder:{t.alpine_arch}")
    src = tmp_path / "kernel" / "modules.tar"
    dest = rootfs.make_modules_image(src, tmp_path / "kernel" / "modules")
    assert dest == tmp_path / "kernel" / "modules"
    assert seen["image"] == "builder:x86_64"
    # the build case: modules.tar and the image in the same folder, one volume (two keys
    # with the same path would leave /in unmounted)
    assert seen["volumes"] == {dest.parent: "/out"}
    lines = [line.strip() for line in seen["script"].splitlines()]
    assert "tar -C /tmp/m -xf /out/modules.tar" in lines
    other = tmp_path / "elsewhere" / "modules"
    rootfs.make_modules_image(src, other)
    assert seen["volumes"] == {other.parent: "/out", src.parent: "/in"}
    assert "tar -C /tmp/m -xf /in/modules.tar" in seen["script"]
    repack = next(line for line in lines if line.startswith("tar -C /tmp/m/lib/modules "))
    for flag in ("--numeric-owner", "--owner=0", "--group=0", "--sort=name"):
        assert flag in repack.split(), flag
    squash = " ".join(seen["script"].split("mksquashfs", 1)[1].split())
    assert squash.startswith("- /out/modules -tar -comp zstd")
    for flag in ("-mkfs-time 0", "-all-time 0", "-noappend"):
        assert flag in squash, flag


def test_build_console_kernel_makes_the_modules_image(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    made = []

    def fake_kernel(board, kdir, initramfs_dir=None):
        (kdir / "dtbs").mkdir(parents=True, exist_ok=True)
        (kdir / "Image").write_bytes(b"k")
        return kdir / "Image"

    monkeypatch.setattr(build.kernel, "build_kernel", fake_kernel)
    monkeypatch.setattr(build.kernel, "build_dtbs", lambda *a: None)
    monkeypatch.setattr(build.uboot, "build_uboot", lambda *a: None)
    monkeypatch.setattr(build.rootfs, "make_modules_image",
                        lambda src, dest: made.append((src, dest)))
    build.build_console_kernel(get_target("r36s"))
    kdir = tmp_path / "r36s" / "kernel"
    assert made == [(kdir / "modules.tar", kdir / "modules")]


def test_logs_doc_has_the_boot_messages_of_the_modules_step():
    # task 2.3: every message of mount_modules is in docs/LOGS.md, with the variables as
    # placeholders
    import re

    src = (REPO_ROOT / "initramfs/lib/storage.sh").read_text()
    body = src.split("mount_modules() {", 1)[1].split("\n}\n", 1)[0]
    messages = re.findall(r'log "([^"]*)"', body)
    assert len(messages) == 5
    doc = (REPO_ROOT / "docs/LOGS.md").read_text()
    for msg in messages:
        want = (msg.replace("${found:-no kernel}", "<found>").replace("$file", "<file>")
                .replace("$running", "<release>"))
        assert f"| `{want}` |" in doc, want


def test_rootfs_has_no_kernel_modules():
    # task 1.2: SYSTEM no longer carries the modules, only the empty mount point
    script = rootfs._ROOTFS_SCRIPT
    assert "modules.tar" not in script
    assert "mkdir -p $R/lib/modules" in script.splitlines()
    # created before the tar of the rootfs
    assert script.index("mkdir -p $R/lib/modules") < script.index("-cf /out/rootfs.tar")

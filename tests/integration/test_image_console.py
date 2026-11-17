"""Console image (r36s-single-card, tasks 5.2 and 5.3): our MBR, the boot area of both
consoles, the GA36 Android boot image and the BOOT with one folder per console.

Requires out/console/console.img (uv run r36os build console).
"""

import hashlib
import shutil
import struct
import subprocess

import pytest

from r36os import bootimg, manifests, r36s_vendor, vendor
from r36os.container import Container, ensure_builder
from r36os.image import boot_start
from r36os.rootfs import target_out
from r36os.targets import get_image, get_target

OUT = target_out(get_image("console"))
GA36 = target_out(get_target("ga36"))
IMG = OUT / "console.img"
START = boot_start("console")
S = 512
pytestmark = [
    pytest.mark.skipif(shutil.which("podman") is None, reason="no podman"),
    pytest.mark.skipif(not IMG.exists(), reason="no out/console/console.img"),
]


def _sh(script: str) -> str:
    cmd = Container(image=ensure_builder(get_target("vm")), volumes={OUT: "/out"}).argv(script)
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def _read(offset: int, length: int) -> bytes:
    with IMG.open("rb") as f:
        f.seek(offset)
        return f.read(length)


def test_mbr_has_the_ga36_signature_and_only_boot():
    mbr = _read(0, S)
    assert mbr[510:512] == b"\x55\xaa"
    assert mbr[440:444] == bytes.fromhex("4c554d32")[::-1]
    dump = _sh("sfdisk -d /out/console.img")
    parts = [line for line in dump.splitlines() if " : start=" in line]
    assert len(parts) == 1 and f"start={START}" in parts[0].replace(" ", "")
    assert START == 262144


def test_shrunk_boot0():
    boot0 = _read(16 * S, 24 * 1024)
    assert boot0[4:12] == b"eGON.BT0"
    assert struct.unpack_from("<I", boot0, 0x10)[0] == 24576
    assert struct.unpack_from("<I", boot0, 0x0C)[0] == vendor.egon_checksum(boot0)


def test_r36s_chain_at_its_sectors():
    regions = r36s_vendor.factory_regions()
    for r in r36s_vendor.REGIONS:
        assert _read(r.start * S, (r.end - r.start) * S) == regions[r.name], r.name
    assert _read(16384 * S, 8) == b"LOADER  " and _read(24576 * S, 4) == b"BL3X"


def test_ga36_vendor_area_kept_elsewhere():
    area = vendor.vendor_area().read_bytes()
    for start, end in ((1, 16), (32768, vendor.ANDROID_BOOT_SECTOR)):  # incl. U-Boot 2017
        assert _read(start * S, (end - start) * S) == area[start * S:end * S], (start, end)


def test_android_boot_is_ga36_panel1():
    expected = (GA36 / "kernel/android-boot-panel1.img").read_bytes()
    got = _read(vendor.ANDROID_BOOT_SECTOR * S, len(expected))
    assert got == expected and bootimg.parse(got)["magic"] == b"ANDROID!"


def test_boot_contents():
    listing = _sh(f"MTOOLS_SKIP_CHECK=1 mdir -i /out/console.img@@{START * S} -b -/ ::/")
    sets = {b: manifests.read_slots(target_out(get_target(b)) / "slots/SLOTS")
            for b in ("ga36", "r36s")}
    slot_files = [f"{b}/{f}" for b, ss in sets.items() for f in ss.files()]
    for name in ("VERSION", "boot.ini", "ga36/SLOTS", "ga36/zImage", *slot_files,
                 "r36s/SLOTS", "r36s/Image",
                 "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel1.dtb",
                 "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel2.dtb",
                 "dtbs/rk3326/rk3326-r36s-v5.dtb",
                 # D17: the converted trees, named after their lume,id (docs table, 2.3)
                 "dtbs/rk3326/vendor/darkosre-r36s.dtb"):
        assert f"::/{name}" in listing, listing
    assert "::/logs" not in listing and "::/SYSTEM" not in listing.split()
    # build-speed D9: a new card has the slot sets only, no SYSTEM nor modules image
    for b in ("ga36", "r36s"):
        assert f"::/{b}/SYSTEM" not in listing.split()
        assert f"::/{b}/modules" not in listing.split()
    # boot-dtb-select D8: the DTBs only live in dtbs/<soc>/, and force is the user's
    assert "::/ga36/dtbs" not in listing and "::/r36s/rk3326" not in listing
    assert "::/dtbs/force" not in listing
    # only what the consoles read: the panel boot images are archived with the build
    assert "android-boot" not in listing


@pytest.mark.parametrize("board", ["ga36", "r36s"])
def test_modules_outside_system(board):
    # kernel-modules-image: the modules slot (build-speed D9) is the built modules image,
    # with one folder named after the kernel release, and the overlay slots have nothing
    # under lib/modules/ (base, runtime, lume: only the mount point)
    out = target_out(get_target(board))
    ss = manifests.read_slots(out / "slots/SLOTS")
    want = hashlib.sha256((out / "kernel/modules").read_bytes()).hexdigest()
    assert ss.get("modules").sha256 == want
    got = _sh(f"MTOOLS_SKIP_CHECK=1 mtype -i /out/console.img@@{START * S} "
              f"::/{board}/{ss.get('modules').file} | sha256sum")
    assert got.split()[0] == want
    builder = Container(image=ensure_builder(get_target("vm")), volumes={out: "/b"})
    listing = builder.sh("unsquashfs -l /b/kernel/modules", capture_output=True,
                         text=True).stdout.split()
    top = {p.split("/")[1] for p in listing if p.startswith("squashfs-root/")}
    assert top == {(out / "kernel/release").read_text().strip()}
    for slot in ss.overlay():
        system = builder.sh(f"unsquashfs -l /b/{slot.file}", capture_output=True,
                            text=True).stdout
        assert "squashfs-root/lib/modules/" not in system, slot.name


def test_ga36_zimage_has_no_appended_dtb():
    # the kernel reloaded by kexec: the plain zImage, the boot image minus the DTB
    zimage = (GA36 / "kernel/zImage").read_bytes()
    listing = _sh(f"MTOOLS_SKIP_CHECK=1 mtype -i /out/console.img@@{START * S} ::/ga36/zImage "
                  "| sha256sum")
    assert listing.split()[0] == hashlib.sha256(zimage).hexdigest()


def test_boot_root_has_the_factory_files():
    # task 4.5: the RG351 DTB the R36S U-Boot loads first, and the boot logo it draws
    listing = _sh(f"MTOOLS_SKIP_CHECK=1 mdir -i /out/console.img@@{START * S} -b ::/")
    for name in r36s_vendor.BOOT_FILES:
        assert f"::/{name}" in listing, listing

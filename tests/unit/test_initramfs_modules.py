import pytest

from r36os.initramfs import module_name, resolve_modules

DEP = """\
kernel/fs/exfat/exfat.ko.zst:
kernel/fs/fat/vfat.ko.zst: kernel/fs/fat/fat.ko.zst
kernel/fs/fat/fat.ko.zst:
kernel/drivers/block/virtio_blk.ko.zst: kernel/drivers/virtio/virtio_ring.ko.zst
kernel/drivers/virtio/virtio_pci.ko.zst: kernel/drivers/virtio/virtio_pci_modern_dev.ko.zst kernel/drivers/virtio/virtio_ring.ko.zst
kernel/drivers/virtio/virtio_ring.ko.zst:
kernel/drivers/virtio/virtio_pci_modern_dev.ko.zst:
"""


def test_deps_first_and_no_duplicates():
    order = resolve_modules(DEP, "kernel/fs/squashfs/squashfs.ko\n",
                            ["virtio_pci", "virtio_blk", "vfat", "squashfs"])
    names = [module_name(p) for p in order]
    assert names.index("virtio_ring") < names.index("virtio_pci")
    assert names.index("fat") < names.index("vfat")
    assert len(names) == len(set(names))
    assert "squashfs" not in names  # embutido


def test_missing_module_fails():
    with pytest.raises(KeyError):
        resolve_modules(DEP, "", ["nao_existe"])

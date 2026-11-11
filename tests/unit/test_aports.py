from r36os.packages import local_aports
from r36os.targets import get_target


def test_mesa_only_for_vm():
    assert "mesa" in local_aports(get_target("vm"))
    assert "mesa" not in local_aports(get_target("r36s"))
    assert "mesa" not in local_aports(get_target("ga36"))


def test_cores_for_all_targets():
    for t in ("vm", "r36s", "ga36"):
        assert "libretro-pcsx-rearmed" in local_aports(get_target(t))
        assert "retroarch" in local_aports(get_target(t))
        # PSP disabled in this version (pending 12.1): the aport exists but is not built
        assert "libretro-ppsspp" not in local_aports(get_target(t))

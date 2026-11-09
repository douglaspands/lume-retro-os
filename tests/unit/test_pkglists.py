from r36os import pkglists
from r36os.targets import TARGETS


def test_common_list_has_no_hardware_packages():
    common = pkglists.common_packages()
    assert common, "lista comum vazia"
    bad = [p for p in common if pkglists.is_hardware(p)]
    assert bad == [], f"pacotes de hardware na lista comum: {bad}"


def test_hw_lists_do_not_overlap_common():
    common = set(pkglists.common_packages())
    for t in TARGETS.values():
        assert common.isdisjoint(pkglists.hw_packages(t)), t.name


def test_common_list_has_required_items():
    common = set(pkglists.common_packages())
    for p in ("alpine-base", "openrc", "mesa-dri-gallium", "retroarch",
              "exfatprogs", "jq", "seatd", "alsa-utils"):
        assert p in common


def test_no_duplicates():
    common = pkglists.common_packages()
    assert len(common) == len(set(common))


def test_vm_kernel_is_hardware_layer():
    from r36os.targets import get_target

    assert "linux-virt" in pkglists.hw_packages(get_target("vm"))

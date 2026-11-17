"""The VM self-test (guest script) and `r36os test-vm` (host) agree on the checks."""

import re

from r36os.paths import REPO_ROOT
from r36os.selftest import KEY_PREFIX, KEYS, expected_checks

SELFTEST_SH = REPO_ROOT / "aports/lume-diag/files/usr/libexec/r36os/selftest"
# decided by the host from the serial, not by the guest script
HOST_ONLY = {"poweroff-on-quit"}


def _script_checks() -> set[str]:
    return set(re.findall(r"^\s*check ([a-z0-9-]+) ", SELFTEST_SH.read_text(), re.M))


def test_every_expected_check_is_run_by_the_guest():
    expected = {c for c in expected_checks() if not c.startswith("core-loaded-")} - HOST_ONLY
    assert expected - _script_checks() == set()


def test_lume_checks_are_expected():
    lume = {c for c in _script_checks() if c.startswith("lume-")}
    assert lume and lume <= set(expected_checks())


def test_every_key_request_is_served_by_the_host():
    text = SELFTEST_SH.read_text()
    for req in re.findall(r"request (keys-[a-z-]+)", text):
        assert req in KEYS, req
    # `keys x right x` in the script becomes key-x, key-right, key-x
    assert 'request "key-$k"' in text and KEY_PREFIX == "key-"

"""build-speed task 10.1 (design D20, spec boot-runtime): OpenRC starts the services in
parallel, and the ones no game uses start after the frontend. The order is read from the
depend() of each init script of the repo (and the conf.d of the packaged ones), as OpenRC
does; the boot log order itself is proven on the consoles."""

import re

from r36os.paths import REPO_ROOT

ROOTFS = REPO_ROOT / "rootfs"
INITD = ROOTFS / "overlay/etc/init.d"
CONFD = ROOTFS / "overlay/etc/conf.d"
CONFIGURE = (ROOTFS / "configure.sh").read_text()

# depend() of the init scripts that come from Alpine 3.24 packages (not in the repo)
PACKAGED = {
    "dbus": {"need": ["localmount"], "after": ["bootmisc"]},
    "networkmanager": {"need": ["dbus"], "provide": ["net"]},
    "bluetooth": {"need": ["dbus", "localmount", "hostname"],
                  "after": ["coldplug", "udev-postmount"]},
    "seatd": {}, "alsa": {},
}

# What no game uses: started after the frontend
LATE = ("bluetooth", "networkmanager", "r36os-playlists", "lume-index")
# What a game, the cable or the screen before the game uses: started before the frontend
EARLY = ("seatd", "alsa", "r36os-mixer", "r36os-jack", "r36os-persist", "r36os-logd",
         "r36os-usb", "r36os-savesync", "r36os-hostshare", "r36os-input", "r36os-hwsummary")


def default_runlevel():
    names = set()
    for body in re.findall(r'^for s in ([^;]*); do\n\tadd "\$s" default\n', CONFIGURE, re.M):
        names.update(body.replace("\\\n", " ").split())
    names.update(re.findall(r"\badd ([a-z][\w-]*) default\b", CONFIGURE))
    return names


def init_script(name):
    """The init script in the overlay, or in an aport of the repo (aports/<pkg>/<name>.initd)."""
    if (INITD / name).exists():
        return INITD / name
    return next((REPO_ROOT / "aports").glob(f"*/{name}.initd"), None)


def deps_of(name):
    path = init_script(name)
    if path:
        body = re.search(r"^depend\(\) \{\n(.*?)^\}", path.read_text(), re.S | re.M)
        deps = {}
        for line in (body.group(1) if body else "").splitlines():
            kind, *args = line.split()
            deps.setdefault(kind, []).extend(args)
    else:
        deps = {k: list(v) for k, v in PACKAGED[name].items()}
    confd = CONFD / name
    if confd.exists():
        for kind, value in re.findall(r'^rc_(need|use|after|before)="([^"]*)"$',
                                      confd.read_text(), re.M):
            deps.setdefault(kind, []).extend(value.split())
    return deps


def start_graph(names):
    """Edges a -> b: a starts before b (only between services of the runlevel)."""
    provides = {p: n for n in names for p in deps_of(n).get("provide", [])}
    edges = {n: set() for n in names}
    for n in names:
        for kind, args in deps_of(n).items():
            for a in (provides.get(a, a) for a in args):
                if a not in names or a == n:
                    continue
                if kind in ("need", "use", "want", "after"):
                    edges[a].add(n)
                elif kind == "before":
                    edges[n].add(a)
    return edges


def reaches(edges, a, b):
    seen, todo = set(), [a]
    while todo:
        n = todo.pop()
        for m in edges[n]:
            if m == b:
                return True
            if m not in seen:
                seen.add(m)
                todo.append(m)
    return False


NAMES = default_runlevel()
EDGES = start_graph(NAMES)


def test_openrc_runs_the_services_in_parallel():
    assert "sed -i -e 's/^#*rc_parallel=.*/rc_parallel=\"YES\"/' /etc/rc.conf" in CONFIGURE
    assert "grep -qx 'rc_parallel=\"YES\"' /etc/rc.conf || echo 'rc_parallel=\"YES\"' >> /etc/rc.conf" \
        in CONFIGURE


def test_every_service_of_the_default_runlevel_is_known():
    for name in NAMES:
        assert init_script(name) or name in PACKAGED, name
    for name in LATE + EARLY + ("frontend", "dbus", "r36os-ssh-wifi", "r36os-selftest"):
        assert name in NAMES, name


def test_no_dependency_cycle():
    for name in NAMES:
        assert not reaches(EDGES, name, name), name


def test_services_no_game_uses_start_after_the_frontend():
    for name in LATE:
        assert reaches(EDGES, "frontend", name), name
        assert not reaches(EDGES, name, "frontend"), name


def test_what_a_game_or_the_cable_uses_starts_before_the_frontend():
    for name in EARLY:
        assert reaches(EDGES, name, "frontend"), name
        assert not reaches(EDGES, "frontend", name), name


def test_the_frontend_waits_for_none_of_the_late_ones():
    frontend = deps_of("frontend")
    for kind in ("need", "use", "want", "after"):
        assert not set(frontend.get(kind, [])) & set(LATE + ("dbus", "net")), kind


def test_nothing_before_the_frontend_drags_networkmanager_or_bluetooth_in():
    # "need"/"use" start the dependency first whatever its "after" says: none of the services
    # before the frontend may need or use them (or "net", which NetworkManager provides)
    for name in NAMES:
        if reaches(EDGES, name, "frontend"):
            deps = deps_of(name)
            used = set(deps.get("need", []) + deps.get("use", []) + deps.get("want", []))
            assert not used & {"networkmanager", "bluetooth", "net", "dbus"}, name


def test_packaged_services_get_the_order_from_conf_d():
    # the init scripts of networkmanager-openrc and bluez-openrc stay untouched
    for name in ("networkmanager", "bluetooth"):
        assert not init_script(name), name
        assert re.search(r'^rc_after="frontend"$', (CONFD / name).read_text(), re.M), name


def test_hardware_snapshot_is_taken_after_the_frontend():
    logd = (ROOTFS / "overlay/usr/libexec/r36os/logd").read_text()
    run = re.search(r"^cmd_run\(\) \{(.*?)^\}", logd, re.S | re.M).group(1)
    assert run.index("wait_frontend") < run.index("hw_snapshot")
    assert "/usr/libexec/r36os/hwinfo" in re.search(r"^hw_snapshot\(\) \{(.*?)^\}", logd,
                                                    re.S | re.M).group(1)

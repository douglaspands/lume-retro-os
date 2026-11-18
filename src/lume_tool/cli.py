"""Command line: `lume build|flash|push|eject|vm|pkg|test-vm|clean`."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from lume_tool import lang
from lume_tool.targets import IMAGES, TARGETS, InvalidTargetError, get_image, get_target


def _port(text: str) -> int:
    port = int(text)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port {port}: use 1024-65535")
    return port


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lume",
        description="Builds the console image (one card for the GA36 and the R36S) and the "
                    "test VM image, and runs the test VM.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    b = sub.add_parser("build", help="build the image of one target (or all with --all), "
                                     "or only some fragments for `lume push`")
    b.add_argument("target", nargs="*",
                   help=f"image: {', '.join(IMAGES)}; or fragments (aports/ names): a "
                        "fragment build compiles them and the aports that build-depend on "
                        "them, redoes only the slots that hold them and archives a build "
                        "without an image, ready for `lume push`; `kernel` redoes only the "
                        "kernel, its modules and DTBs (with --console, of that console)")
    b.add_argument("--console", choices=("ga36", "r36s"),
                   help="fragment build: only this console (default: every console the "
                        "fragments are built for)")
    b.add_argument("--all", action="store_true",
                   help="build the vm, test it, then the console image")
    b.add_argument("--lang", default=None, metavar="CODE",
                   help=f"factory menu language ({', '.join(lang.LANGUAGES)}; default en, "
                        "or for a fragment build the one of the latest console build)")
    b.add_argument("--clean", action="store_true",
                   help="run every stage, even those whose inputs did not change")
    b.add_argument("--variant", metavar="NAME",
                   help="with `kernel --console ga36`: an experiment kernel of "
                        "kernel/variants/<console>/NAME, archived as a build that `latest` "
                        "does not point to (send it with `lume push --build <id>`, undo it "
                        "with `lume push`)")

    f = sub.add_parser("flash", help="write a built image to the card (run it in a terminal)")
    f.add_argument("target", help=f"image: {', '.join(IMAGES)}")
    f.add_argument("device", help="whole card, e.g. /dev/sdc")
    mode = f.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true",
                      help="write the whole card (the default): image, then ROMS on all the "
                           "space left after BOOT, with the default folders and config")
    mode.add_argument("--update", action="store_true",
                      help="write only the boot area and BOOT, keeping ROMS (games and saves)")
    f.add_argument("--build", default="latest", metavar="TIMESTAMP",
                   help="build from out/images/<image>/ (default: latest)")
    f.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    f.add_argument("--eject", action="store_true",
                   help="safely unmount and power off / eject the device after writing")

    u = sub.add_parser("push", help="update the console over the USB cable (OTG port), "
                                    "without taking the card out")
    u.add_argument("--build", default="latest", metavar="TIMESTAMP",
                   help="console build from out/images/console/ (default: latest)")
    u.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    u.add_argument("--no-wait", action="store_true",
                   help="reboot and return, without waiting for the console to come back "
                        "and checking the new boot")
    u.add_argument("--hot", metavar="FRAGMENT",
                   help="extract one lume-* fragment into the console's RAM layer "
                        "and restart its services, without a reboot (gone after a reboot; "
                        "not for kernel, modules or base)")
    u.add_argument("--console", choices=("ga36", "r36s"),
                   help="refuse, before sending anything, when the console on the cable is "
                        "the other one")
    u.add_argument("--dry-run", action="store_true",
                   help="only list what would change: the packages of each slot set, the "
                        "files to send with their sizes and what would be deleted")
    u.add_argument("--host", metavar="ADDR[:PORT]",
                   help="console address (default: the USB cable's); 127.0.0.1:PORT for "
                        "`lume vm --ssh`")

    dv = sub.add_parser("dev", help="test the console over the USB cable (wait, sh, shot, "
                                    "keys, log)")
    dv.add_argument("--host", metavar="ADDR[:PORT]",
                    help="console address (default: the USB cable's); 127.0.0.1:PORT for "
                         "`lume vm --ssh`")
    ds = dv.add_subparsers(dest="dev_command", required=True, metavar="<action>")
    w = ds.add_parser("wait", help="wait until the console answers over the cable")
    w.add_argument("--timeout", type=float, default=120, metavar="SECONDS")
    sh = ds.add_parser("sh", help="run a command on the console as root (exit code passed)")
    sh.add_argument("cmd", nargs=argparse.REMAINDER, help="the command")
    st = ds.add_parser("shot", help="save a PNG of the console screen")
    st.add_argument("file", type=Path, nargs="?")
    st.add_argument("--compare", metavar="SCREEN",
                    help="reach SCREEN (tests/device/shots/screens.toml), capture and compare "
                         "with the reference of this console; fail above the threshold")
    st.add_argument("--update", metavar="SCREEN",
                    help="store the capture of SCREEN as the new reference of this console")
    ky = ds.add_parser("keys", help="press buttons, e.g. 'a,down*3,start+select,wait:500,"
                                    "fn+start' (see lume_tool.dev for the syntax)")
    ky.add_argument("sequence")
    ky.add_argument("--hold", type=int, default=80, metavar="MS", help="press length")
    ky.add_argument("--gap", type=int, default=120, metavar="MS", help="pause after a press")
    lg = ds.add_parser("log", help="print the boot log of the current boot")
    ck = ds.add_parser("check", help="run the on-device self-test; exit 0 only if all pass")
    rp = ds.add_parser("replay", help="RetroArch replay: record, stop, or play <slot> "
                                      "(network command; needs a running game)")
    rp.add_argument("action", choices=("record", "stop", "play"))
    rp.add_argument("slot", type=int, nargs="?", help="replay slot (play only)")
    rc = ds.add_parser("record", help="record button events on the console "
                                      "(--stop: bring the recording to cache/recordings/)")
    rc.add_argument("--stop", action="store_true", help="stop recording and fetch the file")
    pl = ds.add_parser("play", help="play a recording (.evrec) on the console, "
                                    "printing the measured delay")
    pl.add_argument("file", type=Path)
    rn = ds.add_parser("run", help="run a device test script (tests/device/scripts/<name>.toml "
                                   "or a path); exit 0 only if every step passes")
    rn.add_argument("script", help="script name or path")
    for action in (sh, st, ky, lg, ck, rp, rc, pl, rn):  # not wait: the console may still be off
        action.add_argument("--console", choices=("ga36", "r36s", "vm"),
                            help="refuse to run when the console on the cable is the other one")

    wt = ds.add_parser("watch", help="on every saved file of a lume-* fragment: "
                                     "fragment build, then push --hot (Ctrl-C ends)")
    wt.add_argument("fragment", help="fragment (aports/ name), e.g. lume-core")
    for action in (w, sh, st, ky, lg, ck, rp, rc, pl, rn, wt):
        # also after the action (`lume dev sh --host 127.0.0.1:2222 uname -m`); SUPPRESS
        # keeps the one given before the action when this one is absent
        action.add_argument("--host", metavar="ADDR[:PORT]", default=argparse.SUPPRESS,
                            help="console address, as before the action")

    pw = sub.add_parser("power", help="power profiles: report on the card's metrics and events")
    pw.add_argument("--host", metavar="ADDR", help="console address (default: the USB cable's)")
    ps = pw.add_subparsers(dest="power_command", required=True, metavar="<action>")
    pr = ps.add_parser("report", help="summarise ROMS/logs by scenario and system "
                                      "(table + CSV in cache/), no game names")
    pr.add_argument("--since", type=int, metavar="BOOT", help="only boots numbered BOOT or later")
    pr.add_argument("--console", choices=("ga36", "r36s"),
                    help="refuse to run when the console on the cable is the other one")
    pr.add_argument("--from-dir", type=Path, metavar="DIR",
                    help="read a local copy of ROMS/logs instead of the cable")

    e = sub.add_parser("eject", help="safely flush, unmount and power off the card")
    e.add_argument("device", help="whole card, e.g. /dev/sdc")

    v = sub.add_parser("vm", help="run the vm image in QEMU/KVM")
    v.add_argument("--headless", action="store_true", help="no window: serial on the terminal")
    v.add_argument("--gamepad", action="append", default=[], metavar="EVDEV",
                   help="pass a PC gamepad through (/dev/input/by-id/...-event-joystick)")
    v.add_argument("--share", type=Path, metavar="DIR",
                   help="share a PC folder with the VM (mounted at /mnt/host)")
    v.add_argument("--roms", type=Path, metavar="DIR",
                   help="share a PC ROM folder (bound to /storage/roms in the VM)")
    v.add_argument("--no-gamepad", action="store_true",
                   help="do not pass the host gamepads through to the VM")
    v.add_argument("--ssh", type=_port, nargs="?", const=2222, metavar="PORT",
                   help="local network for `lume dev`: the VM's ssh (root, no password) on "
                        "127.0.0.1:PORT of the PC only (default 2222), no route out")

    k = sub.add_parser("pkg", help="build packages from aports/ for a hardware layer")
    k.add_argument("target", help=f"layer: {', '.join(TARGETS)}")
    k.add_argument("names", nargs="+", help="directories under aports/")
    k.add_argument("--checksum", action="store_true", help="only update the sha512sums")
    k.add_argument("--force", action="store_true",
                   help="compile even when the inputs did not change (a same content is "
                        "still not published)")

    for cmd in (b, u, k):
        cmd.add_argument("--jobs", type=int, metavar="N",
                         help="parallel jobs for make, abuild, mksquashfs and zstd "
                              "(default: LUME_JOBS, else half the cores)")

    t = sub.add_parser("test-vm", help="automated acceptance test of the vm image")
    t.add_argument("--keep", action="store_true", help="keep the VM disk after the test")

    d = sub.add_parser("dtb-import", help="convert vendor RK3326 device trees into "
                                          "board/r36s/dts-vendor/ (boot-dtb-select D12)")
    d.add_argument("sources", nargs="*", metavar="NAME=DIR",
                   help="a collection name and the folder of its DTBs, e.g. "
                        "mydevice=/path/to/dtbs; added to the default collections of "
                        "lume_tool.vendor_dtb.default_sources() (the three public ones are "
                        "required, out/r36s-factory is used when it exists)")

    c = sub.add_parser("clean", help="free the space of build leftovers (dry run by default)")
    c.add_argument("--yes", action="store_true", help="remove (without it, only list)")
    c.add_argument("--keep", type=int, default=3, metavar="N",
                   help="archived images to keep per image, besides latest and the ones "
                        "cited in the docs (default 3)")
    return p


def _heat_guarded(fn):
    """Runs a build step under the heat guard (D15), even on error.

    Pauses the build containers when the CPU is too hot (`LUME_TEMP_GUARD=log` only logs).
    The heat lines join the stage summary when the build prints one, otherwise they are
    printed here. A HeatAbort replaces whatever error the killed containers caused, and
    nothing stays paused when this returns.
    """
    from lume_tool import heat

    guard = heat.guard_from_env().start()
    heat.ACTIVE = guard
    try:
        result = fn()
    except BaseException:
        if guard.error is not None:
            guard.stop()
            raise guard.error from None
        raise
    finally:
        guard.stop()  # resumes anything still paused
        if not guard.reported:
            for line in guard.summary.lines():
                print(line, flush=True)
        heat.ACTIVE = None
    guard.check()
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _main(args)
    except Exception as e:
        from lume_tool.heat import HeatError
        from lume_tool.parallel import PipelineError

        if isinstance(e, PipelineError):  # the summaries were printed by the build
            print(f"error: {e}", file=sys.stderr)
            return 1
        if isinstance(e, HeatError):
            print(f"error: {e}", file=sys.stderr)
            return 2
        raise


def _main(args: argparse.Namespace) -> int:
    try:
        if args.command in ("build", "pkg", "push"):
            from lume_tool import jobs

            jobs.set_jobs(args.jobs)  # the option beats LUME_JOBS
            print(jobs.summary(), flush=True)
        if args.command == "build":
            if args.all == bool(args.target):
                print("error: give a target or --all", file=sys.stderr)
                return 2
            if args.lang is not None:
                lang.retro_language(args.lang)  # validate before creating any file
            from lume_tool import fragment_build, stage_inputs

            if args.variant is not None:
                # device-fixes 6.3: an experiment kernel, never the default image
                if args.target != ["kernel"] or not args.console or args.all or args.clean:
                    print("error: --variant goes with `kernel --console <console>` only",
                          file=sys.stderr)
                    return 2
                from lume_tool import kernel_variants

                kernel_variants.load(args.console, args.variant)   # checked before building
                _heat_guarded(lambda: kernel_variants.build_variant(args.console,
                                                                    args.variant))
                return 0
            fragments = not args.all and fragment_build.is_fragment_target(args.target)
            if fragments:
                # validated before any file is created (an unknown name, an image name)
                fragment_build.plan_fragments(args.target, args.console)
            elif args.console:
                print("error: --console is for a fragment build", file=sys.stderr)
                return 2
            stage_inputs.set_clean(args.clean)
            if fragments:
                _heat_guarded(lambda: fragment_build.build_fragments(
                    args.target, console=args.console, language=args.lang))
                return 0
            language = args.lang or lang.DEFAULT
            if args.all:
                from lume_tool.release import build_all

                return _heat_guarded(lambda: build_all(language=language))
            image = get_image(args.target[0])
            from lume_tool.build import build_image_target

            _heat_guarded(lambda: build_image_target(image, language=language))
            return 0
        if args.command == "flash":
            from lume_tool.flash import main_flash

            return main_flash(get_image(args.target), args.device, args.update,
                              args.build, args.yes, args.eject)
        if args.command == "push" and args.hot:
            if args.dry_run:
                print("error: --dry-run is for the normal push, not --hot", file=sys.stderr)
                return 2
            from lume_tool.push_hot import main_push_hot

            return main_push_hot(args.hot, console=args.console, host=args.host)
        if args.command == "push":
            from lume_tool.push import main_push

            return main_push(args.build, args.yes, wait=not args.no_wait, console=args.console,
                             dry_run=args.dry_run, host=args.host)
        if args.command == "dev":
            from lume_tool.dev import main_dev

            return main_dev(args)
        if args.command == "power":
            from lume_tool.power_report import main_power_report

            return main_power_report(args.since, args.console, args.host, args.from_dir)
        if args.command == "eject":
            from lume_tool.flash import main_eject

            return main_eject(args.device)
        if args.command == "pkg":
            target = get_target(args.target)
            from lume_tool.packages import build_packages

            _heat_guarded(lambda: build_packages(target, args.names, checksum=args.checksum,
                                                 force=args.force))
            return 0
        if args.command == "vm":
            from lume_tool.vm import run_vm

            share = args.roms or args.share
            return run_vm(headless=args.headless, gamepads=args.gamepad, share_dir=share,
                          no_gamepad=args.no_gamepad, ssh_port=args.ssh)
        if args.command == "test-vm":
            from lume_tool.selftest import test_vm

            return test_vm(keep=args.keep)
        if args.command == "dtb-import":
            from lume_tool.paths import REPO_ROOT
            from lume_tool.vendor_dtb import default_sources, import_collections

            sources = default_sources()
            for name, folder in list(sources.items()):
                if name == "factory" and not folder.is_dir():
                    del sources[name]     # the factory card copy is optional
                elif not folder.is_dir():
                    print(f"error: {name}: {folder} is missing (see README, "
                          "\"Converter os DTBs\")", file=sys.stderr)
                    return 2
            for item in args.sources:
                name, sep, folder = item.partition("=")
                if not sep or not Path(folder).is_dir():
                    print(f"error: {item}: expected NAME=DIR", file=sys.stderr)
                    return 2
                sources[name] = Path(folder)
            rows = import_collections(sources, REPO_ROOT / "board/r36s/dts-vendor")
            for status in ("converted", "refused", "same"):
                print(f"{status}: {sum(r['status'] == status for r in rows)}")
            return 0
        if args.command == "clean":
            from lume_tool.clean import main_clean

            return main_clean(yes=args.yes, keep=args.keep)
    except (InvalidTargetError, lang.InvalidLanguageError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

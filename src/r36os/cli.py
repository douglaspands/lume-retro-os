"""Command line: `r36os build|flash|vm|pkg|test-vm`."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from r36os import lang
from r36os.targets import TARGETS, InvalidTargetError, get_target


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="r36os",
        description="Builds the r36s/ga36/vm images and runs the test VM.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    b = sub.add_parser("build", help="build the image of one target (or all with --all)")
    b.add_argument("target", nargs="?", help=f"target: {', '.join(TARGETS)}")
    b.add_argument("--all", action="store_true", help="build the vm, test it, then the consoles")
    b.add_argument("--lang", default=lang.DEFAULT, metavar="CODE",
                   help=f"factory menu language ({', '.join(lang.LANGUAGES)}; default en)")

    f = sub.add_parser("flash", help="write a built image to the card (run it in a terminal)")
    f.add_argument("target", help=f"target: {', '.join(TARGETS)}")
    f.add_argument("device", help="whole card, e.g. /dev/sdc")
    f.add_argument("--update", action="store_true",
                   help="write only the boot area and BOOT, keeping ROMS (games and saves)")
    f.add_argument("--build", default="latest", metavar="TIMESTAMP",
                   help="build from out/images/<target>/ (default: latest)")
    f.add_argument("--yes", action="store_true", help="do not ask for confirmation")

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

    k = sub.add_parser("pkg", help="build packages from aports/ for a target")
    k.add_argument("target", help=f"target: {', '.join(TARGETS)}")
    k.add_argument("names", nargs="+", help="directories under aports/")
    k.add_argument("--checksum", action="store_true", help="only update the sha512sums")

    t = sub.add_parser("test-vm", help="automated acceptance test of the vm image")
    t.add_argument("--keep", action="store_true", help="keep the VM disk after the test")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            if args.all == bool(args.target):
                print("error: give a target or --all", file=sys.stderr)
                return 2
            lang.retro_language(args.lang)  # validate before creating any file
            if args.all:
                from r36os.release import build_all

                return build_all(language=args.lang)
            target = get_target(args.target)
            from r36os.build import build_target

            build_target(target, language=args.lang)
            return 0
        if args.command == "flash":
            from r36os.flash import main_flash

            return main_flash(get_target(args.target), args.device, args.update,
                              args.build, args.yes)
        if args.command == "pkg":
            target = get_target(args.target)
            from r36os.packages import build_packages

            build_packages(target, args.names, checksum=args.checksum)
            return 0
        if args.command == "vm":
            from r36os.vm import run_vm

            share = args.roms or args.share
            return run_vm(headless=args.headless, gamepads=args.gamepad, share_dir=share,
                          no_gamepad=args.no_gamepad)
        if args.command == "test-vm":
            from r36os.selftest import test_vm

            return test_vm(keep=args.keep)
    except (InvalidTargetError, lang.InvalidLanguageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

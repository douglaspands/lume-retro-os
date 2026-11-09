"""Linha de comando: `r36os build|vm|test-vm`."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from r36os.targets import TARGETS, InvalidTargetError, get_target


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="r36os",
        description="Build das imagens r36s/ga36/vm e execução da VM de teste.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<comando>")

    b = sub.add_parser("build", help="gera a imagem de um alvo (ou de todos com --all)")
    b.add_argument("target", nargs="?", help=f"alvo: {', '.join(TARGETS)}")
    b.add_argument("--all", action="store_true", help="gera vm, testa e então os consoles")

    v = sub.add_parser("vm", help="roda a imagem vm no QEMU/KVM")
    v.add_argument("--headless", action="store_true", help="sem janela: serial no terminal")
    v.add_argument("--gamepad", action="append", default=[], metavar="EVDEV",
                   help="repassa um controle do PC (/dev/input/by-id/...-event-joystick)")
    v.add_argument("--share", type=Path, metavar="DIR",
                   help="compartilha uma pasta do PC com a VM (montada em /mnt/host)")
    v.add_argument("--roms", type=Path, metavar="DIR",
                   help="compartilha pasta de ROMs do PC (vinculada a /storage/roms na VM)")
    v.add_argument("--no-gamepad", action="store_true",
                   help="não repassa os controles do host para a VM")

    k = sub.add_parser("pkg", help="constrói pacotes de aports/ para um alvo")
    k.add_argument("target", help=f"alvo: {', '.join(TARGETS)}")
    k.add_argument("names", nargs="+", help="diretórios de aports/")
    k.add_argument("--checksum", action="store_true", help="só atualiza os sha512sums")

    t = sub.add_parser("test-vm", help="teste automatizado de aceitação da imagem vm")
    t.add_argument("--keep", action="store_true", help="mantém o disco da VM após o teste")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            if args.all == bool(args.target):
                print("erro: informe um alvo ou --all", file=sys.stderr)
                return 2
            if args.all:
                from r36os.release import build_all

                return build_all()
            target = get_target(args.target)  # valida antes de criar qualquer arquivo
            from r36os.build import build_target

            build_target(target)
            return 0
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
    except InvalidTargetError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

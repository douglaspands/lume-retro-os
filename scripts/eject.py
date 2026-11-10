#!/usr/bin/env python3
"""Safely eject removable drives (SD cards, USB flash drives, card readers).

Lists removable block devices and safely unmounts all partitions before
powering off / detaching the device via udisksctl (with fallback to eject).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SECTOR = 512
SYS_BLOCK = Path("/sys/block")
_ENV = dict(os.environ, LC_ALL="C", LANG="C")



@dataclass
class PartitionInfo:
    name: str
    path: str
    size_bytes: int
    mountpoints: list[str] = field(default_factory=list)


@dataclass
class DeviceInfo:
    name: str
    path: str
    size_bytes: int
    vendor: str
    model: str
    partitions: list[PartitionInfo] = field(default_factory=list)

    @property
    def label(self) -> str:
        parts = [p for p in (self.vendor, self.model) if p]
        desc = " ".join(parts) if parts else "Removable Disk"
        return f"{self.path} ({desc}, {self.size_bytes / 1e9:.1f} GB)"


def _mountpoints_map() -> dict[str, list[str]]:
    """Map block device path (e.g. /dev/sdc1) to list of mountpoints."""
    res: dict[str, list[str]] = {}
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("/dev/"):
                res.setdefault(parts[0], []).append(parts[1])
    except OSError:
        pass
    return res


def list_removable_devices() -> list[DeviceInfo]:
    """Scan /sys/block for removable storage devices."""
    mounts = _mountpoints_map()
    devices: list[DeviceInfo] = []

    for b in sorted(SYS_BLOCK.glob("*")):

        removable_file = b / "removable"
        if not removable_file.exists():
            continue
        try:
            if removable_file.read_text().strip() != "1":
                continue
            size = int((b / "size").read_text().strip()) * SECTOR
        except (ValueError, OSError):
            continue

        if size == 0:
            continue

        model = (b / "device/model").read_text().strip() if (b / "device/model").exists() else ""
        vendor = (b / "device/vendor").read_text().strip() if (b / "device/vendor").exists() else ""
        dev_path = f"/dev/{b.name}"

        dev = DeviceInfo(
            name=b.name,
            path=dev_path,
            size_bytes=size,
            vendor=vendor,
            model=model,
        )

        for p in sorted(b.glob(f"{b.name}*")):
            if not p.is_dir() or not (p / "partition").exists():
                continue
            try:
                p_size = int((p / "size").read_text().strip()) * SECTOR
            except (ValueError, OSError):
                p_size = 0
            part_path = f"/dev/{p.name}"
            dev.partitions.append(
                PartitionInfo(
                    name=p.name,
                    path=part_path,
                    size_bytes=p_size,
                    mountpoints=mounts.get(part_path, []),
                )
            )

        devices.append(dev)

    return devices


def flush_device(device_path: str) -> None:
    """Ensure all pending writes for this specific device and its filesystems are flushed."""
    try:
        mounts = [line.split()[1] for line in Path("/proc/mounts").read_text().splitlines()
                  if line.startswith(device_path)]
    except OSError:
        mounts = []

    for mp in mounts:
        print(f"  syncing filesystem at {mp}...", flush=True)
        subprocess.run(["sync", "-f", mp], env=_ENV, check=False)

    # Flush block device buffer cache
    subprocess.run(["sudo", "blockdev", "--flushbufs", device_path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=_ENV, check=False)
    subprocess.run(["sync"], env=_ENV, check=False)


def unmount_device(device_path: str) -> None:
    """Unmount all mounted partitions of device_path."""
    try:
        mounted = [line.split()[0] for line in Path("/proc/mounts").read_text().splitlines()
                   if line.startswith(device_path)]
    except OSError:
        mounted = []

    for part in mounted:
        print(f"  unmounting {part}...", flush=True)
        res = subprocess.run(["udisksctl", "unmount", "-b", part],
                             capture_output=True, text=True, env=_ENV)
        if res.returncode != 0 and "not mounted" not in res.stderr.lower():
            # Try sudo umount as fallback
            subprocess.run(["sudo", "umount", part], env=_ENV, check=False)


def eject_device(device_path: str) -> int:
    """Safely flush, unmount and power off / detach the device."""
    real_path = str(Path(device_path).resolve())
    if not Path(real_path).is_block_device():
        print(f"error: {real_path} is not a valid block device", file=sys.stderr)
        return 1

    print(f"Ensuring all pending writes are synchronized for {real_path}...")
    flush_device(real_path)

    print(f"Unmounting partitions on {real_path}...")
    unmount_device(real_path)

    # Post-unmount buffer flush: ensure unmount metadata is written to hardware
    subprocess.run(["sudo", "blockdev", "--flushbufs", real_path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=_ENV, check=False)
    subprocess.run(["sync"], env=_ENV, check=False)

    print(f"Powering off {real_path}...")
    rc = subprocess.run(["udisksctl", "power-off", "-b", real_path],
                        env=_ENV).returncode
    if rc != 0:
        # Fallback to eject
        rc = subprocess.run(["eject", real_path], env=_ENV).returncode

    if rc == 0:
        print(f"ok: {real_path} safely powered off / ejected. You can now disconnect it.")
        return 0
    else:
        print(f"warning: power-off returned {rc}, but buffers were flushed and partitions unmounted.",
              file=sys.stderr)
        return rc



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely eject removable drives (SD cards, USB flash drives, card readers)."
    )
    parser.add_argument("device", nargs="?", help="optional device path (e.g. /dev/sdc or sdc)")
    parser.add_argument("-l", "--list", action="store_true", help="list removable devices and exit")
    args = parser.parse_args(argv)

    devices = list_removable_devices()

    if args.list:
        if not devices:
            print("No removable storage devices found.")
            return 0
        print("Removable storage devices found:")
        for idx, dev in enumerate(devices, 1):
            print(f"  [{idx}] {dev.label}")
            for p in dev.partitions:
                mount_info = f" -> {', '.join(p.mountpoints)}" if p.mountpoints else " (unmounted)"
                print(f"       - {p.path} ({p.size_bytes / 1e9:.1f} GB){mount_info}")
        return 0

    if args.device:
        target = args.device if args.device.startswith("/dev/") else f"/dev/{args.device}"
        return eject_device(target)

    # Interactive mode
    if not devices:
        print("No removable storage devices found.")
        return 0

    print("Removable storage devices found:")
    for idx, dev in enumerate(devices, 1):
        print(f"  [{idx}] {dev.label}")
        for p in dev.partitions:
            mount_info = f" -> {', '.join(p.mountpoints)}" if p.mountpoints else " (unmounted)"
            print(f"       - {p.path} ({p.size_bytes / 1e9:.1f} GB){mount_info}")

    print()
    if len(devices) == 1:
        dev = devices[0]
        try:
            choice = input(f"Safely eject {dev.path}? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 1
        if choice in ("", "y", "yes"):
            return eject_device(dev.path)
        print("Cancelled.")
        return 0

    try:
        choice = input(f"Select device to safely eject (1-{len(devices)}, or q to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 1

    if choice.lower() in ("q", "quit", "exit", ""):
        print("Cancelled.")
        return 0

    try:
        idx = int(choice)
        if 1 <= idx <= len(devices):
            return eject_device(devices[idx - 1].path)
    except ValueError:
        pass

    print("Invalid selection.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

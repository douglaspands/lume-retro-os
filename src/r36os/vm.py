"""VM de teste (D12): QEMU x86_64/KVM em container, disco descartável.

Modo janela: virtio-vga-gl + virgl (GTK), áudio do host, teclado do host.
Modo sem tela: egl-headless, serial no terminal, QMP para capturas e teclas.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from r36os.container import Container, ensure_builder, image_exists, run
from r36os.image import BOOT_START
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir
from r36os.rootfs import target_out
from r36os.targets import TARGETS

VM_IMAGE = "localhost/r36os-vm"
CARD_BYTES = 4_000_000_000 // 512 * 512  # cartão de "4 GB"


def ensure_vm_image() -> str:
    if not image_exists(VM_IMAGE):
        run(["podman", "build", "-t", VM_IMAGE,
             "-f", str(REPO_ROOT / "containers/vm.Containerfile"), str(REPO_ROOT / "containers")])
    return VM_IMAGE


def run_dir() -> Path:
    return ensure_dir(cache_dir() / "vm")


def prepare_disk(dest: Path, append: str = "", src: Path | None = None) -> Path:
    """Cópia descartável de out/vm/vm.img, aumentada para 4 GB como um cartão real.

    `append` acrescenta parâmetros ao cmdline do kernel na cópia (ex.: r36os.selftest=1).
    """
    src = src or target_out(TARGETS["vm"]) / "vm.img"
    if not src.exists():
        raise FileNotFoundError(f"{src} não existe: rode `uv run r36os build vm`")
    dest.unlink(missing_ok=True)
    subprocess.run(["cp", "--reflink=auto", "--sparse=always", str(src), str(dest)], check=True)
    os.truncate(dest, CARD_BYTES)
    if append:
        off = BOOT_START * 512
        Container(image=ensure_builder(TARGETS["vm"]), volumes={dest.parent: "/vm"}).sh(
            f"export MTOOLS_SKIP_CHECK=1; "
            f"mtype -i /vm/{dest.name}@@{off} ::/extlinux/extlinux.conf "
            f"| sed '/^[[:space:]]*APPEND /s|$| {append}|' > /tmp/ext.conf; "
            f"mcopy -o -i /vm/{dest.name}@@{off} /tmp/ext.conf ::/extlinux/extlinux.conf"
        )
    return dest


@dataclass
class VmConfig:
    disk: Path
    headless: bool = True
    extra_disks: list[Path] = field(default_factory=list)
    qmp: Path | None = None
    serial_log: Path | None = None
    gamepads: list[str] = field(default_factory=list)
    share_dir: Path | None = None
    memory_mib: int = 1024
    gl: bool = True  # False: virtio-vga sem virgl (o QMP screendump funciona em qualquer GPU)

    @property
    def host_audio(self) -> bool:
        """Áudio pelo PulseAudio/PipeWire do host (socket pulse/native)."""
        xdg = os.environ.get("XDG_RUNTIME_DIR", "")
        return not self.headless and bool(xdg) and Path(xdg, "pulse/native").exists()


def qemu_argv(cfg: VmConfig) -> list[str]:
    """Linha do QEMU vista de dentro do container (diretório da VM em /vm)."""
    a = ["qemu-system-x86_64", "-name", "lume-retro-os",
         "-machine", "q35,accel=kvm", "-cpu", "host", "-smp", "2",
         "-m", str(cfg.memory_mib), "-nic", "none", "-rtc", "base=utc",
         "-drive", f"file=/vm/{cfg.disk.name},format=raw,if=virtio,cache=writeback"]
    for d in cfg.extra_disks:
        a += ["-drive", f"file=/vm/{d.name},format=raw,if=virtio"]
    a += ["-device", "virtio-vga-gl" if cfg.gl else "virtio-vga"]
    if cfg.headless:
        a += ["-display", "egl-headless,rendernode=/dev/dri/renderD128" if cfg.gl else "none",
              "-audiodev", "none,id=snd0"]
    else:
        a += ["-display", "gtk,gl=on,zoom-to-fit=off"]
        a += ["-audiodev", "pa,id=snd0,server=unix:/tmp/pulse/native" if cfg.host_audio
              else "none,id=snd0"]
    a += ["-device", "intel-hda", "-device", "hda-output,audiodev=snd0"]
    chardev = "stdio,id=ser0,signal=off"
    if cfg.serial_log:
        chardev += f",logfile=/vm/{cfg.serial_log.name}"
    a += ["-chardev", chardev, "-serial", "chardev:ser0"]
    if cfg.qmp:
        a += ["-qmp", f"unix:/vm/{cfg.qmp.name},server=on,wait=off"]
    for ev in cfg.gamepads:
        a += ["-device", f"virtio-input-host-pci,evdev={ev}"]
    if cfg.share_dir:
        # somente leitura: as ROMs do PC nunca são alteradas pela VM
        a += ["-virtfs", "local,path=/share,mount_tag=hostshare,security_model=none,readonly=on"]
    return a


EVIOCGRAB = 1074021776  # ioctl _IOW('E', 0x90, int)


def _can_grab_evdev(path: str) -> bool:
    try:
        import fcntl
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, EVIOCGRAB, 1)
            fcntl.ioctl(fd, EVIOCGRAB, 0)
            return True
        finally:
            os.close(fd)
    except OSError:
        return False


def detect_gamepads() -> list[str]:
    """Detecta controles conectados no PC em /dev/input/by-id/*-event-joystick."""
    by_id = Path("/dev/input/by-id")
    if not by_id.exists():
        return []
    pads: list[str] = []
    for p in sorted(by_id.glob("*-event-joystick")):
        target = p.resolve()
        target_str = str(target)
        if os.access(target, os.R_OK | os.W_OK) and _can_grab_evdev(target_str):
            pads.append(target_str)
    return pads


def gpu_driver() -> str:
    """Driver de kernel da GPU do render node (ex.: amdgpu, i915, nvidia)."""
    link = Path("/sys/class/drm/renderD128/device/driver")
    return link.resolve().name if link.exists() else ""


def nvidia_cdi() -> bool:
    return gpu_driver() == "nvidia" and any(
        Path(d, "nvidia.yaml").exists() or Path(d, "nvidia.json").exists()
        for d in ("/var/run/cdi", "/etc/cdi"))


def podman_argv(cfg: VmConfig) -> list[str]:
    a = ["podman", "run", "--rm", "-i", "--userns=keep-id", "--group-add=keep-groups",
         "--security-opt", "label=disable", "--device", "/dev/kvm", "--device", "/dev/dri",
         "-e", "HOME=/tmp", "-v", f"{cfg.disk.parent}:/vm"]
    if nvidia_cdi():
        # driver proprietário: as bibliotecas GL/EGL do host entram por CDI
        a += ["--device", "nvidia.com/gpu=all"]
    elif gpu_driver() == "nvidia":
        raise RuntimeError("GPU NVIDIA sem especificação CDI: gere com "
                           "`nvidia-ctk cdi generate` (nvidia-container-toolkit)")
    if sys.stdin.isatty():
        a.append("-t")
    if not cfg.headless:
        xdg = os.environ.get("XDG_RUNTIME_DIR", "")
        a += ["-e", "XDG_RUNTIME_DIR=/tmp/xdg"]
        wl = os.environ.get("WAYLAND_DISPLAY")
        if wl and xdg and Path(xdg, wl).exists():
            a += ["-v", f"{xdg}/{wl}:/tmp/xdg/{wl}", "-e", f"WAYLAND_DISPLAY={wl}",
                  "-e", "GDK_BACKEND=wayland"]
        elif os.environ.get("DISPLAY"):
            a += ["-v", "/tmp/.X11-unix:/tmp/.X11-unix", "-e", f"DISPLAY={os.environ['DISPLAY']}"]
        else:
            raise RuntimeError("sem sessão gráfica (WAYLAND_DISPLAY/DISPLAY): use --headless")
        if cfg.host_audio:
            a += ["-v", f"{xdg}/pulse/native:/tmp/pulse/native"]
    for ev in cfg.gamepads:
        a += ["--device", ev]
    if cfg.share_dir:
        share = cfg.share_dir.expanduser().resolve()
        if not share.is_dir():
            raise NotADirectoryError(f"pasta não encontrada: {share}")
        # sem :z (label=disable já libera o acesso): :z reetiquetaria no SELinux a pasta
        # inteira do usuário no host
        a += ["-v", f"{share}:/share:ro"]
    return a + [ensure_vm_image()] + qemu_argv(cfg)


def run_vm(headless: bool = False, gamepads: list[str] | None = None,
           share_dir: Path | None = None, no_gamepad: bool = False) -> int:
    d = run_dir()
    disk = prepare_disk(d / "run.img")
    pads = list(gamepads or [])
    if not pads and not no_gamepad:
        pads = detect_gamepads()
        if pads:
            print(f"Controle(s) detectado(s): {', '.join(pads)}", flush=True)
    cfg = VmConfig(disk=disk, headless=headless, qmp=d / "qmp.sock",
                   serial_log=d / "serial.log", gamepads=pads,
                   share_dir=share_dir)
    (d / "qmp.sock").unlink(missing_ok=True)
    print(f"VM: disco descartável {disk}; serial também em {d / 'serial.log'}; "
          f"QMP em {d / 'qmp.sock'}. Ctrl+A X não se aplica: feche a janela ou use poweroff.",
          flush=True)
    try:
        return subprocess.run(podman_argv(cfg)).returncode
    finally:
        disk.unlink(missing_ok=True)

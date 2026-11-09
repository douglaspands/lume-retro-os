"""./flash.sh — grava um build no cartão SD, inteiro ou por partição (D10)."""

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import REPO_ROOT, deps, layout, mtools
from .cli import PtParser
from .errors import R36Error
from .util import CHUNK, MIB, fmt_mib, log, run, sha256_file, warn

PARTS = ("boot", "system", "storage", "roms")
FULL_ORDER = ("bootarea", "boot", "env", "kernel", "system", "storage", "roms")
TS_RE = re.compile(r"^\d{8}-\d{6}(-test)?$")
SAFE_MOUNT_PREFIXES = ("/run/media/", "/media/", "/mnt/")

HELP = """\
Grava no cartão SD um build gerado pelo ./build.sh (diretório out/<timestamp>/).

Gravação completa (--all): bootarea, p2 (16 MiB), p5, p6, p7, p8 e p1.
Gravação parcial (--part): só as partições escolhidas; exige cartão já gravado
por este repositório (layout compatível).

Proteções: só grava em disco inteiro removível (ou mmcblk), recusa disco com
partições do sistema montadas ou menor que a imagem, exige digitar o nome do
dispositivo, nunca grava mais de 16 MiB na p2 e exige escolha explícita antes
de apagar ROMs (p1) ou saves (p8). Use --dry-run para só ver o plano.

Escolha do build: com --build, usa o identificador indicado (AAAAMMDD-HHMMSS,
com -test nos builds gerados com ./build.sh --test). Sem --build, num
terminal e com mais de um build em out/, mostra um menu (Enter = o mais
recente); fora de um terminal, usa o mais recente sem perguntar. Use
--list-builds para ver os builds com tamanho do cartão e features.

Rode num terminal normal: o script pede a senha do sudo para acessar o cartão.
"""

EPILOG = """\
exemplos:
  ./flash.sh --list-builds
  ./flash.sh --device /dev/sdc --all --wipe-roms --wipe-storage --dry-run
  ./flash.sh --device /dev/sdc --all --keep-roms --keep-storage
  ./flash.sh --device /dev/sdc --part system
  ./flash.sh --device /dev/sdc --part system --part boot --build 20261013-153045
  ./flash.sh --device /dev/sdc --part system --build 20261013-153045-test
  ./flash.sh --target-file teste.img --all --wipe-roms --wipe-storage
"""


def parse_args(argv):
    p = PtParser(prog="./flash.sh", description=HELP, epilog=EPILOG)
    p.add_argument("--device", metavar="DISPOSITIVO", help="disco inteiro do cartão, ex.: /dev/sdc ou /dev/mmcblk0")
    p.add_argument("--target-file", metavar="ARQUIVO",
                   help="grava num arquivo existente em vez de um dispositivo (testes; sem sudo)")
    p.add_argument("--all", action="store_true", help="gravação completa")
    p.add_argument("--part", action="append", choices=PARTS, metavar="PARTIÇÃO",
                   help="gravação parcial: boot, system, storage ou roms (repita para mais de uma)")
    p.add_argument("--keep-roms", action="store_true",
                   help="(--all) mantém a p1 do cartão e a entrada dela no MBR")
    p.add_argument("--wipe-roms", action="store_true",
                   help="autoriza apagar as ROMs da p1 (exigido com --part roms)")
    p.add_argument("--keep-storage", action="store_true", help="(--all) mantém a p8 (saves e configurações)")
    p.add_argument("--wipe-storage", action="store_true",
                   help="autoriza apagar a p8 (exigido com --all sem --keep-storage e com --part storage)")
    p.add_argument("--dry-run", action="store_true",
                   help="simulação: faz as verificações e mostra o plano, sem escrever nada")
    p.add_argument("--no-eject", action="store_true",
                   help="não desliga nem ejeta o cartão após a gravação (mantém no sistema)")
    p.add_argument("--build", metavar="TIMESTAMP",
                   help="build a gravar (AAAAMMDD-HHMMSS, com -test nos builds de teste); padrão: menu no terminal ou o mais recente em out/")
    p.add_argument("--list-builds", action="store_true",
                   help="só lista os builds de out/ (tamanho do cartão e features) e sai")
    args = p.parse_args(argv)
    errs = [] if args.list_builds else validate_args(args)
    if errs:
        p.error(errs[0])
    args.part = sorted(set(args.part or ()), key=PARTS.index)
    return args


def validate_args(a) -> list:
    errs = []
    if bool(a.device) == bool(a.target_file):
        errs.append("indique exatamente um alvo: --device ou --target-file")
    if a.all == bool(a.part):
        errs.append("escolha --all (gravação completa) ou --part (gravação parcial)")
    if a.keep_roms and a.wipe_roms:
        errs.append("as opções --keep-roms e --wipe-roms não podem ser usadas juntas")
    if a.keep_storage and a.wipe_storage:
        errs.append("as opções --keep-storage e --wipe-storage não podem ser usadas juntas")
    if a.part and (a.keep_roms or a.keep_storage):
        errs.append("--keep-roms e --keep-storage só valem com --all (na parcial, não escolha a partição)")
    if a.part and "roms" in a.part and not a.wipe_roms:
        errs.append("gravar a partição roms apaga as ROMs do cartão: repita com --wipe-roms")
    if a.part and "storage" in a.part and not a.wipe_storage:
        errs.append("gravar a partição storage apaga saves, savestates e configurações (p8): repita com --wipe-storage")
    if a.all and not (a.keep_storage or a.wipe_storage):
        errs.append("a gravação completa sobrescreve a p8 (saves e configurações): "
                    "escolha --keep-storage (manter) ou --wipe-storage (apagar)")
    if a.build is not None and not TS_RE.match(a.build):
        errs.append(f"--build deve ter o formato AAAAMMDD-HHMMSS, com -test opcional, recebido {a.build!r}")
    return errs


# ------------------------------------------------------------------ builds

def available_builds(out_root) -> list:
    out_root = Path(out_root)
    if not out_root.is_dir():
        return []
    return sorted(d.name for d in out_root.iterdir()
                  if d.is_dir() and TS_RE.match(d.name) and (d / "manifest.json").is_file())


def resolve_build(out_root, ts=None) -> Path:
    builds = available_builds(out_root)
    if not builds:
        raise R36Error(f"nenhum build encontrado em {out_root}; rode ./build.sh primeiro")
    if ts is None:
        return Path(out_root) / builds[-1]
    if ts not in builds:
        raise R36Error(f"build {ts} não existe em {out_root}. Disponíveis:\n  " + "\n  ".join(builds))
    return Path(out_root) / ts


def load_manifest(build_dir) -> dict:
    return json.loads((Path(build_dir) / "manifest.json").read_text(encoding="utf-8"))


def build_line(build_dir, manifest=None) -> str:
    """Linha usada no menu, no --list-builds e no plano: timestamp, tamanho do cartão e features."""
    name = Path(build_dir).name
    try:
        m = load_manifest(build_dir) if manifest is None else manifest
        feats = ", ".join(f["id"] for f in m["features"]) or "sem features"
        mark = "  test" if m.get("test") else ""
        return f"{name}  {int(m['card_size_mib'])} MiB  {feats}{mark}"
    except (OSError, ValueError, KeyError, TypeError):
        return f"{name}  manifest ilegível"


def build_readable(build_dir) -> bool:
    return not build_line(build_dir).endswith("manifest ilegível")


def list_builds(out_root) -> int:
    builds = available_builds(out_root)[::-1]
    if not builds:
        log(f"Nenhum build encontrado em {out_root}; rode ./build.sh primeiro.")
        return 0
    log(f"Builds em {out_root} (do mais recente para o mais antigo):")
    for i, ts in enumerate(builds, 1):
        log(f"  {i}) {build_line(Path(out_root) / ts)}")
    return 0


def choose_build(out_root, input_fn=input):
    """Menu numerado (1 = mais recente). Devolve o diretório escolhido ou None em EOF."""
    builds = [Path(out_root) / ts for ts in available_builds(out_root)[::-1]]
    log(f"Builds em {out_root}:")
    for i, d in enumerate(builds, 1):
        log(f"  {i}) {build_line(d)}" + ("  (mais recente)" if i == 1 else ""))
    while True:
        try:
            ans = input_fn(f"Build a gravar [1-{len(builds)}, Enter = 1]: ").strip()
        except EOFError:
            return None
        n = int(ans) if ans.isdigit() else (1 if not ans else 0)
        if not 1 <= n <= len(builds):
            warn(f"a opção {ans!r} não existe; responda um número de 1 a {len(builds)}")
        elif not build_readable(builds[n - 1]):
            warn(f"o build {builds[n - 1].name} tem o manifest ilegível; escolha outro")
        else:
            return builds[n - 1]


def select_build(out_root, ts=None, *, interactive=False, input_fn=input):
    """--build vence; sem ele, menu só em terminal e com 2 ou mais builds; senão, o mais recente."""
    if ts is None and interactive and len(available_builds(out_root)) > 1:
        return choose_build(out_root, input_fn)
    return resolve_build(out_root, ts)


def verify_artifacts(build_dir, manifest, names) -> None:
    for name in names:
        r = manifest["regions"][name]
        path = Path(build_dir) / r["file"]
        if not path.is_file():
            raise R36Error(f"artefato ausente: {path}")
        got = sha256_file(path, r["write_length"])
        if got != r["sha256"]:
            raise R36Error(
                f"artefato corrompido: {path}\n  sha256 esperado: {r['sha256']}\n  sha256 obtido:   {got}\n"
                "Gravação recusada; nada foi escrito."
            )


# ------------------------------------------------------------------ alvo

@dataclass
class DiskInfo:
    name: str
    path: str
    size: int
    model: str = ""
    tran: str = ""
    removable: bool = False
    labels: dict = field(default_factory=dict)  # {partição: label}
    mounted: list = field(default_factory=list)  # [(partição, ponto de montagem)]


def _truthy(v):
    return v is True or str(v).lower() in ("1", "true")


def lsblk_json() -> dict:
    out = run(["lsblk", "-J", "-b", "-o", "NAME,TYPE,RM,SIZE,MODEL,TRAN,MOUNTPOINTS,LABEL"]).stdout
    return json.loads(out)


def inspect_device(device: str, data: dict) -> DiskInfo:
    """Aplica as travas do alvo sobre a saída do `lsblk -J`."""
    # /dev/disk/by-id/... -> sdX; sem o dispositivo presente (testes), usa o nome dado
    real = os.path.realpath(device) if os.path.exists(device) else device
    name = os.path.basename(real)
    for disk in data.get("blockdevices", []):
        for child in disk.get("children", []) or []:
            if child["name"] == name:
                raise R36Error(
                    f"{device} é uma partição de /dev/{disk['name']}; indique o disco inteiro "
                    f"(ex.: --device /dev/{disk['name']})"
                )
        if disk["name"] != name:
            continue
        if disk.get("type") != "disk":
            raise R36Error(f"{device} não é um disco inteiro (tipo {disk.get('type')})")
        removable = _truthy(disk.get("rm"))
        if not removable and not name.startswith("mmcblk"):
            raise R36Error(
                f"{device} ({disk.get('model') or 'sem modelo'}, {fmt_mib(int(disk['size']))}) não é removível "
                "(RM=0); recusado para proteger os discos do PC. Se for um leitor USB que se "
                "declara fixo, use outro leitor."
            )
        info = DiskInfo(name=name, path=f"/dev/{name}", size=int(disk["size"]),
                        model=(disk.get("model") or "").strip(), tran=disk.get("tran") or "",
                        removable=removable)
        for node in [disk, *(disk.get("children") or [])]:
            if node.get("label"):
                info.labels[node["name"]] = node["label"]
            for mp in node.get("mountpoints") or []:
                if not mp:
                    continue
                if mp == "[SWAP]" or not mp.startswith(SAFE_MOUNT_PREFIXES):
                    raise R36Error(
                        f"{device} tem a partição {node['name']} montada em {mp} (sistema do PC); recusado"
                    )
                info.mounted.append((node["name"], mp))
        return info
    raise R36Error(f"dispositivo {device} não encontrado (veja: lsblk)")


class FileTarget:
    """Alvo arquivo (testes). Só abre para escrita em write()."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise R36Error(f"--target-file: arquivo {self.path} não existe (crie com: truncate -s 15000M {self.path})")
        self.name = self.path.name
        self.size = self.path.stat().st_size
        self.mtools_prefix = ()

    def describe(self):
        return f"arquivo {self.path} ({fmt_mib(self.size)})"

    def read(self, offset, length):
        with open(self.path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    def mtools_image(self):
        return str(self.path)

    def unmount(self):
        pass

    def write(self, src, offset, length, override=None):
        with open(self.path, "r+b") as fo:
            for pos, buf in _chunks(src, length, override):
                fo.seek(offset + pos)
                fo.write(buf)
            fo.flush()
            os.fsync(fo.fileno())

    def sync(self):
        pass

    def power_off(self) -> bool:
        return False

    def readback_sha256(self, offset, length):
        return sha256_file(self.path, length, offset)


class DeviceTarget:
    """Alvo dispositivo: leitura e escrita via sudo (dd)."""

    def __init__(self, info: DiskInfo):
        self.info = info
        self.path = info.path
        self.name = info.name
        self.size = info.size
        self.mtools_prefix = ("sudo",)

    def describe(self):
        i = self.info
        labels = ", ".join(f"{k}={v}" for k, v in i.labels.items()) or "(nenhum)"
        return (f"{i.path}  modelo: {i.model or '?'}  conexão: {i.tran or '?'}  "
                f"capacidade: {fmt_mib(i.size)} ({i.size} bytes)\n  labels atuais: {labels}")

    def read(self, offset, length):
        p = run(["sudo", "dd", f"if={self.path}", "bs=512", "iflag=skip_bytes,count_bytes",
                 f"skip={offset}", f"count={length}", "status=none"], text=False)
        return p.stdout

    def mtools_image(self):
        return self.path

    def unmount(self):
        for part, mp in self.info.mounted:
            dev = f"/dev/{part}"
            log(f"    desmontando {dev} ({mp})")
            p = subprocess.run(["udisksctl", "unmount", "-b", dev], capture_output=True, text=True)
            if p.returncode != 0:
                p = subprocess.run(["sudo", "umount", dev], capture_output=True, text=True)
            if p.returncode != 0:
                raise R36Error(f"não foi possível desmontar {dev} ({mp}); nada foi escrito.\n{p.stderr.strip()}")

    def write(self, src, offset, length, override=None):
        if override is not None:
            p = subprocess.run(
                ["sudo", "dd", f"of={self.path}", "bs=4M", "oflag=seek_bytes,direct", f"seek={offset}",
                 "conv=fsync,notrunc", "status=none"], input=override)
        else:
            p = subprocess.run(
                ["sudo", "dd", f"if={src}", f"of={self.path}", "bs=4M", "iflag=count_bytes",
                 f"count={length}", "oflag=seek_bytes,direct", f"seek={offset}",
                 "conv=fsync,notrunc", "status=progress"])
        if p.returncode != 0:
            raise R36Error(f"dd falhou gravando em {self.path} no offset {offset}")

    def sync(self):
        subprocess.run(["sync"])
        subprocess.run(["sudo", "blockdev", "--flushbufs", self.path], capture_output=True)
        subprocess.run(["udevadm", "settle"], capture_output=True)

    def power_off(self) -> bool:
        p = subprocess.run(["udisksctl", "power-off", "-b", self.path], capture_output=True, text=True)
        if p.returncode == 0:
            return True
        sysfs_delete = Path(f"/sys/block/{self.name}/device/delete")
        if sysfs_delete.exists():
            p2 = subprocess.run(["sudo", "tee", str(sysfs_delete)], input=b"1\n", capture_output=True)
            return p2.returncode == 0
        return False

    def readback_sha256(self, offset, length):
        h = hashlib.sha256()
        proc = subprocess.Popen(
            ["sudo", "dd", f"if={self.path}", "bs=4M", "iflag=skip_bytes,count_bytes,direct",
             f"skip={offset}", f"count={length}", "status=none"], stdout=subprocess.PIPE)
        n = 0
        for buf in iter(lambda: proc.stdout.read(CHUNK), b""):
            h.update(buf)
            n += len(buf)
        if proc.wait() != 0 or n != length:
            raise R36Error(f"falha ao reler {length} bytes no offset {offset} de {self.path}")
        return h.hexdigest()


def _chunks(src, length, override):
    if override is not None:
        for pos in range(0, len(override), CHUNK):
            yield pos, override[pos: pos + CHUNK]
        return
    with open(src, "rb") as fi:
        pos = 0
        while pos < length:
            buf = fi.read(min(CHUNK, length - pos))
            if not buf:
                raise R36Error(f"{src}: leitura curta")
            yield pos, buf
            pos += len(buf)


# ----------------------------------------------------------- diagnóstico de saúde

DMESG_IO_PATTERNS = (
    "buffer i/o error",
    "reset high-speed usb device",
    "device offline",
    "blk_update_request: i/o error",
)


def check_dmesg_io_errors(device_name: str, *, dmesg_fn=None) -> list:
    """Inspeciona mensagens recentes do dmesg para o dispositivo e retorna alertas de I/O."""
    dev = os.path.basename(device_name)
    if dmesg_fn is not None:
        raw_output = dmesg_fn()
    else:
        try:
            p = subprocess.run(["dmesg"], capture_output=True, text=True)
            if p.returncode != 0:
                p = subprocess.run(["sudo", "dmesg"], capture_output=True, text=True)
            raw_output = p.stdout if p.returncode == 0 else ""
        except Exception:
            raw_output = ""

    if not raw_output:
        return []

    alerts = []
    for line in raw_output.splitlines():
        line_lower = line.lower()
        if dev.lower() in line_lower and any(pat in line_lower for pat in DMESG_IO_PATTERNS):
            alerts.append(line.strip())

    if alerts:
        warn(f"ATENÇÃO: Detectados {len(alerts)} erro(s) de I/O no dmesg para o dispositivo {dev}:")
        for line in alerts[-5:]:
            warn(f"  {line}")
        warn("O leitor USB ou cartão microSD pode estar instável. Recomenda-se usar porta USB direta sem hub.")
    return alerts


def test_hardware_write_lock(target) -> None:
    """Executa teste atômico de escrita, releitura e restauração no último setor do cartão.

    Descarta gravações falsas onde a memória flash travou silenciosamente em modo somente leitura.
    """
    if target.size < layout.SECTOR:
        return
    offset = target.size - layout.SECTOR
    orig = target.read(offset, layout.SECTOR)
    if len(orig) != layout.SECTOR:
        raise R36Error(f"falha ao ler último setor para teste de trava de hardware em {target.name}")

    inverted = bytes((~b) & 0xFF for b in orig)
    target.write(None, offset, layout.SECTOR, override=inverted)
    target.sync()
    got = target.read(offset, layout.SECTOR)

    if got != inverted:
        with contextlib.suppress(Exception):
            target.write(None, offset, layout.SECTOR, override=orig)
            target.sync()
        raise R36Error(
            f"trava de hardware detectada em {target.name}: o cartão está protegido contra gravação física "
            "(read-only lock) e não pode ser regravado. O cartão deve ser substituído."
        )

    target.write(None, offset, layout.SECTOR, override=orig)
    target.sync()
    restored = target.read(offset, layout.SECTOR)
    if restored != orig:
        raise R36Error(f"falha ao restaurar último setor de teste em {target.name}")


def check_p1_filesystem(device_path: str, *, run_fn=None) -> bool:
    """Valida a integridade da FAT32 da p1 de forma não destrutiva (fsck.fat -n)."""
    p1_path = f"{device_path}p1" if device_path and device_path[-1].isdigit() else f"{device_path}1"
    target = p1_path if os.path.exists(p1_path) else device_path

    if run_fn is not None:
        p = run_fn(target)
    else:
        try:
            p = subprocess.run(["sudo", "fsck.fat", "-n", target], capture_output=True, text=True)
            if p.returncode != 0 and "not found" in p.stderr.lower():
                p = subprocess.run(["fsck.fat", "-n", target], capture_output=True, text=True)
        except Exception:
            return True

    if p.returncode != 0:
        err_msg = (p.stdout + "\n" + p.stderr).strip()
        warn(f"AVISO: O sistema de arquivos FAT32 da partição de ROMs ({target}) apresentou inconsistências:")
        for line in err_msg.splitlines()[:5]:
            warn(f"  {line}")
        warn("Recomenda-se fazer backup das ROMs antes de prosseguir.")
        return False
    return True


# ------------------------------------------------------------- layout do cartão

@dataclass
class CardState:
    readable: bool
    sector0: bytes | None = None
    compatible: bool = False
    reasons: list = field(default_factory=list)  # por que não é compatível
    p1_entry: layout.MbrEntry | None = None
    p1_compatible: bool = False
    roms_known: bool = False  # True se a p1 foi lida
    roms_extra: list = field(default_factory=list)
    roms_extra_bytes: int = 0

    @property
    def has_roms(self):
        return bool(self.roms_extra) or self.roms_extra_bytes > 0


def read_card(target, build_dir, manifest) -> CardState:
    """Compara MBR, EBRs e softw411 do cartão com os do build e procura ROMs além da base."""
    expected = (Path(build_dir) / manifest["regions"]["bootarea"]["file"]).read_bytes()
    try:
        _s0, exp_entries, exp_logicals = layout.read_layout(lambda o, n: expected[o:o + n])
        sector0, entries, logicals = layout.read_layout(target.read)
    except R36Error as e:
        return CardState(readable=True, reasons=[str(e)])
    st = CardState(readable=True, sector0=sector0, p1_entry=entries[0])
    for e, x in zip(entries[1:], exp_entries[1:]):
        if (e.type, e.start, e.sectors) != (x.type, x.start, x.sectors):
            st.reasons.append(f"entrada {e.index} do MBR diferente (início {e.start}, setores {e.sectors})")
    if [(lg.start, lg.sectors) for lg in logicals] != [(lg.start, lg.sectors) for lg in exp_logicals]:
        st.reasons.append("partições lógicas p5..p8 em posições diferentes")
    sw_off = manifest["layout"]["softw411_sector"] * 512
    try:
        sw = layout.parse_softw411(target.read(sw_off, layout.SOFTW411_SIZE))
        exp_sw = layout.parse_softw411(expected[sw_off: sw_off + layout.SOFTW411_SIZE])
        if sw.parts != exp_sw.parts:
            st.reasons.append("tabela softw411 diferente")
    except R36Error as e:
        st.reasons.append(str(e))
    st.compatible = not st.reasons
    roms_start = manifest["regions"]["roms"]["offset"] // 512
    p1 = entries[0]
    st.p1_compatible = st.compatible and p1.start == roms_start and p1.sectors > 0 and p1.type in (0x0B, 0x0C)
    if p1.start and p1.sectors and p1.start * 512 < target.size:
        try:
            listing = mtools.listing(target.mtools_image(), p1.start * 512, prefix=target.mtools_prefix)
            known = set(manifest["roms"]["known_paths"])
            st.roms_known = True
            st.roms_extra = sorted(p for p in listing if p.casefold() not in known)
            total = sum(int(e.size) for e in listing.values() if e.type == "-")
            extra_files = sum(int(listing[p].size) for p in st.roms_extra if listing[p].type == "-")
            st.roms_extra_bytes = max(extra_files, total - manifest["roms"]["known_bytes"])
        except R36Error:
            st.roms_known = False
    return st


# ------------------------------------------------------------------ plano

@dataclass
class PlanItem:
    name: str
    offset: int
    length: int
    file: Path
    sha256: str
    override: bytes | None = None  # bootarea com a entrada da p1 do cartão


@dataclass
class Plan:
    items: list
    lost: list  # descrições do que será apagado
    warnings: list
    required_size: int


def make_plan(args, build_dir, manifest, card: CardState, target_size) -> Plan:
    regions = manifest["regions"]
    build_dir = Path(build_dir)

    def item(name):
        r = regions[name]
        return PlanItem(name, r["offset"], r["write_length"], build_dir / r["file"], r["sha256"])

    lost, warnings = [], []
    if args.all:
        names = list(FULL_ORDER)
        if args.keep_storage:
            if not card.compatible:
                raise R36Error("--keep-storage exige um cartão com o layout desta família de imagens "
                               "(p8 na mesma posição): " + "; ".join(card.reasons))
            names.remove("storage")
        else:
            lost.append("p8 (STORAGE): saves, savestates e configurações serão apagados")
        if card.has_roms and not (args.keep_roms or args.wipe_roms):
            raise R36Error(
                f"a p1 do cartão tem ROMs além das da base ({len(card.roms_extra)} entrada(s), "
                f"{fmt_mib(card.roms_extra_bytes)}). Escolha:\n"
                "  --keep-roms  mantém a p1 e a entrada dela no MBR (grava o resto)\n"
                "  --wipe-roms  apaga as ROMs e grava a p1 do build"
            )
        override = None
        if args.keep_roms:
            if not card.p1_compatible:
                why = "; ".join(card.reasons) or (
                    f"a p1 do cartão começa no setor {card.p1_entry.start if card.p1_entry else '?'}, "
                    f"esperado {regions['roms']['offset'] // 512}")
                raise R36Error(f"--keep-roms recusado: não é possível preservar a p1 com segurança ({why})")
            if not card.p1_entry or card.p1_entry.start != layout.P1_CANONICAL_START:
                raise R36Error(
                    f"--keep-roms recusado: a partição p1 deve iniciar no setor {layout.P1_CANONICAL_START} "
                    f"(detectado: {card.p1_entry.start if card.p1_entry else '?'})"
                )
            names.remove("roms")
            bootarea = (build_dir / regions["bootarea"]["file"]).read_bytes()
            entry = layout.build_canonical_p1_entry(target_size)
            override = layout.replace_p1_entry(bootarea[:512], entry) + bootarea[512:]
        else:
            if card.has_roms:
                lost.append(f"p1 (ROMS): {len(card.roms_extra)} entrada(s) além da base, "
                            f"{fmt_mib(card.roms_extra_bytes)}, serão apagadas")
            elif card.readable and not card.roms_known:
                warnings.append("não foi possível ler a p1 atual do cartão; o conteúdo dela será apagado")
            lost.append("tabela de partições e todo o conteúdo anterior do cartão (exceto o que for mantido)")
        items = [item(n) for n in names]
        if override is not None:
            ba = next(i for i in items if i.name == "bootarea")
            ba.override = override
            ba.sha256 = hashlib.sha256(override).hexdigest()
        required = manifest["image"]["size_bytes"] if not args.keep_roms else max(i.offset + i.length for i in items)
        if not args.keep_roms and target_size < required:
            raise R36Error(
                f"cartão menor que a imagem: cartão {target_size} bytes ({fmt_mib(target_size)}), "
                f"imagem {required} bytes ({fmt_mib(required)}). Gere a imagem com tamanho menor, ex.: "
                f"./build.sh --size-mib {target_size // MIB // 4 * 4}"
            )
        if not args.keep_roms and target_size > required:
            warnings.append(f"{fmt_mib(target_size - required)} do cartão ficarão sem uso "
                            f"(gere com --size-mib {target_size // MIB // 4 * 4} para usar tudo)")
    else:
        if not card.compatible:
            raise R36Error(
                "o cartão não tem o layout desta família de imagens ("
                + "; ".join(card.reasons or ["layout ilegível"])
                + "). Faça a gravação completa primeiro (--all)."
            )
        names = list(args.part)
        if "roms" in names:
            exp = regions["roms"]
            card_p1 = card.p1_entry
            if not card.p1_compatible or card_p1.sectors * 512 != exp["size"]:
                raise R36Error(
                    "a p1 do cartão tem tamanho diferente da p1 deste build "
                    f"({card_p1.sectors * 512 if card_p1 else '?'} vs {exp['size']} bytes); "
                    "use a gravação completa (--all --wipe-roms) ou gere o build com o tamanho do cartão"
                )
            lost.append(f"p1 (ROMS): todo o conteúdo"
                        + (f" ({fmt_mib(card.roms_extra_bytes)} de ROMs além da base)" if card.has_roms else ""))
        if "storage" in names:
            lost.append("p8 (STORAGE): saves, savestates e configurações serão apagados")
        items = [item(n) for n in names]
        required = max(i.offset + i.length for i in items)
    if target_size < required:
        raise R36Error(f"cartão menor que o necessário: {target_size} < {required} bytes")
    boot = next((i for i in items if i.name == "boot"), None)
    if boot and boot.length > 16 * MIB:
        raise R36Error("p2 maior que 16 MiB no manifest; recusado")
    return Plan(items, lost, warnings, required)


def show_plan(target, build_dir, manifest, card, plan, args):
    log(f"Build: {build_line(build_dir, manifest)}")
    log(f"Imagem: {manifest['image']['file']}")
    log(f"Alvo: {target.describe()}")
    log(f"Layout atual do cartão: {'compatível' if card.compatible else 'incompatível'}"
        + ("" if card.compatible else f" ({'; '.join(card.reasons)})"))
    if card.roms_known:
        log(f"ROMs além da base na p1: {'sim, ' + fmt_mib(card.roms_extra_bytes) if card.has_roms else 'não'}")
    log(f"Modo: {'gravação completa' if args.all else 'gravação parcial: ' + ', '.join(args.part)}"
        + (" + mantém ROMs" if args.keep_roms else "") + (" + mantém STORAGE" if args.keep_storage else ""))
    log("Regiões a escrever:")
    total = 0
    for i in plan.items:
        extra = "  (entrada da p1 do cartão preservada)" if i.override is not None else ""
        log(f"  {i.name:<9} offset {i.offset:>12}  setor {i.offset // 512:>9}  {fmt_mib(i.length):>12}{extra}")
        total += i.length
    log(f"  total: {fmt_mib(total)}")
    if plan.lost:
        log("Dados que serão apagados:")
        for l in plan.lost:
            log(f"  - {l}")
    for w in plan.warnings:
        warn(w)


def confirm(target, input_fn=input) -> bool:
    try:
        ans = input_fn(f"\nPara confirmar, digite o nome do dispositivo ({target.name}): ")
    except EOFError:
        return False
    return ans.strip() == target.name


def write_plan(target, plan) -> None:
    for i in plan.items:
        log(f"==> gravando {i.name} ({fmt_mib(i.length)})")
        target.write(i.file, i.offset, i.length, i.override)
    target.sync()
    failed = []
    for i in plan.items:
        got = target.readback_sha256(i.offset, i.length)
        ok = got == i.sha256
        log(f"    {i.name:<9} {'verificado' if ok else 'DIVERGENTE'}")
        if not ok:
            failed.append(i.name)
    if failed:
        raise R36Error(f"verificação pós-gravação falhou em: {', '.join(failed)}")


def flash(args, *, out_root=None, input_fn=input, lsblk=None, interactive=None) -> int:
    out_root = Path(out_root or REPO_ROOT / "out")
    if args.list_builds:
        return list_builds(out_root)
    if interactive is None:
        interactive = sys.stdin.isatty()
    build_dir = select_build(out_root, args.build, interactive=interactive, input_fn=input_fn)
    if build_dir is None:
        log("Escolha cancelada; nada foi escrito.")
        return 1
    manifest = load_manifest(build_dir)
    if args.target_file:
        target = FileTarget(args.target_file)
    else:
        deps.check_flash()
        info = inspect_device(args.device, lsblk() if lsblk else lsblk_json())
        target = DeviceTarget(info)
        check_dmesg_io_errors(target.name)
    card = read_card(target, build_dir, manifest)
    plan = make_plan(args, build_dir, manifest, card, target.size)
    show_plan(target, build_dir, manifest, card, plan, args)
    log("Conferindo sha256 dos artefatos contra o manifest...")
    verify_artifacts(build_dir, manifest, [i.name for i in plan.items])
    if args.dry_run:
        log("\nSimulação (--dry-run): nada foi escrito.")
        return 0
    if not confirm(target, input_fn):
        log("Confirmação não confere; nada foi escrito.")
        return 1
    if isinstance(target, DeviceTarget):
        log("Verificando se o cartão possui trava de gravação física (read-only lock)...")
        test_hardware_write_lock(target)
        if args.keep_roms:
            check_p1_filesystem(target.path)
    target.unmount()
    write_plan(target, plan)
    if not args.no_eject and isinstance(target, DeviceTarget):
        ok = target.power_off()
        if ok:
            log(f"\n==> Dispositivo {target.path} desenergizado e desconectado com segurança.")
            log("O cartão microSD pode ser removido fisicamente do computador.")
        else:
            log("\nGravação concluída e verificada. Pode remover o cartão.")
    else:
        log("\nGravação concluída e verificada.")
        if args.no_eject:
            log("Dispositivo mantido conectado (--no-eject).")
        else:
            log("Pode remover o cartão.")
    return 0


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return flash(args)
    except R36Error as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130

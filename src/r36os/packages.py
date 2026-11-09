"""Estágio 2: pacotes Alpine locais (abuild) e repositório local `out/repo/<arch>`."""

from __future__ import annotations

from pathlib import Path

from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir, out_dir
from r36os.targets import Target

KEY_NAME = "r36os"
REPO_NAME = "r36os"  # abuild grava em $REPODEST/<nome do dir pai>/<arch>


def aport_arches(apkbuild: Path) -> list[str]:
    """Valor de arch= do APKBUILD (ex.: ['all', '!armv7'])."""
    for line in apkbuild.read_text().splitlines():
        if line.startswith("arch="):
            return line.split("=", 1)[1].strip().strip('"').split()
    return ["all"]


def builds_for(apkbuild: Path, arch: str) -> bool:
    arches = aport_arches(apkbuild)
    if f"!{arch}" in arches:
        return False
    return any(a in ("all", "noarch", arch) for a in arches)


def local_aports(target: Target | None = None) -> list[str]:
    """Pacotes de aports/ (cada subdiretório com APKBUILD), em ordem estável.

    Com `target`, só os que o arch= do APKBUILD permite (o mesa local é só x86_64).
    """
    found = sorted((REPO_ROOT / "aports").glob("*/APKBUILD"))
    return [p.parent.name for p in found
            if target is None or builds_for(p, target.alpine_arch)]


def keys_dir() -> Path:
    return cache_dir() / "abuild"


def repo_dir(target: Target) -> Path:
    return out_dir() / "repo" / target.alpine_arch


def public_key() -> Path:
    return keys_dir() / f"{KEY_NAME}.rsa.pub"


def _container(target: Target, aports: Path) -> Container:
    cache = cache_dir()
    ensure_dir(keys_dir())
    ensure_dir(cache / "distfiles")
    ensure_dir(cache / "ccache" / target.alpine_arch)
    ensure_dir(out_dir() / "repo")
    return Container(
        image=ensure_builder(target),
        platform=target.oci_platform,
        volumes={
            aports: f"/aports/{REPO_NAME}",
            out_dir() / "repo": f"/repodest/{REPO_NAME}",
            keys_dir(): "/root/.abuild",
            cache / "distfiles": "/cache/distfiles",
            cache / "ccache" / target.alpine_arch: "/cache/ccache",
        },
        # USE_CCACHE=1: sem ele o abuild não põe /usr/lib/ccache/bin no PATH, e sob
        # emulação (ARM) cada recompilação custaria horas
        env={"REPODEST": "/repodest", "CCACHE_DIR": "/cache/ccache", "USE_CCACHE": "1"},
    )


_SETUP_KEY = f"""
if [ ! -f /root/.abuild/{KEY_NAME}.rsa ]; then
  openssl genrsa -out /root/.abuild/{KEY_NAME}.rsa 4096
  openssl rsa -in /root/.abuild/{KEY_NAME}.rsa -pubout -out /root/.abuild/{KEY_NAME}.rsa.pub
fi
echo 'PACKAGER_PRIVKEY=/root/.abuild/{KEY_NAME}.rsa' > /root/.abuild/abuild.conf
cp /root/.abuild/{KEY_NAME}.rsa.pub /etc/apk/keys/
apk update -q
"""


def ensure_key(target: Target) -> Path:
    """Gera a chave de assinatura do abuild no cache (uma vez, compartilhada pelos arches)."""
    _container(target, REPO_ROOT / "aports").sh(_SETUP_KEY)
    return public_key()


def build_packages(
    target: Target, names: list[str], aports: Path | None = None, checksum: bool = False
) -> None:
    """Constrói os pacotes `aports/<nome>` para a arquitetura do alvo.

    Com `checksum=True`, só atualiza os sha512sums dos APKBUILDs (abuild checksum).
    """
    aports = aports or REPO_ROOT / "aports"
    step = "abuild -F checksum" if checksum else "abuild -F -r -P /repodest"
    # abuild -r instala as dependências; ao final atualiza e assina o APKINDEX do repositório.
    script = _SETUP_KEY + "".join(
        f"(cd /aports/{REPO_NAME}/{n} && {step})\n" for n in names
    )
    _container(target, aports).sh(script)


def install_test(target: Target, name: str, aports: Path) -> str:
    """Instala `name` num container limpo a partir do repositório local e devolve `apk info`."""
    c = _container(target, aports)
    out = c.sh(
        _SETUP_KEY
        + f"apk add --repository /repodest/{REPO_NAME} {name} >/dev/null\n"
        + f"apk info -e {name}\n",
        capture_output=True,
        text=True,
    )
    return out.stdout

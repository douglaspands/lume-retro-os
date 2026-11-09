# Cross-compilador x86_64 para kernel e U-Boot dos consoles (estágio 1).
# Kernel e U-Boot não usam libc, então o toolchain glibc do Debian serve.
FROM docker.io/library/debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc-aarch64-linux-gnu gcc-arm-linux-gnueabihf gcc make \
        device-tree-compiler bc flex bison \
        libssl-dev libgnutls28-dev uuid-dev libelf-dev \
        python3 python3-setuptools python3-pyelftools python3-dev swig \
        python3-venv cpio kmod rsync xz-utils zstd git ca-certificates \
        ccache \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/dtschema \
    && /opt/dtschema/bin/pip install --no-cache-dir dtschema

ENV PATH=/opt/dtschema/bin:$PATH \
    CCACHE_DIR=/cache/ccache
WORKDIR /work

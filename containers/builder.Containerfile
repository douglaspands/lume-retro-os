# Builder Alpine (estágios 2, 3 e 4): abuild, rootfs com apk --root, SYSTEM e imagem.
# É construído para cada arquitetura alvo (--platform linux/amd64|arm64|arm/v7),
# para os scripts de pós-instalação do apk rodarem de verdade.
ARG ALPINE_VERSION=3.24
FROM docker.io/library/alpine:${ALPINE_VERSION}

# syslinux só existe no Alpine x86 e só é usado pela imagem vm (os consoles usam U-Boot)
RUN apk add --no-cache \
        alpine-sdk abuild ccache sudo \
        mtools dosfstools sfdisk \
        squashfs-tools zstd \
        jq bash coreutils findutils tar xz cpio \
        busybox-static exfatprogs \
    && if [ "$(apk --print-arch)" = x86_64 ]; then apk add --no-cache syslinux; fi \
    && adduser -D -G abuild builder \
    && echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder

ENV PACKAGER="r36os <r36os@localhost>" \
    CCACHE_DIR=/cache/ccache \
    SRCDEST=/cache/distfiles
WORKDIR /work

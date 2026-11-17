# distccd for one ARM architecture (build-speed D7, P-36), native x86_64.
# The compiler is the cross gcc built by containers/cross-gcc.sh from the same Alpine
# main/gcc APKBUILD as the target's gcc. distcc sends the compiler path the client used
# (/usr/bin/cc, /usr/bin/gcc, ...), so in this image those names ARE the cross compiler;
# there is no x86_64 gcc here.
# Build context: <cache>/cross-gcc/<arch>/repo/main (the abuild REPODEST of the toolchain).
ARG ALPINE_VERSION=3.24
FROM docker.io/library/alpine:${ALPINE_VERSION}
ARG CTARGET_ARCH
ARG CTARGET

# the packages are unpacked with tar: gcc-<arch> depends on libgcc-static-<arch>, an
# arch=<arch> package that apk will not install on x86_64 (only linking needs it)
RUN --mount=type=bind,source=x86_64,target=/repo \
    set -eu; \
    apk add --no-cache distcc tar binutils-${CTARGET_ARCH}; \
    : > /tmp/deps; \
    for p in /repo/gcc-${CTARGET_ARCH}-[0-9]*.apk /repo/g++-${CTARGET_ARCH}-[0-9]*.apk \
             /repo/libstdc++-dev-${CTARGET_ARCH}-[0-9]*.apk; do \
        tar -xzf "$p" -C / --exclude='.PKGINFO' --exclude='.SIGN.*' 2>/dev/null; \
        tar -xzOf "$p" .PKGINFO | sed -n 's/^depend = \(so:.*\)/\1/p' >> /tmp/deps; \
    done; \
    apk add --no-cache $(sort -u /tmp/deps); \
    rm /tmp/deps; \
    ln -sf ${CTARGET}-gcc /usr/bin/gcc; \
    ln -sf ${CTARGET}-gcc /usr/bin/cc; \
    ln -sf ${CTARGET}-g++ /usr/bin/g++; \
    ln -sf ${CTARGET}-g++ /usr/bin/c++; \
    echo 'int f(int x) { return x * 3; }' > /tmp/t.c; \
    cc -O2 -c /tmp/t.c -o /tmp/t.o; \
    ${CTARGET}-objdump -f /tmp/t.o; \
    rm /tmp/t.c /tmp/t.o; \
    cc --version | head -n1

USER distcc

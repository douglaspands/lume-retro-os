# aports locais do Lume Retro OS

Pacotes Alpine construídos com `abuild` no container do arch alvo e publicados em
`out/repo/<arch>`, assinados com a chave local em `~/.cache/r36os/abuild/`.

```
uv run r36os pkg <alvo> <pacote>...            # constrói
uv run r36os pkg <alvo> --checksum <pacote>... # atualiza sha512sums
```

## retroarch (tarefa 2.1)

Verificação do `retroarch` 1.22.2-r1 do Alpine v3.24 (community), em 2026-11-09,
com `retroarch --features` num container `alpine:3.24` x86_64:

| Item | Alpine 1.22.2-r1 |
|---|---|
| KMS | sim |
| EGL | sim |
| udev | sim |
| GLES | **não**: só OpenGL desktop (`libGL.so.1`) |
| X11, Wayland, Qt6, SDL2, PulseAudio, FFmpeg, Vulkan | sim (dependências que a distro não quer) |
| Dependências de dados | `retroarch-assets` completo, `libretro-database`, `retroarch-joypad-autoconfig` |

Como faltava GLES, há um `aports/retroarch` local (1.22.2-**r100**, para vencer o
pacote do Alpine) com `--enable-kms --enable-egl --enable-opengles --enable-udev
--enable-alsa --enable-freetype` e `--disable-x11 --disable-wayland --disable-qt
--disable-sdl2 --disable-pulse --disable-ffmpeg --disable-vulkan`. Depende só de
`libretro-core-info`; `retroarch-assets` e `retroarch-joypad-autoconfig` do Alpine
entram pela lista de pacotes.

`--features` do pacote local: UDEV, OpenGLES, EGL, KMS, ALSA e FreeType = yes; sem
X11, Wayland, Qt, SDL2 e PulseAudio. `ldd` mostra `libGLESv2`, `libEGL`, `libgbm`,
`libdrm`, `libudev` e `libasound`.

## Cores (tarefa 2.2)

| Pacote | Origem | Commit |
|---|---|---|
| libretro-snes9x2005-plus | novo, o core de SNES de fábrica do GA36 (build padrão, `USE_BLARGG_APU=1`; substitui o snes9x2010 desde 2026-11-11) | `fd45b0e0` |
| libretro-snes9x | testing (edge); **desativado** (`arch=""`) desde 2026-11-11, a pedido do usuário | `229933ea` |
| libretro-genesis-plus-gx | testing (edge) | `b72b8c96` |
| libretro-picodrive | testing, atualizado + submódulos | `1890c293` |
| libretro-fbneo | testing, atualizado (zlib embutido) | `77016b4d` |
| libretro-mame2003-plus | novo; **desativado** (`arch=""`) desde 2026-11-11, a pedido do usuário | `4f6b3b46` |
| libretro-pcsx-rearmed | testing, atualizado (inclui armv7) | `7b0e8f8f` |

Os cores `fceumm`, `nestopia`, `gambatte` e `gpsp` vêm do Alpine v3.24. O `mgba` não entra
nesta versão: o GBA usa o `gpsp` em todos os alvos.

O `libretro-ppsspp` (PSP) está desativado com `arch=""`: ele não é construído e está fora
do catálogo nesta versão (pendência 12.1 do `tasks.md`). O `libretro-mame2003-plus` também,
a pedido do usuário (2026-11-11): o arcade usa o `fbneo` em todos os consoles, o mesmo
romset nos dois aparelhos do cartão único. E o `libretro-snes9x`, também a pedido do usuário
(2026-11-11): o SNES usa o `snes9x2005_plus`, sem alternativo.

Ajustes para o musl:

- **mame2003-plus:** o vídeo do ST-V (`src/vidhrdw/stvvid.c`) força
  `tls_model("initial-exec")`, e o musl recusa esse modelo num `.so` aberto por
  `dlopen` ("initial-exec TLS resolves to dynamic definition"). O `prepare()`
  remove o atributo, e o compilador passa a usar TLS dinâmico.
- **todos:** `linux-headers` nos makedepends (o libretro-common usa `linux/futex.h`).

Verificação: `tests/cores/load_cores.sh` carrega cada core com
`retroarch -L <core> --max-frames=1` (vídeo, áudio e entrada `null`) e confere
que o `dlopen` funcionou (o core roda um quadro ou pede conteúdo).

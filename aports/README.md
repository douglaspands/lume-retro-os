# aports locais do Lume Retro OS

Pacotes Alpine construídos com `abuild` no container do arch alvo e publicados em
`out/repo/<arch>`, assinados com a chave local em `.cache/abuild/` (cache do build, na raiz
do projeto).

```
uv run lume pkg <alvo> <pacote>...            # constrói
uv run lume pkg <alvo> --checksum <pacote>... # atualiza sha512sums
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
| libretro-snes9x2005-plus | novo, o core de SNES nos dois consoles (build padrão do upstream, sem flags por CPU, `USE_BLARGG_APU=1`; substitui o snes9x2010 desde 2026-11-11; commit mais novo do upstream desde a `game-governor`, D15) | `a79dfe90` |
| libretro-genesis-plus-gx | testing (edge) | `b72b8c96` |
| libretro-picodrive | testing, atualizado + submódulos | `1890c293` |
| libretro-fbneo | testing, atualizado (zlib embutido) | `77016b4d` |
| libretro-mame2003-plus | novo; core de arcade alternativo (`game-experience-tuning` 10.5; desativado de 2026-11-11 a 2026-11-19); build padrão do upstream, sem flags por CPU; licença MAME não comercial | `2a60eda7` |
| libretro-mame2000 | novo; core de arcade medido e fora da imagem (`game-experience-tuning` 10.5; MAME 0.37b5); build padrão do upstream, sem flags por CPU e sem `ARM=1` (só liga assembly ARM de 32 bits); licença MAME não comercial | `181b42e5` |
| libretro-fbalpha2012 | novo; o FB Alpha 2012 completo (todas as placas), core padrão do arcade, do CPS-1, do CPS-2 e do Neo Geo (`game-experience-tuning` 10.5); build padrão do upstream, sem flags por CPU; licença do FB Alpha, não comercial | `0ce31536` |
| libretro-pcsx-rearmed | testing, atualizado (inclui armv7) | `7b0e8f8f` |
| libretro-mednafen-pce-fast | novo, PC Engine/TurboGrafx-16 e PCE-CD (`game-experience-tuning` D8; build padrão do upstream, sem flags por CPU; o `.info` vem do `libretro-core-info`) | `2de1ce1c` |

Os cores `fceumm`, `nestopia`, `gambatte` e `gpsp` vêm do Alpine v3.24. O `mgba` não entra
nesta versão: o GBA usa o `gpsp` em todos os alvos.

### Builds `_lume` dos cores (`game-experience-tuning` 11.1, P-114)

Cada um dos 16 cores da imagem ganha um pacote `libretro-<core>-lume`: o mesmo código e o
mesmo nível de otimização do upstream (sem `-Ofast`, sem LTO), com as flags do processador
acrescentadas ao `CFLAGS` e ao `CXXFLAGS` (armv7, Cortex-A7: `-marm -mcpu=cortex-a7
-mfpu=neon-vfpv4 -mfloat-abi=hard`; aarch64, Cortex-A35: `-mcpu=cortex-a35`; x86_64: nenhuma,
é o build do upstream, que não é construído). O id do core muda: `<core>_lume_libretro.so` e
`<core>_lume_libretro.info`, com o `corename` do upstream mais ` (Lume)`. Na imagem e no
catálogo ficam só os que venceram o build do upstream no GA36 (tarefa 11.5,
`cores_lume.ADOPTED`): `genesis_plus_gx_lume`, `snes9x2005_plus_lume` e `pcsx_rearmed_lume`,
no lugar do build do upstream. Os outros (empate ou perda) ficam como aport, prontos para
medir de novo. O `corename` marcado só identifica o core nas listas do RetroArch: as pastas
de opções e de remapeamentos seguem o `library_name` que o próprio core informa, que é o do
upstream, então o `_lume` usa as mesmas pastas do usuário, sem migração (conferido no GA36,
2026-11-20).

Os 18 `aports/libretro-*-lume/APKBUILD` são **gerados** por `lume cores-lume` (módulo
`lume_tool.cores_lume`) a partir do aport do upstream de cada core, e um teste falha se algum
estiver fora de data: não se edita o arquivo, e sim o aport do upstream ou o gerador. A cópia
do aport do Alpine dos quatro cores que a imagem tinha do Alpine (`fceumm`, `nestopia`,
`gambatte`, `gpsp`, no mesmo commit de hoje) fica em `aports/_upstream/` e não é um aport.
O `.info` vem do `libretro-core-info` (dependência de build); no armv7 o `package()` confere
que o `.so` tem NEON. Variantes só no armv7, com o Cyclone (68000) e o DrZ80 (Z80) em
assembly ARM: `libretro-mame2000-cyclone-lume` e `libretro-mame2003-plus-cyclone-lume`
(`mame2000_cyclone_lume`, `mame2003_plus_cyclone_lume`), em `board/ga36/hw-packages.txt`.

O `libretro-ppsspp` (PSP) está desativado com `arch=""`: ele não é construído e está fora
do catálogo nesta versão (pendência 12.1 do `tasks.md`). Arcade, CPS-1, CPS-2 e Neo Geo usam
o `fbalpha2012` completo em todos os consoles (o mesmo romset nos dois aparelhos do cartão
único); o `mame2003-plus` e o `fbneo` são os alternativos do arcade, e o `fbneo` o do CPS-1,
do CPS-2 e do Neo Geo e o padrão do CPS-3 (`game-experience-tuning` 10.5). O `mame2000` e os
recortes `fbalpha2012-cps1`, `-cps2` e `-neogeo` saíram da imagem e ficam só como aport. O
`.info` de cada um vem do `libretro-core-info` do Alpine v3.24. O SNES usa o
`snes9x2005_plus` (o build `_lume`), sem alternativo (o aport do `snes9x` foi removido).

Ajustes para o musl:

- **mame2003-plus:** o vídeo do ST-V (`src/vidhrdw/stvvid.c`) força
  `tls_model("initial-exec")`, e o musl recusa esse modelo num `.so` aberto por
  `dlopen` ("initial-exec TLS resolves to dynamic definition"). O `prepare()`
  remove o atributo, e o compilador passa a usar TLS dinâmico.
- **todos:** `linux-headers` nos makedepends (o libretro-common usa `linux/futex.h`).

Verificação: `tests/cores/load_cores.sh` carrega cada core com
`retroarch -L <core> --max-frames=1` (vídeo, áudio e entrada `null`) e confere
que o `dlopen` funcionou (o core roda um quadro ou pede conteúdo).

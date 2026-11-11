# Cores do firmware de fábrica do GA36 (EmuELEC)

Referência para o P-24: o core padrão e os alternativos de cada sistema no EmuELEC do
firmware de fábrica do GA36-MB V1.2 (imagem `R36S GA36-MB V1.2-20260416`). Serve para
comparar com os padrões da nossa distro e avaliar, no aparelho, qual core rende mais.

**Origem:** o `es_systems.cfg` do EmulationStation, extraído em 2026-11-11 da *feature*
`53-cores-a33` do projeto anterior (`R36S GA36-MB V1.2-20260416/features/53-cores-a33/
system/usr/config/emulationstation/es_systems.cfg`). Essa cópia é a de fábrica com uma
única mudança: o core `snes9x2005_plus_a33` (recompilado para o Cortex-A7) foi acrescentado
como alternativo no SNES, e o `emuelec.conf` da *feature* `10-ptbr-sao-paulo` o tornava o
padrão do SNES. O padrão de cada sistema é o `<core default="true">`.

**Como ler:**

- Nome sem prefixo: core **libretro** (roda dentro do RetroArch, como os nossos).
- `EMULADOR:nome` (ex.: `FBNEOSA:FbneoSA`, `AMIBERRY:AMIBERRY`, `flycastsa:flycastsa`):
  emulador **standalone** (fora do RetroArch). A nossa distro não tem emuladores
  standalone; para esses sistemas, a comparação é com o melhor core libretro alternativo.
- `-`: o sistema não tem padrão marcado.
- Sufixo `_32b`: build de 32 bits em um EmuELEC de 64 bits. No A33 tudo é 32 bits, então
  equivale ao core sem sufixo.

## 1. Os sistemas que a nossa distro já tem

| Sistema | Fábrica: padrão | Fábrica: alternativos | Nossa distro hoje | Diferença |
|---|---|---|---|---|
| NES (`nes`) | nestopia | fceumm, fceumm_mod | fceumm (nestopia também vai na imagem) | **padrão diferente** |
| Super Nintendo (`snes`) | snes9x (e snes9x2005_plus_a33 pelo `emuelec.conf`) | snes9x2010, snes9x2002, snes9x2005_plus, snes9x2005_plus_a33 | snes9x2010 (snes9x também vai na imagem) | **padrão diferente** |
| Master System (`mastersystem`) | gearsystem | genesis_plus_gx, picodrive | genesis_plus_gx | **padrão diferente**; gearsystem não está na imagem |
| Mega Drive (`megadrive`) | genesis_plus_gx | genesis_plus_gx_wide, picodrive | genesis_plus_gx | igual |
| Game Boy (`gb`) | gambatte | gearboy, sameboy, tgbdual, mgba, vbam, vba_next | gambatte | igual |
| Game Boy Color (`gbc`) | gambatte | gearboy, sameboy, tgbdual, mgba, vbam, vba_next | gambatte | igual |
| Game Boy Advance (`gba`) | mgba | gpsp, vbam, vba_next | gpsp | **padrão diferente**; mgba não está na imagem |
| Arcade (`arcade`) | FBNEOSA:FbneoSA (standalone) | AdvanceMame (standalone), mame2003_plus, mame2010, fbneo, fbalpha2012 | mame2003_plus no armv7 (fbneo no x86_64) | standalone na fábrica; comparar com fbneo libretro |
| PlayStation (`psx`) | pcsx_rearmed | pcsx_rearmed_rumble_32b, pcsx_rearmed_32b, swanstation | pcsx_rearmed | igual |

**O que avaliar primeiro** (P-24): os quatro sistemas com padrão diferente. No GBA, o
gpsp tem recompilador dinâmico ARM e costuma ser mais leve que o mgba no Cortex-A7, mas o
mgba é mais preciso. No SNES, o estudo de fábrica (`cores/snes9x2005_plus/`) mostrou o
`snes9x2005_plus` com `-O2` e LTO abaixo de 60% de um núcleo, o mais leve dos testados.

## 2. Todos os sistemas da fábrica

| Id | Sistema | Padrão | Alternativos |
|---|---|---|---|
| amiga | Commodore Amiga | AMIBERRY:AMIBERRY | puae, uae4arm_32b |
| amigacd32 | Commodore Amiga CD 32 | AMIBERRY:AMIBERRY | puae, uae4arm_32b |
| amstradcpc | Amstrad CPC | cap32 | |
| amstradgx4000 | Amstrad GX4000 | cap32 | |
| arcade | Arcade | FBNEOSA:FbneoSA | AdvanceMame:AdvanceMame, mame2003_plus, mame2010, fbneo, fbalpha2012 |
| fbn | Final Burn Neo | FBNEOSA:FbneoSA | fbneo, mame2003_plus, fbalpha2012 |
| cps1 | Capcom PlaySystem 1 | FBNEOSA:FbneoSA | AdvanceMame:AdvanceMame, mame2003_plus, mame2010, fbneo, fbalpha2012 |
| cps2 | Capcom PlaySystem 2 | FBNEOSA:FbneoSA | AdvanceMame:AdvanceMame, mame2003_plus, mame2010, fbneo, fbalpha2012 |
| cps3 | Capcom PlaySystem 3 | FBNEOSA:FbneoSA | AdvanceMame:AdvanceMame, mame2003_plus, mame2010, fbneo, fbalpha2012 |
| megaduck | MegaDuck | sameduck | |
| daphne | Daphne | HYPSEUS:HYPSEUS | daphne |
| mame | Arcade MAME | FBNEOSA:FbneoSA | AdvanceMame:AdvanceMame, mame2003_plus, mame2010, fbneo, fbalpha2012 |
| atomiswave | Atomiswave | flycastsa:flycastsa | flycast, flycast_32b |
| naomi | Sega Naomi | flycastsa:flycastsa | flycast_xtreme_32b, flycast32_rumble_32b |
| 3do | Panasonic 3DO | opera | |
| atari800 | Atari 800 | atari800 | |
| atari2600 | Atari 2600 | stella | STELLASA:STELLASA |
| atari5200 | Atari 5200 | a5200 | atari800 |
| atari7800 | Atari 7800 | prosystem | |
| atarist | Atari ST | hatari | HATARISA:HATARISA |
| atarijaguar | Atari Jaguar | virtualjaguar | |
| atarilynx | Atari Lynx | handy | mednafen_lynx |
| wonderswan | Bandai WonderSwan | mednafen_wswan | |
| wonderswancolor | Bandai WonderSwan Color | mednafen_wswan | |
| odyssey2 | Magnavox Odyssey 2 | o2em | |
| videopac | Philips VideoPac | o2em | |
| pcengine | NEC PC-Engine | mednafen_pce_fast | mednafen_supergrafx |
| pcenginecd | NEC PC-Engine CD | mednafen_pce_fast | mednafen_supergrafx |
| tg16 | NEC TurboGrafx 16 | mednafen_pce_fast | mednafen_supergrafx |
| tg16cd | NEC TurboGrafx 16-CD | mednafen_pce_fast | mednafen_supergrafx |
| supergrafx | NEC SuperGrafx | mednafen_supergrafx | mednafen_pce_fast |
| famicom | Nintendo Famicom | nestopia | fceumm, fceumm_mod |
| fds | Nintendo Famicom Disk System | nestopia | fceumm, fceumm_mod |
| sfc | Nintendo Super Famicom | snes9x | snes9x2010, snes9x2002, snes9x2005_plus |
| nes | Nintendo Entertainment System | nestopia | fceumm, fceumm_mod |
| nesh | NES Hacks | nestopia | fceumm, fceumm_mod |
| snes | Super Nintendo | snes9x | snes9x2010, snes9x2002, snes9x2005_plus, snes9x2005_plus_a33 |
| snesmsu1 | Super Nintendo MSU1 | snes9x | |
| snesh | Super Nintendo Hacks | snes9x | snes9x2010, snes9x2002, snes9x2005_plus |
| n64 | Nintendo 64 | mupen64plus_32b | mupen64plus_next, mupen64plus_next_alt, parallel_n64_32b, mupen64plussa:rice, mupen64plussa:glide64mk2 |
| virtualboy | Nintendo Virtual Boy | mednafen_vb | |
| gb | Nintendo Game Boy | gambatte | gearboy, sameboy, tgbdual, mgba, vbam, vba_next |
| gbc | Nintendo Game Boy Color | gambatte | gearboy, sameboy, tgbdual, mgba, vbam, vba_next |
| gba | Nintendo Game Boy Advance | mgba | gpsp, vbam, vba_next |
| gameandwatch | Nintendo Game and Watch | gw | |
| gbah | Game Boy Advance Hacks | mgba | gpsp, vbam, vba_next |
| gbch | Game Boy Color Hacks | gambatte | gearboy, sameboy, tgbdual, mgba, vbam, vba_next |
| gbh | Game Boy Hacks | gambatte | gearboy, sameboy, tgbdual, mgba, vbam, vba_next |
| wii | Nintendo Wii | dolphin:dolphin | |
| gamecube | Nintendo GameCube | dolphin:dolphin | |
| pokemini | Pokémon Mini | pokemini | |
| sg-1000 | Sega SG-1000 | gearsystem | genesis_plus_gx, picodrive |
| mastersystem | Sega Master System | gearsystem | genesis_plus_gx, picodrive |
| megadrive | Sega Mega Drive | genesis_plus_gx | genesis_plus_gx_wide, picodrive |
| megadrivemsu | Sega Mega Drive MSU | genesis_plus_gx_wide | genesis_plus_gx |
| genesis | Sega Genesis | genesis_plus_gx | genesis_plus_gx_wide, picodrive |
| segacd | Sega CD | genesis_plus_gx | picodrive |
| sega32x | Sega 32X | - | picodrive |
| saturn | Sega Saturn | yabasanshiro:yabasanshiroSA | yabasanshiro |
| dreamcast | Sega Dreamcast | flycastsa:flycastsa | flycast, flycast_32b |
| gamegear | Sega Game Gear | gearsystem | genesis_plus_gx, picodrive |
| ggh | Game Gear Hacks | gearsystem | genesis_plus_gx, picodrive |
| genh | Genesis Hacks | genesis_plus_gx | genesis_plus_gx_wide, picodrive |
| megadrive-japan | Sega Mega Drive Japan | genesis_plus_gx | genesis_plus_gx_wide, picodrive |
| sc-3000 | Sega SC-3000 | bluemsx | |
| neogeo | SNK Neo-Geo | FBNEOSA:FbneoSA | fbneo, mame2003_plus, fbalpha2012 |
| neocd | SNK Neo-Geo CD | neocd | fbneo |
| ngp | SNK Neo-Geo Pocket | mednafen_ngp | |
| ngpc | SNK Neo-Geo Pocket Color | mednafen_ngp | |
| openbor | OpenBOR | OPENBOR:OpenBOR | OPENBOR:OpenBORff |
| psx | Sony PlayStation | pcsx_rearmed | pcsx_rearmed_rumble_32b, pcsx_rearmed_32b, swanstation |
| psp | Sony PSP | PPSSPPSDL:PPSSPPSDL | ppsspp |
| pspminis | Sony PSP Minis | PPSSPPSDL:PPSSPPSDL | ppsspp |
| intellivision | Mattel Intellivision | freeintv | jzintv:jzintv |
| colecovision | ColecoVision | bluemsx | gearcoleco |
| tic-80 | TIC-80 | tic80 | |
| vectrex | Vectrex | vecx | |
| msx | MSX | bluemsx | fmsx |
| msx2 | MSX2 | bluemsx | fmsx |
| zx81 | Sinclair ZX81 | 81 | |
| zxspectrum | Sinclair ZX Spectrum | fuse | |
| x1 | Sharp X1 | x1 | |
| x68000 | Sharp X68000 | px68k | |
| c16 | Commodore Plus/4 | vice_xplus4 | |
| c64 | Commodore 64 | vice_x64 | vice_x64sc |
| c128 | Commodore 128 | vice_x128 | |
| vic20 | Commodore VIC-20 | vice_xvic | |
| pc-9800 | NEC PC-9800 | np2kai | nekop2 |
| pcfx | NEC PC-FX | mednafen_pcfx | |
| pc | DOS x86 | dosbox_pure | DOSBOXSDL2:DOSBOXSDL2, dosbox_svn |
| supervision | Watara Supervision | potator | |
| prboom | Doom | Chocolate-Doom:Chocolate-Doom | prboom, LZDoom:LZDoom |
| ecwolf | Wolfenstein 3D | ECWolf:ecwolf | |
| pico8 | PICO-8 | Pico-8:Pico-8 | fake08 |
| solarus | Solarus | Solarus:solarus | |
| ports | Ports | ports:ports | |
| uzebox | Uzebox | - | uzem |
| fmtmarty | FM Towns | multiemu | |
| pgm2 | PolyGame Master 2 | multiemu | |
| mplayer | Media Player | - | mpv:mpv, ffplay:ffplay |
| phillips-cdi | Philips CD-i | same_cdi | |
| freej2me | Java Games | freej2me | |
| gmloader | GameMaker Loader | gmloader:gmloader | |
| karaoke | Karaoke | pocketcdg | |

O EmuELEC lista sistemas que não rodam bem no A33 (Wii, GameCube, Dreamcast, Saturn, PSP,
Nintendo 64 e outros): a lista é a mesma para todos os aparelhos e não indica que o GA36
dê conta. Constar aqui não é critério para entrar no nosso catálogo (ver os critérios do
P-24).

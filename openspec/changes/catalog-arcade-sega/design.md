# Design

## Context

Ver `proposal.md` (Why). Estado de partida:

- O catálogo (`rootfs/overlay/usr/share/r36os/systems.json`, esquema 1, `docs/CATALOG.md`)
  é a fonte única das pastas de `roms/`, das listas de jogos (`r36os-playlists`), das pastas
  criadas pelo `flash` e pelo primeiro boot e do `LEIA-ME.txt`. Sistema novo no catálogo já
  ganha pasta e lista sem código novo.
- O core padrão vem de `core_by_arch[arch]` ou `core`; `alt_cores` só lista cores
  instalados para o usuário escolher no menu do RetroArch (que oferece qualquer core com
  `.info` que aceite a extensão; o `libretro-core-info` do Alpine traz os `.info` dos
  `fbalpha2012_*`).
- O arcade hoje: `fbneo` (x86_64, aarch64) e `mame2003_plus` (armv7), o que viola a regra
  do cartão único (P-26: o arcade do GA36 não funciona com os romsets do usuário).
- Medido nos fontes dos cores (2026-11-11): os três `fbalpha2012_*` do libretro são o FB
  Alpha **v0.2.97.29** (set/2013), compilam com `make` (`makefile.libretro`, plataforma
  `unix`, saída `<core>_libretro.so`) e procuram os zips, inclusive o `neogeo.zip`, **na
  pasta do jogo** (`g_rom_dir`), não em `bios/`. A licença do FB Alpha proíbe venda e
  pedido de doações e exige o texto da licença junto com o binário.

## Goals / Non-Goals

**Goals:**

- Sistemas novos só por dados (catálogo) e três aports, sem código novo de pastas ou
  listas.
- A regra "mesmo core de arcade nos dois consoles" verificada pelo validador do catálogo,
  não só por convenção.

**Non-Goals:**

- Flags por CPU nos cores novos (P-10) e cross-compile (P-36).
- Remover o aport do `mame2003_plus` (fica desativado para voltar quando o usuário quiser).
- Converter romsets ou checar romsets do usuário.

## Decisions

### D1. Campo `romset` no catálogo (esquema 2)

Cada sistema ganha o campo obrigatório `romset`: `null` nos sistemas comuns e um texto
(o romset que o core padrão aceita) nos sistemas de arcade. O validador recusa um sistema
com `romset` e `core_by_arch` não vazio (regra do cartão único), e o `LEIA-ME` imprime o
`romset` de cada pasta de arcade. O esquema sobe para 2 (`docs/CATALOG.md`), porque o
campo é obrigatório e o validador exige o conjunto exato de campos.

- *Alternativa descartada:* uma lista fixa de ids de arcade no código. Esconderia a regra
  do catálogo, que é a fonte única para qualquer frontend futuro.

### D2. Os sistemas novos

| id | name | extensões | core padrão | `core_by_arch` | `alt_cores` | BIOS | `romset` |
|---|---|---|---|---|---|---|---|
| `segacd` | Sega CD | `cue`, `chd`, `iso`, `m3u` | `genesis_plus_gx` | `armv7`: `picodrive` | `picodrive` | `bios_CD_U.bin`, `bios_CD_E.bin`, `bios_CD_J.bin` (obrigatória) | `null` |
| `sega32x` | Sega 32X | `32x`, `zip`, `7z` | `picodrive` | | | | `null` |
| `cps1` | CPS-1 | `zip` | `fbalpha2012_cps1` | | `fbneo` | | FB Alpha v0.2.97.29 |
| `cps2` | CPS-2 | `zip` | `fbalpha2012_cps2` | | `fbneo` | | FB Alpha v0.2.97.29 |
| `neogeo` | Neo Geo | `zip` | `fbalpha2012_neogeo` | | `fbneo` | `neogeo.zip` na própria `roms/neogeo/` | FB Alpha v0.2.97.29 |
| `arcade` | Arcade | `zip`, `7z` | `fbneo` | | | | FBNeo (versão do core da imagem) |

Ordem no catálogo (e no menu): as pastas de Sega ficam junto do Mega Drive e as de arcade
junto do arcade. A BIOS do Neo Geo é descrita no campo `bios` com a nota de que vai na
pasta dos jogos.

### D3. Três aports `libretro-fbalpha2012-*`

Um aport por core (`cps1`, `cps2`, `neogeo`), no modelo do `libretro-fbneo`: tarball do
GitHub do libretro num commit fixo, `make`, `install` do `.so` em `/usr/lib/libretro/` e do
`src/license.txt` em `/usr/share/licenses/<pkg>/` (exigência da licença), `arch="all"`,
`license="custom"`. Entram em `rootfs/packages.txt` (os três alvos). O
`libretro-mame2003-plus` fica com `arch=""` e sai da lista.

### D4. Arcade sem `core_by_arch`

O arcade passa a usar o `fbneo` em todas as arquiteturas, sem alternativo. É o caminho (2)
do P-26 e a regra D1.

## Risks / Trade-offs

- **[FB Alpha 2012 mais lento ou com menos jogos que o esperado no GA36]** → Medir contra o
  `fbneo` (método do P-24); o `fbneo` fica como alternativo em cada pasta e a decisão volta
  ao usuário se o FB Alpha não ganhar.
- **[Romsets do usuário não batem]** → O `LEIA-ME` diz o romset de cada pasta; o log do
  frontend já registra os arquivos que faltam (como no P-26).
- **[Cartões com jogos de MAME 2003-Plus em `roms/arcade/`]** → Deixam de abrir no GA36
  (BREAKING, na proposta); os arquivos ficam no cartão.
- **[Licença "não comercial"]** → O projeto é distribuído de graça, sem doações; o texto
  da licença vai no pacote e a restrição fica no README.
- **[Build mais longo]** → Três cores a mais por arquitetura, uma vez (cache do repositório
  local; P-36 acelera depois).

## Migration Plan

Cartões existentes ganham as pastas novas no primeiro boot (o contrato de pastas já
recria o que falta). Nada é movido nem apagado. Voltar atrás: gravar com `--update` uma
build anterior; as pastas novas ficam vazias no cartão.

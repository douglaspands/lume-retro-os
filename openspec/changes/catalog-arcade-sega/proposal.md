# Proposal

## Why

O usuário quer escolher o emulador por sistema e ter pastas próprias para os sistemas de
arcade e de Sega que hoje não existem no catálogo (P-35 em `docs/PENDENCIAS.md`, decidida
em 2026-11-11). Com o cartão único da change `r36s-single-card`, a mesma `ROMS` é usada no
GA36 (A33, armv7, fraco) e no R36S (RK3326, aarch64): numa pasta de arcade o core padrão
tem de ser o mesmo nos dois consoles, porque um romset de arcade só funciona no core da
versão dele. Hoje o arcade usa o `mame2003_plus` no armv7 e o `fbneo` nos outros, o que
quebra essa regra, e o arcade do GA36 não funciona com os romsets do usuário (P-26).

## What Changes

- **Pastas novas em `roms/`**, cada uma com a sua lista de jogos: `neogeo`, `cps1`,
  `cps2`, `segacd` e `sega32x` (o nome da pasta de 32X do firmware de fábrica do GA36). A
  pasta do Mega Drive continua `megadrive`.
- **FB Alpha 2012 recortado por placa** como core padrão de CPS-1, CPS-2 e Neo Geo:
  `fbalpha2012_cps1`, `fbalpha2012_cps2` e `fbalpha2012_neogeo`, mais leves que o FBNeo
  atual em aparelho simples. O **`fbneo` é o único alternativo** dessas três pastas.
- **Arcade com o `fbneo` nos dois consoles** (sai o padrão do armv7).
- **Sega CD** com `genesis_plus_gx` no R36S e na VM e `picodrive` no GA36 (o outro como
  alternativo); **32X** com o `picodrive`.
- **Regra do cartão único:** nas pastas de arcade (arcade, CPS-1, CPS-2, Neo Geo) o core
  padrão é o mesmo em todas as arquiteturas; o catálogo e os testes recusam exceção.
- **BREAKING (catálogo):** o `mame2003_plus` sai do catálogo e da imagem; o aport fica no
  repositório desativado (`arch=""`), como o `libretro-ppsspp`. Quem tinha romsets do MAME
  2003-Plus no arcade precisa de romsets do FBNeo.
- **`LEIA-ME.txt`** diz o romset de cada pasta de arcade e as BIOS (`neogeo.zip` para o
  Neo Geo, BIOS do Sega CD por região).
- Três pacotes locais novos (`aports/libretro-fbalpha2012-cps1`, `-cps2`, `-neogeo`) para
  armv7, aarch64 e x86_64 (a VM testa o catálogo). A licença "não comercial" do FB Alpha
  fica registrada.

Fora do escopo: os outros candidatos do P-24 (Game Gear, PC Engine etc.), a otimização
por CPU (P-10) e o cross-compile (P-36).

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `game-library`: pastas novas em `roms/`; sistemas e cores incluídos (Neo Geo, CPS-1,
  CPS-2, Sega CD, 32X; sem o `mame2003_plus`); o core padrão por arquitetura deixa de valer
  para as pastas de arcade (mesmo core nos dois consoles do cartão único); o `LEIA-ME`
  explica o romset de cada pasta de arcade.

## Impact

- **Catálogo e imagem:** `rootfs/overlay/usr/share/r36os/systems.json`,
  `rootfs/packages.txt`, `aports/` (três pacotes novos, `libretro-mame2003-plus`
  desativado).
- **Código:** `src/r36os/leiame.py`, `src/r36os/catalog.py` (validação da regra das pastas
  de arcade); as pastas e listas de jogos já saem do catálogo (`flash`, initramfs,
  `r36os-playlists`), sem código novo.
- **Testes:** `tests/unit/test_catalog.py`, `test_leiame.py`, `test_aports.py`,
  `test_manifest_parity.py`, `tests/playlists/test_playlists.sh`,
  `tests/integration/test_local_repo.py`.
- **Usuário:** pastas novas no cartão (criadas no boot sem apagar nada); romsets de arcade
  do FBNeo e, nas pastas CPS e Neo Geo, do FB Alpha 2012.
- **Aparelho:** medir o `fbalpha2012_*` contra o `fbneo` nos dois consoles (método do
  P-24); se o FB Alpha 2012 não ganhar no GA36, rever o padrão com o usuário.

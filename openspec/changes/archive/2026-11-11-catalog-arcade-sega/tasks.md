# Tasks

> **Para um agente que começa sem contexto:**
> - Esta change mora na worktree `out/worktrees/catalog` (branch `feature/catalog-arcade-sega`,
>   rebaseado sobre o `feature/r36s-single-card`). Trabalhe e faça commit só aqui.
> - **Testes nesta worktree:** o `.venv` existe só no repositório principal, e o `r36os`
>   instalado nele aponta para o código de lá. Rode com
>   `PYTHONPATH=src /home/douglas/Workspace/r36s/r36s_all/.venv/bin/python -m pytest tests/unit`
>   (sem o `PYTHONPATH=src` os testes leem os arquivos do repositório principal).
> - **Nunca compile em paralelo:** `r36os pkg` e `r36os build` usam o mesmo repositório
>   local de pacotes (`out/repo/`) e os núcleos do PC. Antes do grupo 2.2, confira com
>   `podman ps` que não há build rodando (a `r36s-single-card` gera a imagem `console`).
> - Já feito na base (change `r36s-single-card`, 2026-11-11): o `mame2003_plus` e o
>   `snes9x` saíram do catálogo e da imagem (aports com `arch=""`), e o arcade usa o
>   `fbneo` em todos os consoles.

## 1. Catálogo (sem build)

- [x] 1.1 Esquema 2 do catálogo (D1): campo obrigatório `romset` em todos os sistemas; o validador recusa `romset` com `core_by_arch` não vazio; `docs/CATALOG.md` atualizado. Verificação: `tests/unit/test_catalog.py` com o erro novo (core de arcade por arquitetura) e o catálogo válido.
- [x] 1.2 Sistemas novos (D2): `segacd`, `sega32x`, `cps1`, `cps2`, `neogeo` no `systems.json`; cores `fbalpha2012_*` em `cores` (o arcade já está só com `fbneo` e sem `mame2003_plus`, D4, feito na base). Verificação: `test_catalog.py` confere a tabela do D2 (ids na ordem, core padrão por arquitetura, alternativos, BIOS e romset).
- [x] 1.3 `LEIA-ME.txt`: o romset de cada pasta de arcade, o alternativo `fbneo` com outro romset, o `neogeo.zip` na pasta `roms/neogeo/` e a BIOS do Sega CD em `bios/`. Verificação: `tests/unit/test_leiame.py` cobre as pastas novas.
- [x] 1.4 Listas de jogos e pastas: os sistemas novos geram pasta e lista. Verificação: `tests/playlists/test_playlists.sh` e `tests/unit/test_flash.py` (`populate_roms`) com as pastas novas; o teste de pastas do initramfs segue o catálogo.

## 2. Pacotes

- [x] 2.1 Aports `libretro-fbalpha2012-cps1`, `-cps2` e `-neogeo` (D3), com o `license.txt` instalado em `/usr/share/licenses/`; `rootfs/packages.txt` atualizado (o `libretro-mame2003-plus` já está com `arch=""`, feito na base). Verificação: `tests/unit/test_aports.py` (arch, checksums, licença no `package()`) e `test_catalog.py::test_every_core_has_package_in_common_list`.
- [x] 2.2 Compilar os três cores nas três arquiteturas (`r36os pkg <camada> <aport>`; **um build de cada vez**: só começar com `podman ps` vazio, nunca junto do build da imagem `console` da `r36s-single-card`, porque os dois usam `out/repo/` e o `aports/<nome>/src`). Verificação: `tests/integration/test_local_repo.py` acha os cores do catálogo em `out/repo/<arch>/`.
- [x] 2.3 README: os cores FB Alpha 2012 nos Agradecimentos e a restrição da licença (sem venda, sem doações) na seção Licença. Verificação: teste de documentação confere a menção.

## 3. Imagem e VM

- [x] 3.1 Build `vm` e `test-vm`: os cores novos carregam na VM (`tests/integration/test_cores_load.py`) e as listas aparecem com ROMs de teste geradas pelo build quando houver (homebrew livre). Verificação: `test-vm` passa. **Resultado (2026-11-11, na branch `feature/r36s-single-card`, que recebeu esta change por merge):** build `vm` `20261111-232550`; `test-vm` 67/67, com os `core-loaded-*` dos 9 cores que têm ROM de teste; os `fbalpha2012_*` não têm romset livre (`NO_TEST_ROM`), então ficam só com o teste de carga sem conteúdo, `test_cores_load.py` com 8 PASS (os três `fbalpha2012_*` incluídos). Validado com ROMs de teste do usuário (CPS-1, CPS-2, Neo Geo no core padrão e no `fbneo`, e a BIOS do Sega CD), com os pacotes x86_64 da VM, sem tela.
- [x] 3.2 Build `console`: paridade de manifestos `vm` × `ga36` × `r36s` com os cores novos e sem o `mame2003_plus`. Verificação: `tests/unit/test_manifest_parity.py`. **Resultado (2026-11-11):** build `console` `20261111-233324` (GA36 e R36S, `BOOT` de 2 GiB com 1,41 GiB livres); `tests/unit` 335 passed, paridade incluída; `test_image_console.py` e as suítes de shell passam.

## 4. Aparelho

> **4.1 e 4.2 movidas para o P-39** (`docs/PENDENCIAS.md`) no arquivamento, porque dependem dos aparelhos. Os `fbalpha2012_*` ficam só com teste de carga (`NO_TEST_ROM`).

- [ ] 4.1 Nos dois consoles, um jogo de CPS-1, CPS-2, Neo Geo, Sega CD, 32X e arcade abre e roda 5 minutos. Verificação: `events.log` sem `game FAIL`, métricas do `logd`. → P-39.
- [ ] 4.2 Medir `fbalpha2012_*` contra `fbneo` (mesma ROM, 5 minutos, FPS, CPU por núcleo e temperatura) no GA36 e no R36S; registrar no `docs/CATALOG.md`. Se o FB Alpha 2012 não ganhar no GA36, rever o padrão com o usuário. → P-39.

## Workflow follow-up

- Por decisão do usuário (2026-11-11), a implementação entrou na `r36s-single-card` por merge do branch `feature/catalog-arcade-sega`, e esta change é arquivada antes dela.
- Feito no arquivamento: P-35 em "Concluídas" no `docs/PENDENCIAS.md`, P-26 atualizado e P-39 criado para 4.1 e 4.2.
- O merge na `main` é por PR com squash, só quando o usuário pedir.

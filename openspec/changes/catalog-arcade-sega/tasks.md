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
- [ ] 2.2 Compilar os três cores nas três arquiteturas (`r36os pkg <camada> <aport>`; **um build de cada vez**: só começar com `podman ps` vazio, nunca junto do build da imagem `console` da `r36s-single-card`, porque os dois usam `out/repo/` e o `aports/<nome>/src`). Verificação: `tests/integration/test_local_repo.py` acha os cores do catálogo em `out/repo/<arch>/`.
- [x] 2.3 README: os cores FB Alpha 2012 nos Agradecimentos e a restrição da licença (sem venda, sem doações) na seção Licença. Verificação: teste de documentação confere a menção.

## 3. Imagem e VM

- [ ] 3.1 Build `vm` e `test-vm`: os cores novos carregam na VM (`tests/integration/test_cores_load.py`) e as listas aparecem com ROMs de teste geradas pelo build quando houver (homebrew livre). Verificação: `test-vm` passa.
- [ ] 3.2 Build `console`: paridade de manifestos `vm` × `ga36` × `r36s` com os cores novos e sem o `mame2003_plus`. Verificação: `tests/unit/test_manifest_parity.py`.

## 4. Aparelho

- [ ] 4.1 Nos dois consoles, um jogo de CPS-1, CPS-2, Neo Geo, Sega CD, 32X e arcade abre e roda 5 minutos. Verificação: `events.log` sem `game FAIL`, métricas do `logd`.
- [ ] 4.2 Medir `fbalpha2012_*` contra `fbneo` (mesma ROM, 5 minutos, FPS, CPU por núcleo e temperatura) no GA36 e no R36S; registrar no `docs/CATALOG.md`. Se o FB Alpha 2012 não ganhar no GA36, rever o padrão com o usuário.

## Workflow follow-up

- Começa depois do arquivamento da `r36s-single-card` (branch `feature/catalog-arcade-sega`, criado a partir do `feature/r36s-single-card`).
- Ao concluir, mover o P-35 para "Concluídas" no `docs/PENDENCIAS.md` e atualizar o P-26.
- O merge na `main` é por PR com squash, só quando o usuário pedir.

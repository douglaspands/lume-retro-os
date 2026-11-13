# Proposal

## Why

O cache do build (fontes do kernel e do U-Boot, árvores de build, ccache, distfiles, chaves
do abuild, áreas de fábrica e disco da VM, cerca de 17 GB) fica fora do projeto, em
`~/.cache/r36os`. Nesta máquina, esse caminho é um symlink para `~/data/r36os`, criado à mão
para ficar num diretório Btrfs No-COW. Quem chega ao projeto não sabe onde está o cache, nem
que ele precisa de No-COW, nem que existe um symlink: nada disso está no repositório. É o
primeiro passo para o projeto ficar simples de entender sem ajuda de IA. A organização e a
documentação do repositório como um todo ficam para uma change separada.

## What Changes

- **BREAKING**: o cache padrão passa a ser `.cache/` na raiz do projeto, ignorado pelo git.
  `$R36OS_CACHE` continua valendo para quem quiser outro lugar. `$XDG_CACHE_HOME/r36os` e
  `~/.cache/r36os` deixam de ser usados, e a trava que hoje recusa um cache dentro do
  repositório sai.
- Ao criar o `.cache/`, o build tenta marcá-lo como No-COW (`chattr +C`). Num sistema de
  arquivos sem suporte, como ext4 ou xfs, ele avisa numa linha e segue.
- Uma git worktree (por exemplo, `out/worktrees/<nome>`) usa o `.cache/` do repositório
  principal, sem criar outro vazio. Sem isso, cada worktree recompilaria o kernel do zero.
- Migração manual e documentada no README, sem comando novo: os dados de `~/data/r36os` vão
  fisicamente para `.cache/` (não basta um symlink para lá), e o symlink `~/.cache/r36os` e
  a pasta antiga são removidos. Antes de mover, as árvores de kernel de conjuntos de patches
  antigos são limpas com `r36os clean`.
- A documentação (`README.md`, `docs/VM.md`, `aports/README.md`, a skill `repo-clean`), os
  testes e a configuração do ctx e do guardrail (`policy.toml`) passam a citar `.cache/`.
- O README avisa que `git clean -fdx` apaga o `.cache/`, incluindo as chaves do abuild.

## Capabilities

### New Capabilities
- `build-cache`: onde o build guarda o que baixa e o que compila entre execuções (local
  padrão, variável de ambiente, No-COW, uso por worktrees e o que o git ignora).

### Modified Capabilities

(nenhuma: nenhum spec atual fala do cache)

## Impact

- **Código:** `src/r36os/paths.py` (`cache_dir()`: novo padrão, localização do repositório
  principal, No-COW) e `src/r36os/clean.py` (não descer em `.cache/` ao procurar caches do
  Python). Os demais módulos já usam `cache_dir()` e não mudam.
- **Testes:** `tests/unit/test_targets.py` (os dois testes do cache fora do repositório
  invertem), `tests/unit/test_console_boot.py` (caminho fixo `~/.cache/r36os`) e
  `tests/unit/test_guardrail_readonly_paths.py` (usa `~/data/r36os` como exemplo).
- **Configuração:** `.gitignore` (`/.cache/`) e `policy.toml` (globs do `[index.reference]`
  e `readonly_system`).
- **Docs:** `README.md`, `docs/VM.md`, `aports/README.md` e a skill `repo-clean` (em
  `.claude/skills/` e `.agents/skills/`).
- **Máquina do desenvolvedor:** uma migração única, de `~/data/r36os` para `.cache/`. No
  mesmo Btrfs é só uma troca de nome, sem copiar dados.
- Sem efeito nas imagens geradas nem nos aparelhos.

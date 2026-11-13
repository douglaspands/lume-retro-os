# Design

## Context

- `src/r36os/paths.py` resolve o cache na ordem `$R36OS_CACHE`, `$XDG_CACHE_HOME/r36os`,
  `~/.cache/r36os` e **recusa** um caminho dentro do repositório (decisão da task 1.2 da
  change `alpine-retroarch-distro`, coberta por `tests/unit/test_targets.py`). Essa trava
  existia para o cache não poluir o git, o índice e as buscas, e o `.gitignore` resolve isso
  agora.
- Os módulos do build pedem pastas do cache só por `cache_dir()` e criam diretórios só pelo
  `ensure_dir()` (`kernel.py`, `uboot.py`, `packages.py`, `vendor.py`, `r36s_vendor.py`,
  `vm.py`, `flash.py`, `testdata.py`). Por isso a mudança fica concentrada em `paths.py`.
- `cache_dir()` não cria nada: `test_cli_invalid_target_creates_nothing` confirma que um alvo
  inválido não cria o cache.
- Nesta máquina, `~/.cache/r36os` é um symlink para `~/data/r36os` (17 GB, já No-COW).
  `~/data` e o projeto estão no mesmo subvolume Btrfs do `/home` (o inode de `~/data` não é
  256, o da raiz de um subvolume), então mover de um para o outro só troca nomes.
- As worktrees de trabalho paralelo ficam em `out/worktrees/<nome>`, e `REPO_ROOT` é calculado
  a partir de `__file__`. Numa worktree, `REPO_ROOT` aponta para a própria worktree.
- `src/r36os/clean.py` percorre o repositório procurando `__pycache__` e `.pytest_cache`, e só
  pula `.git`, `.venv`, `.ctx`, `out`, `var` e `node_modules`.

## Goals / Non-Goals

**Goals:**
- Cache visível e explicado dentro do projeto, sem symlink nem configuração da máquina.
- Nenhum módulo do build muda além de `paths.py` e `clean.py`.
- Worktrees continuam aproveitando o kernel e o ccache já compilados.

**Non-Goals:**
- Comando de migração: a migração é feita uma vez, à mão, seguindo o README.
- Reorganizar o repositório ou reescrever a documentação geral (change separada).
- Mudar a estrutura interna do cache (`src/`, `kbuild/`, `ccache/` etc. ficam como estão).

## Decisions

### D1. Padrão `<repo principal>/.cache`, só com `$R36OS_CACHE` como alternativa

A ordem passa a ser `$R36OS_CACHE`, depois `<repositório principal>/.cache`.
`$XDG_CACHE_HOME` sai: ele empurra o cache para fora do projeto sem que ninguém perceba, que
é justamente o problema a resolver. A trava contra um cache dentro do repositório também sai.

- *Alternativa:* manter o XDG como segunda opção. Descartada porque mantém dois lugares
  possíveis, e quem lê o código precisa saber qual vale.

### D2. Repositório principal pelo `git rev-parse --git-common-dir`

`cache_dir()` chama `git -C <REPO_ROOT> rev-parse --path-format=absolute --git-common-dir`
uma vez (resultado guardado em memória). O pai desse diretório é a raiz do repositório
principal: numa worktree, o comando devolve o `.git` do repositório principal. Se o `git`
falhar ou não existir (por exemplo, num projeto extraído de um arquivo compactado), o padrão
é `REPO_ROOT / ".cache"`.

- *Alternativa:* subir os diretórios procurando `out/worktrees`. Descartada porque depende de
  onde a worktree foi criada.
- *Alternativa:* exigir `R36OS_CACHE` em cada worktree. Descartada porque é fácil esquecer, e
  esquecer custa recompilar 13 GB de kernel.

### D3. No-COW aplicado pelo `ensure_dir()`, só na criação

`cache_dir()` continua sem criar nada. `ensure_dir(path)` passa a verificar se `path` está
dentro do cache e se a raiz do cache ainda não existe. Nesse caso, ela cria a raiz primeiro e
roda `chattr +C` nela, antes de criar o resto. Se o `chattr` falhar ou não existir, aparece
um aviso de uma linha no stderr (`warning: could not set No-COW on <dir>: ...`) e o build
segue. Uma raiz que já existe nunca é alterada.

- *Por que na criação:* o atributo `C` de um diretório só vale para arquivos criados depois,
  então aplicá-lo num cache cheio não muda nada nos dados que já existem.
- *Alternativa:* `ioctl(FS_IOC_SETFLAGS)` direto do Python. Descartada porque fica mais
  obscuro para quem lê, e o `chattr` (e2fsprogs) existe em qualquer distro.
- *Alternativa:* criar o `.cache/` com `chattr` no README e deixar o build sem isso.
  Descartada porque quem não ler o README perde o No-COW.

### D4. `clean.py` pula `.cache`

`.cache` entra em `SKIP_DIRS`. Sem isso, a busca por caches do Python percorreria os
milhões de arquivos do `kbuild/`. O que o `clean` remove dentro do cache (`kbuild` antigo e
`flash`) continua vindo de `cache_dir()`, como hoje.

### D5. Chaves do abuild continuam no cache

`.cache/abuild/` continua guardando a chave de assinatura. Separar as chaves criaria mais um
lugar para explicar. O risco do `git clean -fdx` fica documentado no README. Perder a chave
custa gerar outra e reassinar `out/repo` com uma recompilação dos pacotes.

### D6. Configuração do ctx e do guardrail

- `[index.reference]` do `policy.toml`: os globs `~/.cache/r36os/src/linux-6.18.62-*/...`
  passam a `.cache/src/linux-6.18.62-*/...` (relativos à raiz do projeto). Isso precisa ser
  conferido, porque o índice do ctx exclui diretórios de cache por padrão e pode descartar
  globs que passam por `.cache`.
- `readonly_system`: as entradas `~/data/r36os/src` e `~/data/r36os/kbuild` saem, porque a
  leitura dentro do workspace já é liberada. O teste `test_guardrail_readonly_paths.py`
  continua cobrindo `/run/media` e a regra de que qualquer outro acesso a `~/data` pergunta,
  com exemplos que não citam o cache.

## Risks / Trade-offs

- [`git clean -fdx` apaga o cache inteiro, incluindo as chaves do abuild] → aviso no README,
  ao lado da explicação do `.cache/`. O que se perde é refeito por um build, só mais lento.
- [IDEs, `tree`, `du` e `find` sem filtro passam a ver o `.cache/`] → os comandos usados no
  projeto (`rg`, `fd`, ctx, receita `tree_compact`) já respeitam o `.gitignore` ou o excluem.
  A seção de cache do README menciona excluí-lo do file watcher da IDE.
- [`mv` entre subvolumes vira cópia de 17 GB] → o passo de migração confere antes, com
  `stat`, que origem e destino estão no mesmo sistema de arquivos. A limpeza de `kbuild`
  antes do `mv` reduz o volume, caso precise copiar.
- [Arquivos de sub-UID do podman dentro do cache] → o `mv` move só as pastas de primeiro
  nível, que são do usuário. Trocar o nome de uma pasta não exige permissão sobre o
  conteúdo dela.
- [Quem tem `R36OS_CACHE` ou `XDG_CACHE_HOME` exportados] → `R36OS_CACHE` continua valendo.
  Quem dependia do XDG lê a migração no README.

## Migration Plan

Feita uma vez, com nenhum build rodando (`podman ps` vazio):

1. `uv run r36os clean` (conferir a lista) e `uv run r36os clean --yes`: remove as árvores
   `kbuild/<placa>-<digest>` de conjuntos de patches antigos.
2. `stat -c %d ~/data/r36os .`: o mesmo número de dispositivo confirma que o `mv` é só uma
   troca de nome.
3. `mkdir .cache` e `chattr +C .cache`.
4. Mover cada pasta de primeiro nível de `~/data/r36os/` para `.cache/` (`mv`, uma por
   chamada).
5. Remover o symlink `~/.cache/r36os` e a pasta vazia `~/data/r36os` (`rmdir`, que falha se
   sobrar algo).
6. Conferir: `uv run r36os build vm` reaproveita o ccache e as fontes (sem novo download do
   kernel), e `lsattr -d .cache` mostra `C`.

**Rollback:** mover as pastas de volta para `~/data/r36os`, recriar o symlink e voltar ao
commit anterior (ou exportar `R36OS_CACHE=~/data/r36os`).

**Resultado da migração nesta máquina (2026-11-13):**

- `r36os clean --yes` (com `R36OS_CACHE=~/data/r36os`): 18 itens, 13,9 GiB liberados;
  nenhuma árvore `kbuild/` era do digest atual, e o cache ficou com 4,3 GB.
- `stat`: o mesmo dispositivo (56) para `~/data/r36os` e o projeto; os `mv` foram só trocas de
  nome. `lsattr -d .cache` mostra `C`; `du -sh .cache` dá os mesmos 4,3 GB.
- Symlink `~/.cache/r36os` e pasta `~/data/r36os` removidos.
- `ctx index` + `ctx search "st7703" --scope reference` acham `panel-sitronix-st7703.c` em
  `.cache/src/` (o ctx não descartou o caminho; nenhum M-NN necessário).
- `uv run r36os build vm`: usou `.cache/abuild`, `.cache/distfiles` e `.cache/ccache/x86_64`
  (assinatura do repositório com as chaves migradas). A VM usa o kernel empacotado do Alpine
  (`linux-virt`), então não há `linux-*.tar.xz` a baixar; o reaproveitamento da árvore do
  kernel só é exercido por um `build console`, que desta vez recompila o kernel (`kbuild/`
  vazio depois da limpeza).
- `uv run r36os test-vm`: **67/67 checks ok em 323 s**; `git status` sem nada em `.cache/`.

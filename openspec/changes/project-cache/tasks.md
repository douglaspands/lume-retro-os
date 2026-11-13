# Tasks

## 1. Resolução do cache (`paths.py`)

- [x] 1.1 Em `src/r36os/paths.py`, `cache_dir()` passa a resolver `$R36OS_CACHE` e, sem ela, `<repositório principal>/.cache` (D1, D2): repositório principal pelo `git rev-parse --path-format=absolute --git-common-dir` (resultado guardado em memória), com `REPO_ROOT / ".cache"` quando o git falhar; saem o `$XDG_CACHE_HOME`, o `~/.cache/r36os` e a trava contra o cache dentro do repositório; docstring do módulo e da função em inglês explicando a ordem. Verificação: em `tests/unit/test_targets.py`, `test_cache_outside_repo` e `test_default_cache_is_xdg` substituídos por testes do padrão `<repo>/.cache`, de `$R36OS_CACHE` dentro do repositório aceito e de `XDG_CACHE_HOME` ignorado; `uv run pytest tests/unit/test_targets.py` passa.
- [x] 1.2 Teste da worktree: um repositório git temporário com `git worktree add` faz `cache_dir()` (com `REPO_ROOT` apontando para a worktree via monkeypatch) devolver o `.cache` do principal; uma pasta sem `.git` devolve o próprio `.cache`. Verificação: os dois testes passam com `uv run pytest tests/unit/test_targets.py`.
- [x] 1.3 `ensure_dir()` cria a raiz do cache e aplica `chattr +C` quando o caminho pedido está dentro do cache e a raiz ainda não existe (D3); falha do `chattr` (ausente ou sem suporte) vira um aviso de uma linha no stderr; uma raiz existente não é tocada. Verificação: testes com `chattr` simulado (sucesso, falha e raiz existente) passam; `test_cli_invalid_target_creates_nothing` continua passando (`cache_dir()` não cria nada).
- [x] 1.4 `tests/unit/test_console_boot.py:69` deixa o caminho fixo `~/.cache/r36os/vendor/...` e usa `cache_dir() / "vendor/ga36-factory-128M.bin"`. Verificação: `uv run pytest tests/unit/test_console_boot.py` passa (ou pula, sem a área de fábrica, pelo mesmo motivo de antes).

## 2. Limpeza (`clean.py`)

- [x] 2.1 `.cache` entra em `SKIP_DIRS` de `src/r36os/clean.py` (D4), e o docstring do módulo passa a citar `.cache/` onde fala do cache. Verificação: teste que monta um `.cache/x/__pycache__` num repositório temporário e confere que o `plan()` não o lista; `uv run pytest tests/unit -k clean` passa.

## 3. Git, ctx e guardrail

- [x] 3.1 `.gitignore`: `/.cache/` com um comentário em inglês (cache do build, No-COW, apagado pelo `git clean -fdx`); sai o comentário "o cache fica fora do repositório". Verificação: `git check-ignore -v .cache/x` aponta a regra nova.
- [x] 3.2 `policy.toml`: globs do `[index.reference]` passam a `.cache/src/linux-6.18.62-*/...` e o comentário acima deles é atualizado; `~/data/r36os/src` e `~/data/r36os/kbuild` saem de `readonly_system` (D6). Verificação: depois da migração (5.x), `.venv/bin/ctx index` e `.venv/bin/ctx search "st7703" --scope reference` acham `panel-sitronix-st7703.c` dentro de `.cache/src/`; se o ctx descartar o caminho por estar em `.cache`, registrar como M-NN em `docs/ctx/MELHORIAS.md` e ajustar o `[index]` (`extra_exclude_dirs`/globs) até a busca achar.
- [x] 3.3 `tests/unit/test_guardrail_readonly_paths.py`: exemplos sem `~/data/r36os` (cobrindo `/run/media` liberado e qualquer acesso a `~/data` perguntando) e docstring atualizado. Verificação: `uv run pytest tests/unit/test_guardrail_readonly_paths.py` passa.

## 4. Documentação

- [x] 4.1 `README.md`: em Requisitos, o cache em `.cache/` (o que guarda, tamanho aproximado, No-COW automático no Btrfs, `R36OS_CACHE` para outro lugar, excluir do file watcher da IDE e o aviso do `git clean -fdx` com as chaves do abuild); `~/.cache/r36os/vendor/` vira `.cache/vendor/`; `.cache/` e `out/` entram na seção Estrutura; nova seção curta "Cache de versões anteriores" com os passos do Migration Plan do `design.md`. Verificação: `rg -n "\.cache/r36os|data/r36os" README.md` não acha nada e os comandos da seção de migração conferem com o `design.md`. *Resultado (2026-11-13):* o `rg` só acha a seção "Cache de versões anteriores", que precisa citar o caminho antigo (`~/.cache/r36os`); fora dela, nada. O `~/data/r36os` (só desta máquina) não aparece: a seção explica o caso do symlink.
- [x] 4.2 `docs/VM.md` (linhas 23, 47, 73 e 102) e `aports/README.md:4` passam a citar `.cache/`. Verificação: `rg -n "\.cache/r36os" docs aports` não acha nada.
- [x] 4.3 Skill `repo-clean` (`.claude/skills/repo-clean/SKILL.md` e `.agents/skills/repo-clean/SKILL.md`, iguais): `~/data/r36os` vira `.cache`. Verificação: `rg -n "data/r36os" .claude .agents` não acha nada, e os dois arquivos continuam idênticos (`cmp`).

## 5. Migração nesta máquina (sem build rodando)

- [x] 5.1 Conferir `podman ps` vazio, rodar `uv run r36os clean`, revisar a lista com o usuário e rodar `uv run r36os clean --yes`. Verificação: `du -h --max-depth=1 ~/data/r36os` mostra só o `kbuild` do digest atual. *Resultado (2026-11-13):* rodado com `R36OS_CACHE=~/data/r36os` (o código novo já aponta para `.cache/`); 18 itens, 13,9 GiB liberados; nenhuma árvore do digest atual existia, então o `kbuild/` ficou vazio (4,3 GB no total).
- [x] 5.2 `stat -c %d ~/data/r36os .` mostra o mesmo dispositivo; `mkdir .cache`, `chattr +C .cache` e mover cada pasta de primeiro nível de `~/data/r36os/` para `.cache/` com um `mv` por chamada. Verificação: `lsattr -d .cache` mostra `C`; `du -sh .cache` bate com o tamanho de antes; `ls -A ~/data/r36os` vazio.
- [x] 5.3 Remover o symlink `~/.cache/r36os` e a pasta `~/data/r36os` (`rmdir`), com OK do usuário. Verificação: `ls -la ~/.cache/r36os` e `ls ~/data/r36os` dizem que não existem.

## 6. Integração

- [x] 6.1 `uv run pytest tests/unit` passa por inteiro. *Resultado (2026-11-13):* 381 passed, nenhum pulado (os testes que leem o cache o acham em `.cache/`).
- [ ] 6.2 `uv run r36os build vm` reaproveita o cache migrado (sem baixar o kernel de novo e com acertos do ccache) e `uv run r36os test-vm` passa; `git status` não mostra nada em `.cache/`. Verificação: log do build sem download do `linux-*.tar.xz` e resultado do `test-vm` anotado no `design.md`.

## Workflow follow-up

- Trabalhar na branch `feature/project-cache`, criada a partir da `main`, e não na `feature/boot-dtb-select`, que tem mudanças abertas. Commits pequenos (Conventional Commits) só com o OK do usuário.
- Depois do archive, atualizar a memória do agente que cita `~/data/r36os` e `~/.cache/r36os` (`r36s-bringup-state`, `build-workflow-gotchas`, `ctx-index-local-fix`).
- Change seguinte: organização e documentação do repositório para quem não usa IA (`repo-readability`).

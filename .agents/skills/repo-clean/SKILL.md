---
name: repo-clean
description: Libera o espaço das sobras de build do r36os (árvores de kernel de conjuntos de patches antigos, imagens arquivadas antigas, cópia descomprimida do flash, pastas de trabalho do abuild, caches do Python) sem tocar no que não se refaz. Use quando o usuário pedir para limpar o repositório, liberar espaço em disco, ou quando `out/` ou `.cache` estiverem grandes.
---

# Limpeza do repositório r36os

A limpeza é feita pelo comando do projeto `uv run r36os clean` (`src/r36os/clean.py`, testes em
`tests/unit/test_clean.py`). Ele sabe o que um build novo recria e o que não se refaz.
**Nunca apague à mão** (`rm`, `rmtree`, gerenciador de arquivos): as regras ficam no código,
testadas, e o guardrail barra `rm -rf`.

## Passo a passo

1. **Simular** (padrão, não apaga nada):
   ```
   uv run r36os clean
   ```
   Mostra duas listas com tamanhos: **a remover** e **para revisão** (nunca removida).
2. **Conferir a lista "a remover"** antes de seguir:
   - nenhum item em `var/`, `out/repo`, `out/r36s-factory` ou `out/r36s-bootlogs` (o comando
     recusa esses, mas confira);
   - nenhuma imagem que o usuário queira guardar: o comando mantém `latest`, `flashed` (o
     build que está no cartão), as 3 mais novas de cada imagem (`--keep N` muda) e qualquer
     carimbo `AAAAMMDD-HHMMSS` citado em `docs/`, `openspec/` ou `README.md`. Se o usuário
     falou de um build que não está citado, cite-o num desses arquivos ou aumente `--keep`;
   - nenhum build rodando (`podman ps` vazio): a árvore do kernel de um build em andamento
     pode parecer antiga se os patches mudaram no meio dele.
3. **Mostrar ao usuário** o total e o resumo por tipo (árvores de kernel, imagens, flash,
   abuild, caches do Python) e a lista de revisão, e **pedir confirmação**. Apagar é
   irreversível; não confirme sozinho.
4. **Apagar** só com o OK do usuário:
   ```
   uv run r36os clean --yes
   ```
5. **Lista de revisão** (o comando não apaga):
   - entradas desconhecidas em `out/` (testes avulsos, como `out/kpatch-work`): pergunte ao
     usuário item por item antes de qualquer coisa;
   - worktrees em `out/worktrees/` de ramos já incorporados: remover com
     `git worktree remove <caminho>` só com o OK do usuário (regras de git do projeto).

## O que sai e por que não faz falta

| O quê | Onde | Por que pode sair |
|---|---|---|
| Árvores de build do kernel de conjuntos de patches antigos | `.cache/kbuild/<placa>-<digest>` | o build usa só a do digest atual de `kernel/patches/`; mudou um patch, nasce outra |
| Imagens arquivadas antigas | `out/images/<imagem>/<carimbo>/` | ficam a `latest`, a `flashed`, as N mais novas e as citadas nos documentos |
| Imagem descomprimida do flash | `.cache/flash/*.img` | o `flash` descomprime de novo a partir do `.img.zst` arquivado |
| Pastas de trabalho do abuild | `aports/*/{src,pkg,tmp}` | o `r36os pkg` baixa (do `distfiles`) e monta de novo |
| Caches do Python | `__pycache__`, `.pytest_cache` | recriados na próxima execução |

## O que nunca sai

- `var/`: ROMs de teste do usuário (privadas; não citar nomes nem caminhos de jogos).
- `out/repo`: repositório local de pacotes (horas de compilação sob `qemu-user`).
- `out/r36s-factory`, `out/r36s-bootlogs`: provas tiradas do aparelho, não se refazem.
- No cache (`.cache`, ou `$R36OS_CACHE`): `ccache`, `distfiles`, `abuild` (chaves de assinatura),
  `vendor`, `vm` e a árvore do kernel atual (`src/`, que o próprio build troca).
- `.ctx/`, `.venv/`: índice e ambiente do `ctx` (para o índice, `ctx doctor --fix`).
- Imagens de container do podman: são compartilhadas com outros projetos da máquina.

## Depois

Relatar ao usuário o espaço liberado (última linha do comando) e o que ficou na lista de
revisão. Se aparecer um tipo novo de sobra que se repete, acrescente a regra em
`src/r36os/clean.py` com teste, não um comando avulso.

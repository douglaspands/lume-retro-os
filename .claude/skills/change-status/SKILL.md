---
name: change-status
description: Mostra o andamento da entrega de uma change do OpenSpec de forma compilada e curta (porcentagem concluída, tarefas feitas e pendentes, onda atual, o que está executando agora, o que está pronto para começar, o que falta e o que precisa do usuário). Use quando o usuário pedir status, andamento, progresso, estatísticas ou "quanto falta" de uma change, ou rodar /change-status.
---

# Status da entrega de uma change

Os números saem de um script, nunca de conta feita de cabeça.

## 1. Coletar

```
.venv/bin/python .claude/skills/change-status/status.py [<change>]
```

- Sem `<change>`, usa a única change ativa; com mais de uma, o script lista os nomes e você
  pergunta qual.
- O script lê o `tasks.md` da change (marcações, tabela do "Grafo de execução" e janelas de
  aparelho) e o estado real: worktrees `<change>/<nó>` e se o branch já foi mesclado em
  `feature/<change>`, containers do `podman` e processos `r36os build|pkg|push|flash` em
  andamento (inclusive pelo `cache/tmp/timed.py`), com o tempo de cada um.
- `--json` dá os mesmos dados estruturados, se precisar filtrar.

## 2. Completar com o que só a sessão sabe

O script não vê o que roda dentro desta sessão. Acrescente, se houver:
- subagentes em segundo plano ainda sem relatório (nó e modelo);
- comando ou prova esperando o usuário (console a ligar, cartão a trocar, resposta pendente);
- tarefas já provadas mas ainda não marcadas no `tasks.md` (diga que estão "provadas, falta
  marcar", sem contar na porcentagem).

Não invente tempo restante. Se o usuário pedir uma estimativa, dê uma faixa e diga em que se baseia.

## 3. Mostrar (pt-BR, no máximo ~25 linhas)

Formato:

```
## <change>: <feitas>/<total> tarefas · <pct>%
[##########..........]

**Onda atual:** <n> · feitas <ids> · pendentes <ids>

**Executando agora**
- <build/subagente/worktree não mesclada, com tempo>   (ou "nada")

**Pronto para começar** (dependências concluídas)
- <id> <título curto> (<modelo>) ...   (no máximo 6, os da onda atual e da próxima primeiro)

**Falta**
| Grupo | Feitas |
|---|---|
| <só os grupos com pendência, nome curto> | x/y |

**Precisa de você:** <próxima janela de aparelho com as provas pendentes e o que fazer>
**Próximo passo:** <uma linha>
```

Regras:
- Títulos curtos (até ~50 caracteres), sem copiar a descrição inteira da tarefa.
- Worktrees já mescladas não entram em "Executando agora"; se houver muitas, diga numa linha
  que podem ser removidas (só com o OK do usuário).
- Nada de nomes de jogos ou caminhos de ROMs (privacidade dos ROMs de teste).

# Melhorias do `ctx` (agent-harness-hub) medidas neste projeto

Este projeto serve de banco de testes para o `ctx` do
[agent-harness-hub](https://github.com/douglaspands/agent-harness-hub). As melhorias são feitas
primeiro aqui, como protótipo no `.venv`, medidas no trabalho real e acumuladas neste arquivo.
Quando o usuário pedir, este arquivo vira o prompt para aplicar as melhorias no agent-harness-hub.

- **Versão instalada:** agent-harness-hub **0.5.0** (`main` @ `feaf71e`, PR #4), desde
  2026-11-14, só no `.venv` com `uv pip install --reinstall "agent-harness-hub[all]"` (fora do
  `pyproject.toml`). O `ctx upgrade` regenerou `scripts/guardrail.py`, skills e blocos de
  instruções a partir do kit; as mudanças locais de M-18 e M-19 agora vêm do gerador.
- **Protótipo da 0.4.0 (obsoleto):** [`ctx-0.4.0-local.patch`](ctx-0.4.0-local.patch) e
  `ctx-0.4.0-local-m19-m22.patch` eram diffs contra o `site-packages` da 0.4.0. Tudo o que eles
  faziam foi levado na 0.5.0; não reaplicar.
- **Dependências opcionais:** os extras `c` (`tree-sitter`, `tree-sitter-c`) e `semantic`
  (`model2vec`, que traz `numpy`, `tokenizers`, `safetensors`, `huggingface-hub`) do
  agent-harness-hub, instalados com `[all]`. Sem eles, o `ctx` volta ao comportamento anterior.
- **Configuração deste projeto:** `[index.reference]` no `policy.toml` (DTS de fábrica e
  drivers de vídeo/DSI/PHY e DTS do PX30/RK3326 da árvore do kernel com patches).

## Linha de base (antes das melhorias)

`ctx evaluate` em 2026-11-12, 12 sessões, tokens estimados (caracteres ÷ 4):

| Medida | Valor |
|---|---|
| Veredito | não compensa |
| Saldo líquido estimado | −2.390 tokens por sessão |
| Adoção da busca | 1% (10 `ctx search` contra 1.727 `rg`/`grep`/`sed`) |
| Recall | nunca consultado |
| Bloqueios do guardrail | 50 (média 4,3 → 4,0 por sessão) |
| Índice | 291 arquivos, 4 MB, busca de 1 a 8 ms |

### Medição de 2026-11-12 (com os protótipos M-01 a M-06 e M-11)

`ctx evaluate`, 13 sessões, mesma estimativa de tokens:

| Medida | Valor |
|---|---|
| Veredito | não compensa |
| Saldo líquido estimado | −1.763 tokens por sessão (ganho ≈ 12.250, custo ≈ 35.172) |
| Custo fixo | ≈ 1.744 tokens de instruções por sessão + 12.500 dos bloqueios |
| Adoção da busca | 1% (20 `ctx search` contra 1.772 `rg`/`grep`/`sed`); 45 chamadas poupadas pela multi-query; p95 358 ms |
| Recall | 2 consultas, 2 com resultado (marginal) |
| Fatos | nenhum registrado |
| Upstream | não usado; 2 downloads manuais repetidos da mesma URL |
| Receitas | 1 execução, 0 com sucesso |
| Bloqueios do guardrail | 50 (média 4,3 → 3,4 por sessão): único recurso que compensa |

Melhoras desde a linha de base: saldo de −2.390 para −1.763 por sessão, buscas de 10 para 20,
recall passou a ser usado. As propostas M-14 a M-17 vêm desta medição.

## Melhorias

Estado: **proposta** (só descrita), **protótipo** (aplicada no `.venv` deste projeto),
**medida** (com resultado registrado), **levada** (enviada ao agent-harness-hub).

### Entrega da 0.5.0 (2026-11-14, PR #4)

- **Levadas:** M-01 a M-07, M-11, M-13, M-18 a M-20, M-22, M-24 a M-26, e a parte de relatório do
  M-21. Detalhes no `CHANGELOG.md` do agent-harness-hub.
- **Só desenho**, com decisão e custo em `docs/design/ctx-propostas.md` do agent-harness-hub: M-08,
  M-09, M-10, M-12, M-14, M-15, M-16 + M-27, M-17 e o resto do M-21 (aviso no momento da descoberta).
- **Não levadas:** o modelo multilíngue como padrão (só com M-10) e a mudança de padrão do M-23
  (medição continua aqui).
- **Diferenças em relação ao protótipo**, achadas na prova neste projeto:
  - esquema do índice 4, e não 3 (o protótipo já tinha usado o 3); as colunas também são conferidas;
  - o recuo da consulta (M-01) completa a lista com o passo seguinte quando faltam resultados:
    `dsidph` citado em `docs/ctx/` não esconde mais `phy-rockchip-inno-dsidphy.c`;
  - a sobra curta de uma função longa (M-03) fica na parte anterior: `get_lane_mbps` trazia só
    as 4 linhas finais da função;
  - a reindexação dos resultados desatualizados (M-26) só acontece com
    `[search].refresh = "incremental"`; o padrão `off` mantém a regra de a busca não escrever;
  - o modelo semântico (M-05) só é baixado pelo `ctx index`, e só os arquivos que o model2vec
    usa (30 MB em vez de 59 MB);
  - bloqueios antigos (sem id de regra) contam na mesma linha que os novos no `evaluate` (M-19).
- **Prova (2026-11-14):** as 5 consultas do prompt trazem o esperado em 1º, os falsos
  positivos do M-24/M-25 passam e os destrutivos continuam barrados, e o `evaluate` mostra os
  bloqueios por regra (`chaining` 41×, 54 repetidos na mesma sessão). A busca com a semântica
  ligada ficou com p95 de ~1 s (carga do modelo a cada chamada, ver M-10).

### M-01. Recuo da consulta quando todos os termos não casam — levada (0.5.0)

- **Problema:** a consulta exige todos os termos (`"a" "b" "c"`). Uma frase em linguagem natural
  com uma palavra que não aparece no código volta vazia. Exemplo: `factory dtb backlight pwms`
  → 0 resultados.
- **Mudança:** `sanitize_query(query, mode)` com três modos, tentados em ordem até haver
  resultado: `and` (todos os termos), `trigram` (cada termo de 3+ caracteres como substring, ver
  M-04) e `or` (qualquer termo; só com 2+ termos). O CLI mostra o modo usado no cabeçalho da
  consulta ("por substring", "com qualquer termo").
- **Resultado:** `factory dtb backlight pwms` passou a trazer os nós `backlight` do DTS do R36S e
  de outras placas PX30.

### M-02. Pesos por coluna no BM25 — levada (0.5.0)

- **Problema:** `bm25(chunks)` dá o mesmo peso a caminho, título e corpo. Um casamento no nome do
  símbolo vale tanto quanto uma menção de passagem.
- **Mudança:** `bm25(chunks, 2.0, 6.0, 0.5, 0, 0, 1.0, 0)` (caminho, título, tipo, —, —,
  conteúdo, —). Só rende junto com M-03, que põe o nome do símbolo no título.

### M-03. Corte estrutural para C e Device Tree — levada (0.5.0)

- **Problema:** C e DTS caem no corte genérico de janelas fixas de 50 linhas. A função fica partida,
  o título não diz o que há no trecho e a busca por `get_lane_mbps` trazia a tabela `hstt_table`
  antes da função.
- **Mudança** (`ctx/chunkers.py`):
  - **C/H**, com tree-sitter-c (opcional): um trecho por definição de nível superior (função,
    struct, enum, typedef, tabela estática, macro de 3+ linhas), com o comentário logo acima e o
    nome do símbolo no título. Definições acima de 120 linhas viram partes com o mesmo título. O
    que fica entre definições usa janelas de 50 linhas, com os `#define` listados no título.
  - **DTS/DTSI**, sem dependência: contagem de chaves; cada nó de profundidade 1 dentro de `/ { }` e
    cada `&rótulo { }` vira um trecho com o rótulo e o nome no título (`backlight: backlight`,
    `dsi@ff450000`, `&dsi`).
- **Resultado:** `dw-mipi-dsi-rockchip.c` passou de janelas cegas a 81 trechos com nome
  (`dw_mipi_dsi_get_lane_mbps`, `px30_chip_data`…); o DTS de fábrica, a 141 nós. A busca por
  `get_lane_mbps` traz a função inteira.
- **Próximo:** shell, TOML e YAML ainda usam o corte genérico.

### M-04. Índice de trigramas para pedaços de identificador — levada (0.5.0)

- **Problema:** o tokenizador `unicode61` só casa palavras inteiras. `dsidph` ou `lane_mb` não
  acham nada, e é aí que o agente recorre ao `rg`.
- **Mudança:** segunda tabela FTS5 `chunks_tri` (`tokenize='trigram'`, mesmo `rowid` de
  `chunks`), usada como segundo passo do recuo (M-01). Esquema do índice: versão 3.
- **Resultado:** `dsidph` traz as definições de `phy-rockchip-inno-dsidphy.c`.
- **Custo:** índice de 4 MB para 24 MB (com M-05 e as referências), quase tudo dos trigramas.

### M-05. Busca semântica local, híbrida com BM25 — levada (0.5.0, extra `semantic`)

- **Problema:** a busca é só lexical; uma pergunta ("onde o glue calcula a taxa da lane") só acha
  algo se repetir as palavras do código.
- **Mudança** (`ctx/semantic.py`):
  - Embeddings estáticos `minishlab/potion-base-8M` (model2vec, 256 dimensões, CPU): 2.000 trechos
    em 16 ms.
  - Vetores em BLOB numa tabela comum (`vectors`) do próprio `index.db`; similaridade de cosseno
    com numpy, por força bruta.
  - O modelo é baixado só na indexação, para `.ctx/models/`; a busca nunca acessa a rede.
  - Fusão por *reciprocal rank fusion* (k = 60): 20 candidatos de cada lado, peso 1,0 para o BM25 e
    0,8 para a semântica (o termo exato vence o empate). Cada resultado mostra a origem (`bm25`,
    `sem` ou `bm25+sem`).
  - `[search].semantic = false` desliga; `[search].semantic_model` troca o modelo.
- **Resultado:**
  - `where the glue computes the lane rate` → patch 0014, `dw_mipi_dsi2_get_lane_mbps` e
    `inno_dsidphy_validate`: certos.
  - `panel stays grey with no video` → hunk do painel no patch 0010 e testes do painel: certos.
  - **Em português, falhou:** `onde o glue calcula a taxa da lane` trouxe documentos sem relação,
    porque o modelo é só de inglês.
- **Achados:**
  - **`sqlite-vec` não serve como base:** o Python do `.venv` (3.14.7) não tem
    `enable_load_extension`. A força bruta com numpy é portátil e basta para milhares de trechos.
  - **Latência:** de ~8 ms para ~300 ms por chamada do CLI, quase toda para importar o numpy e
    carregar o modelo a cada processo.
  - **Modelo duplicado:** `.ctx/models` tem 89 MB, porque o download passa pelo cache do Hugging
    Face (`.ctx/models/.hf`) e depois é salvo de novo.
- **Modelo multilíngue (medido em 2026-11-12):** `minishlab/potion-multilingual-128M` contra o
  `potion-base-8M`, só semântica, top 3 em 3.708 trechos, 5 perguntas em português e as mesmas em
  inglês:

  | Modelo | Disco | Carga (cache) | PT certas | EN certas |
  |---|---|---|---|---|
  | `potion-base-8M` | 30 MB | 0,18 s | 0 de 5 | 3 de 5 |
  | `potion-multilingual-128M` | ~480 MB | 3,3 s | 2 a 3 de 5 | 4 de 5 |
  | multilíngue em int8 | 140 MB | 2,7 s | — | — |
  | multilíngue em float16 | 263 MB | 3,1 s | — | — |

  - O multilíngue acerta "luz de fundo do painel" → nó `backlight` e "painel fica cinza sem vídeo"
    → requisito "Vídeo no painel interno"; o de inglês erra todas em português.
  - Nenhum dos dois acerta "onde o glue calcula a taxa da lane" só pela semântica (no híbrido, o
    BM25 resolve em inglês).
  - **A carga é dominada pelo tokenizador** (vocabulário de ~500 mil tokens), não pelos pesos:
    quantizar reduz o disco, mas a carga cai pouco. Carregar 3 s a cada `ctx search` não é aceitável.
  - **Decisão:** o protótipo continua com o `potion-base-8M`. O multilíngue só vale com M-10 ou
    M-11.
- **Próximo:**
  - pular a semântica quando o BM25 já trouxe `top_k` resultados com todos os termos;
  - baixar direto para `.ctx/models/` (`snapshot_download(local_dir=…)`), sem o cache duplicado.

### M-06. Prévia centrada no termo e com linha cortada — levada (0.5.0)

- **Problema:** a prévia começava no início do trecho, às vezes o cabeçalho de licença, e não na
  linha que casou. Uma linha longa (JSONL) inundava a saída.
- **Mudança:** com o trecho maior que a prévia, ela começa 3 linhas antes da primeira linha que
  contém um dos termos. Cada linha é cortada em 200 caracteres, com a contagem do resto.

### M-07. Receita `copy-verify` barrada pela própria política — levada (0.5.0, `requires`)

- **Problema:** os passos da receita embutida (`cp`, `sync`, `sha256sum`) não estão no
  `commands.allow` padrão; a receita não roda sem `--yes`.
- **Mudança proposta:** liberar esses comandos na política padrão quando chamados pela receita, ou
  a receita declarar os comandos de que precisa.
- **Medido (2026-11-13):** as 5 execuções do `.ctx/events.jsonl` terminaram em
  `needs_confirmation` com 0 etapas executadas (o `evaluate` mostrava "4 execuções, 0 ok").
  Com `cp`, `sync` e `sha256sum` no `commands.allow` do `policy.toml` deste projeto, a receita
  rodou: 5/5 etapas numa chamada, 4 chamadas economizadas. As regras de caminho continuam
  pedindo confirmação para escrita fora do workspace.
- **Para levar ao upstream:** a receita declarar os comandos que usa (`requires = [...]`), e o
  `ctx init` colocar os da receita embutida no `allow` gerado.

### M-08. `copy-verify` confere o cache, não o disco — proposta (desenho no hub)

- **Problema:** o SHA256 é calculado logo depois do `sync`, na mesma montagem, e pode ler o cache
  de página do sistema em vez do dispositivo. Neste projeto o leitor USB corrompe gravações
  pequenas, e só a conferência depois de desmontar e montar só leitura é confiável.
- **Mudança proposta:** opção `--remount-ro <dispositivo>` (desmontar, montar só leitura e conferir)
  ou ler com `O_DIRECT` / depois de `posix_fadvise(DONTNEED)`.
- **Visto também no `r36os flash` (2026-11-13), e corrigido nele:** a leitura de volta pelo
  `/dev/sdX` vinha do cache de páginas, então o SHA256 não lia o cartão; e a gravação pelo cache
  enchia o limite global de páginas sujas (256 MiB no PC do usuário) e travava o desktop (o
  Chrome primeiro). O `flash` passou a usar `oflag=direct` e `iflag=direct`. A mesma ideia
  serve à `copy-verify`.

### M-09. Referências fora do workspace com caminho versionado — proposta (desenho no hub)

- **Problema:** a árvore do kernel deste projeto muda de nome a cada mudança nos patches
  (`linux-6.18.62-<hash>`). O `[index.reference]` resolve com curinga, mas os caminhos dos
  resultados são absolutos e longos (`/home/…/data/r36os/src/linux-…/drivers/…`). O `[upstream]`
  supõe baixar arquivo por arquivo de uma URL, o que não serve para uma árvore gerada pelo build.
- **Mudança proposta:** fonte de referência com nome (`[index.reference.kernel] root = "…"`,
  `globs = […]`), mostrada nos resultados como `kernel:drivers/…`.

### M-10. Processo residente para a busca — proposta (desenho no hub)

- **Problema:** cada `ctx search` é um processo novo, que importa o numpy e carrega o modelo de novo:
  ~0,3 s com o `potion-base-8M` e ~3,3 s com o multilíngue (M-05).
- **Mudança proposta:** um servidor local por projeto (socket Unix em `.ctx/`, iniciado na primeira
  busca e encerrado depois de N minutos parado) que mantém o modelo e a matriz de vetores em
  memória; o CLI só repassa a consulta. Sem o servidor, o CLI busca sozinho, como hoje.

### M-11. Glossário do projeto para expandir a consulta — levada (0.5.0)

- **Implementado (2026-11-12):**
  - `[search].glossary` no `policy.toml`: lista de grupos de termos equivalentes, com 23 grupos
    iniciais tirados desta sessão.
  - `expand_query()` casa os termos sem diferenciar maiúsculas nem acentos.
  - O BM25 tenta a consulta original e depois a traduzida (cada termo trocado pelo primeiro
    equivalente); o recuo "qualquer termo" e a semântica usam a consulta mais todos os equivalentes.
  - O CLI mostra o que o glossário aplicou.
  - Junto: palavras vazias em português e inglês saem da consulta lexical (`STOPWORDS`), senão
    "backlight do panel" nunca casa com todos os termos.
- **Resultado** (as mesmas perguntas do teste do multilíngue, com o `potion-base-8M`):
  - "painel fica cinza sem vídeo" → seção 5 do `BRINGUP-R36S.md` (diagnóstico do painel) em 1º.
  - "onde o glue calcula a taxa da lane" → `dw_mipi_dsi2_get_lane_mbps`, o hunk do patch 0014 e
    `dw_mipi_dsi_phy_init` (antes: nada relacionado).
  - "luz de fundo do painel" e "cartão corrompido pelo leitor USB" ainda perdem para seções longas de
    markdown (ver M-13).

O texto abaixo é a proposta original.

- **Proposta:**

- **Problema:** neste projeto o código e os logs estão em inglês e a conversa e a documentação em
  português. A semântica multilíngue resolve só em parte e custa caro (M-05).
- **Mudança proposta:** um glossário curto por projeto (`[search.glossary]` no `policy.toml` ou
  `.ctx/glossary.toml`), com termos equivalentes (`painel = panel`, `luz de fundo = backlight`,
  `taxa da lane = lane rate, lane_mbps`, `cartão = card, sdcard`). A consulta é expandida antes do
  BM25 e da semântica. O `ctx` pode sugerir entradas a partir das consultas que voltaram vazias e
  das que o agente refez com outras palavras.
- **Por quê:** é a "ontologia" que este RAG precisa — leve, editável, versionada no projeto — e
  pode tornar desnecessário o modelo multilíngue de 480 MB.

### M-12. Ligações entre trechos (grafo de código) — proposta (desenho no hub)

- **Problema:** a busca devolve trechos soltos. Neste projeto as perguntas reais atravessam
  ligações: patch → arquivo → função; `compatible` no DTS → `of_match_table` do driver; rótulo
  `&dsi` → nó `dsi@ff450000`; teste → patch que ele confere.
- **Mudança proposta:** uma tabela `links (from_rowid, to_rowid, kind)` preenchida na indexação
  com o que já é extraído (símbolos dos patches, nomes de função C, rótulos e `compatible` do DTS),
  e `ctx search --related` ou `ctx refs <símbolo>` para seguir as ligações num passo só.

### M-13. Seções longas de markdown dominam o BM25 — levada (0.5.0)

- **Problema:** o corte de markdown faz um trecho por seção, sem limite de tamanho. A seção 4 do
  `tasks.md` (dezenas de linhas, cada uma longa) contém quase todas as palavras do projeto e aparece
  em 1º para perguntas genéricas ("luz de fundo do painel", "cartão corrompido pelo leitor USB"),
  na frente do nó `backlight` do DTS e da função `reader_warning`.
- **Mudança proposta:** dividir seções longas por item de lista ou parágrafo (mantendo o título da
  seção), e limitar o tamanho do trecho como já é feito em C (120 linhas) e nos hunks de patch.

### M-14. O `evaluate` conta como desvio o `rg` que o `ctx search` não substitui — proposta (desenho no hub)

- **Problema:** a adoção da busca (1%) conta todo `rg`/`grep`/`sed` como desvio. Na sessão do
  bring-up do R36S (boots 10 a 12), quase todos os `rg` eram de outro tipo:
  - em um arquivo conhecido, com padrão exato (linhas `panel|dsi|lane rate` do log, uma constante num
    patch);
  - fora do índice: logs de boot no cartão (`/run/media/…/ROMS/logs/boot/`), árvore do kernel
    gerada pelo build em `~/data` com hash novo a cada mudança nos patches (M-09) e saída de build.

  O `ctx search` não serve para esses casos, então a métrica pune o uso certo e esconde os desvios
  de verdade (busca ampla por conceito no repositório).
- **Mudança proposta:** classificar cada `rg`/`grep` do transcript antes de contar:
  1. **alvo único** — um arquivo como caminho;
  2. **fora do índice** — caminho fora do workspace ou ignorado pelo índice;
  3. **busca ampla** — diretório do workspace ou sem caminho.

  Só a busca ampla conta como desvio. O relatório mostra as três contagens.

### M-15. Custo fixo das instruções por sessão — proposta (desenho no hub)

- **Problema:** o bloco gerado no `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` custa ≈ 1.744 tokens por
  sessão, mais que todo o ganho medido por sessão (≈ 940). Boa parte repete o que o guardrail já
  ensina na hora do bloqueio: tabela de receitas, lista de binários, regras de encadeamento.
- **Mudança proposta:** bloco curto (Turno 1: `status`/`map`/`search`; `recall` em sessão retomada;
  "o guardrail explica o resto"). O detalhe fica na skill `workspace-ctx`, carregada só quando
  usada. O `evaluate` mede o custo pelo tamanho real do bloco gerado, por harness ativo.

### M-16. Upstream sem projetos declarados e downloads repetidos — proposta (desenho no hub, com M-27)

- **Problema:** o `ctx upstream get` nunca foi usado. Os 2 downloads manuais repetidos e a consulta
  ao ROCKNIX (patch do painel do R36S em `ROCKNIX/distribution`, ramo `next`, boot 12) passaram pela
  web porque nenhum projeto está declarado em `[upstream.*]`.
- **Mudança proposta:**
  - O `evaluate` (ou o fim de sessão) lista as URLs buscadas mais de uma vez e sugere o bloco
    `[upstream.<nome>]` pronto.
  - O `upstream get` aceita repositório GitHub + ramo + caminho (`github:ROCKNIX/distribution@next/<caminho>`),
    sem exigir um modelo de URL por projeto.
- **Configuração deste projeto (feita em 2026-11-12):** `[upstream.linux]` (espelho `gregkh/linux`,
  que tem as tags estáveis como `v6.18.62`) e `[upstream.rocknix]` (`ROCKNIX/distribution`;
  versão = sha do commit, ou ramo como `next`, sabendo que o cache não se atualiza). Testados com
  `panel-sitronix-st7703.c` da v6.18.62 e o `001-panel-updates.patch` do ROCKNIX (`next`), que
  confirmou o modo de 50 MHz do boot 12. Limite visto: com ramo como versão, o cache congela
  o conteúdo do dia do download sem avisar.

### M-17. Receitas que falham sem explicação no `evaluate` — proposta (desenho no hub)

- **Problema:** o `evaluate` mostra "1 execução, 0 ok" sem dizer por quê. A causa provável é a
  M-07 (passos da `copy-verify` fora do `commands.allow`), mas o relatório não liga as duas coisas.
- **Mudança proposta:** registrar o passo que falhou e o motivo (bloqueio do guardrail, código de
  saída) e mostrá-los no `evaluate`. Receita sem execução com sucesso em N sessões é sugerida
  para remoção.

### M-18. Leitura liberada fora do workspace e no `~/data`, só para caminhos declarados — levada (0.5.0)

- **Problema:** um bring-up lê o tempo todo coisas fora do workspace: os logs no cartão do
  aparelho (`/run/media/...`) e a árvore do kernel que o build gera (`~/data/r36os/src/...`).
  Cada `rg` nesses caminhos cai em `defer` (fora do workspace) ou em `ask` forte (qualquer
  menção ao `~/data`, o volume Btrfs No-COW), e o Claude Code pergunta ao usuário a cada busca.
  O `paths.readonly_system` já existia, mas não expandia `~` e era consultado **depois** da regra
  do `~/data`, então não servia para esse caso.
- **Implementado no protótipo (2026-11-12, `scripts/guardrail.py`):**
  - `matches_readonly_system` expande `~` e aceita `/**` no fim, como o `harness_allow`.
  - Novo `paths.readonly_commands` (padrão: `rg`, `ls`, `fd`, `sha256sum`, `wc`, `stat`, `tree`,
    `file`, `cmp`, `diff`): um comando cujos segmentos são todos só de leitura (ou filtros
    seguros de pipe), com todos os caminhos dentro do `~/data` em `readonly_system`, não
    dispara o `ask` do `~/data`.
  - Ferramenta de leitura de arquivo: dentro do `~/data`, a leitura de um caminho de
    `readonly_system` é `allow`; escrita e qualquer outro caminho do `~/data` seguem em `ask`.
  - Neste projeto: `/run/media`, `~/data/r36os/src` e `~/data/r36os/kbuild` em `readonly_system`.
  - Teste: `tests/unit/test_guardrail_readonly_paths.py` (leitura liberada; escrita, outro caminho
    do `~/data` e comando misturando um caminho liberado com outro não liberado seguem em `ask`).
- **Para levar ao agent-harness-hub:** o gerador do `guardrail.py` e o modelo do `policy.toml`
  com `readonly_commands` e a seção comentada explicando o uso; o `ctx upgrade` hoje
  sobrescreveria esta mudança local.

### M-19. Bloqueios do guardrail por regra, e quais não ensinam — levada (0.5.0, com id de regra)

- **Problema:** o `evaluate` soma todos os bloqueios como custo (13 250 tokens estimados) e, ao mesmo
  tempo, os conta como recurso que compensa, sem dizer qual regra pesa.
- **Medido (2026-11-13, 15 sessões):** 53 bloqueios, **34 repetidos na mesma sessão** (a regra
  disparou de novo, então o coaching não ensinou). Por regra: encadeamento de comandos shell 31
  (~7 750 tokens), padrão proibido `mkfs` 9, `tree` sem `-L` 4, `git log` sem `-n` 3. A regra do
  encadeamento sozinha é ~58% do custo: é o que o agente mais repete.
- **Implementado:** `metrics.py` guarda `denial_rules` e `denial_repeats` por sessão; o `evaluate`
  soma e o `cli.py` imprime a tabela "Bloqueios por regra" (primeiras 8). Patch incremental em
  `docs/ctx/ctx-0.4.0-local-m19-m22.patch`.
- **Falta:** o rótulo da regra é o início da mensagem (70 caracteres); o guardrail deveria gravar um
  identificador de regra no `events.jsonl`. Limitar a mensagem do encadeamento a uma linha com a
  receita pode reduzir a repetição.
- **Mensagem mais instrutiva (2026-11-13, `scripts/guardrail.py`):** o `deny` de encadeamento agora
  diz o que fazer no lugar: comandos independentes em chamadas Bash paralelas no mesmo turno,
  dependentes em turnos seguintes, e `cd X && cmd` vira caminho absoluto ou `git -C X`. Medir na
  próxima avaliação se os 34 repetidos caem. **Para levar ao agent-harness-hub:** o texto no gerador
  do `guardrail.py`; o `ctx upgrade` hoje sobrescreveria esta mudança local.
- **Medido de novo (2026-11-14, 31 sessões):** o encadeamento continua sendo o bloqueio mais caro,
  com 47 bloqueios (≈ 11.750 tokens estimados), e há 60 bloqueios repetidos na mesma sessão (eram 34
  em 15 sessões). A mensagem mais instrutiva não derrubou a repetição. Proposta: o `deny` de
  encadeamento devolve os comandos já separados, prontos para virar chamadas paralelas (por
  exemplo `1) git status -s  2) git log --oneline -n 5`), em vez de só explicar a regra. Se a
  repetição não cair na próxima avaliação, avaliar trocar o `deny` por `allow` com registro de
  auditoria para cadeias só de leitura (`git`, `rg`, `ls` ligados por `&&`).
- **`git log` sem `-n`** (12 bloqueios) e **`tree` sem `-L`** (4) também se repetem. Mesma
  proposta: a mensagem traz o comando corrigido.

### M-20. Veredito provisório com amostra pequena — levada (0.5.0)

- **Problema:** com 15 sessões (e um modelo com 1), "não compensa" saía com o mesmo peso de um
  veredito com amostra grande.
- **Implementado:** `overall.confidence` é `provisório` abaixo de `[metrics.evaluate].confident_sessions`
  (padrão 30); o relatório mostra o aviso e a recomendação manda repetir a avaliação antes de desligar
  um recurso. Intervalo de confiança do saldo fica como evolução.

### M-21. Registro de fatos quando algo custou caro — levada em parte (relatório na 0.5.0; aviso na descoberta em desenho no hub)

- **Problema:** nenhum fato registrado em 15 sessões, e o `recall` depende só de transcript. O agente
  nunca chama `ctx fact add`.
- **Implementado:** com a amostra mínima e nenhum fato, o `evaluate` recomenda `ctx fact add` com
  exemplos do que registrar.
- **Falta (proposta):** o guardrail avisar no momento da descoberta, por exemplo quando uma mesma
  sessão faz um `ctx search` seguido de 3 ou mais leituras no mesmo arquivo, ou ao fim da sessão
  (`ctx fact review` já existe para candidatos).
- **Primeiro uso (2026-11-13):** a pedido do usuário, depois do `evaluate`, 13 fatos da sessão da
  change `usb-device-access` (fatos #1 a #13: `udhcpd` no `busybox-extras`, `umtprd` em `/bin`,
  medição da porta OTG, fallback de VBUS do `phy-sun4i-usb`, role switch do dwc2, drivers de Wi-Fi
  do RetroArch, socket dos comandos de rede, firmware em zstd, dependência do `HID_PLAYSTATION`,
  VM sem Bluetooth, `dropbear -B`, U-Boot de fábrica sem `ums`, `flash` com `sudo`). Todos com
  fonte `arquivo:linha`, para o `ctx fact stale` avisar quando a fonte mudar. O registro só
  aconteceu porque o `evaluate` recomendou e o usuário pediu: o agente não o fez sozinho ao
  descobrir, o que reforça a proposta acima.

### M-22. Adoção por sessão, não só por chamada — levada (0.5.0)

- **Problema:** 1% por chamada (21 buscas contra ~2 300 desvios) não distingue "não usa" de "usa
  pouco": 8 de 15 sessões usaram `ctx search` e 13 de 15 algum comando do ctx.
- **Implementado:** a evidência de "busca e índice" mostra as duas medidas. Combina com o M-14, que
  limpa os desvios que o `ctx search` não substitui.

### M-23. Coach das ferramentas de arquivo ligado — medição em andamento

- **Problema:** com `[file_tools] mode = "off"`, só as instruções pedem a ferramenta nativa em vez
  de `cat`/`head`/`sed -n`. O `evaluate` de 2026-11-13 (23 sessões, provisório) recomendou o
  modo `coach` junto com a adoção de 1% da busca.
- **Mudança (2026-11-13):** `mode = "coach"` no `policy.toml` e `ctx rule sync`; o bloco gerado
  ganhou uma linha avisando do modo.
- **Medir:** no próximo `evaluate`, os bloqueios da regra de ferramentas de arquivo (quantos e se
  se repetem na mesma sessão) e se a média de bloqueios por sessão volta a cair. Se o coach só
  somar bloqueios sem mudar o hábito, voltar para `off`.
- **Primeira medição (2026-11-14, 31 sessões, janela inteira):** 10 bloqueios da regra
  `file-tools:read`; a adoção da busca continua em 1% por chamada (51 `ctx search` contra 3.587
  `rg`/`grep`/`sed`). O `evaluate` voltou a recomendar ligar o coach, sem notar que ele já está
  ligado: falta ao relatório ler o `policy.toml` antes de recomendar. A janela inteira mistura
  sessões de antes e de depois da mudança. A próxima avaliação deve usar só as sessões a partir
  de 2026-11-13 para decidir entre manter ou voltar para `off`.

### M-24. Padrões proibidos casam com argumentos, não com o comando — levada (0.5.0)

- **Problema (sessão de 2026-11-13, change `usb-device-access`):** os padrões proibidos do
  guardrail são procurados como substring na linha inteira. Falsos positivos vistos:
  - `rm -rf /storage/.lume-push` (pasta temporária no console, via `ssh`) barrado por
    `rm -rf /`: qualquer `rm -rf` de caminho absoluto casa;
  - `rg -n "mksquashfs|SOURCE_DATE_EPOCH" src` barrado por `mkfs`: o padrão estava no **texto
    da busca**; os 9 bloqueios de `mkfs` do M-19 têm a mesma causa;
  - `rm -rf /tmp/s` dentro de um `podman run ... sh -c "..."` de teste também barrado.

  O agente contorna (`rm -r`, outra grafia), o que ensina a driblar a regra em vez de respeitá-la.
- **Mudança proposta:** separar o comando em argv (`shlex`) e casar a regra com o comando e as
  opções: `rm` com `-r`/`-f` e alvo exatamente `/`, `/*` ou um diretório de sistema (`/etc`,
  `/usr`, `$HOME`…); `mkfs*` só como nome de programa (`argv[0]`, ou depois de `sudo`/`exec`).
  Argumentos de comandos de leitura (`rg`, `grep`, `ctx search`) nunca são comandos.
- **Medido de novo (2026-11-14):** 11 bloqueios de `destructive:mkfs` e 6 de `destructive:rm` em 31
  sessões. Mesmo com a mudança levada na 0.5.0, os números continuam subindo (eram 9 de `mkfs`).
  Conferir nos `events.jsonl` se ainda são falsos positivos (`mkfs` como texto de busca ou como
  argumento do `r36os` build) ou bloqueios de sessões antigas contadas na janela inteira.

### M-25. Encadeamento dentro de texto citado para outro host ou container — levada (0.5.0, aspas simples)

- **Problema:** `ssh root@10.55.0.1 "cmd1 ; cmd2"` passou (o `;` está dentro das aspas), mas
  `ssh ... "x=$(stat -c %s f) ; ..."` foi barrado pelo `$()` e um laço `while` no comando do
  Monitor também. O texto entre aspas é **um argumento** executado em outra máquina ou em outro
  shell (console por `ssh`, `podman run ... sh -c`). A regra é inconsistente (`;` passa, `$()` não)
  e força scripts temporários para coisas de uma linha.
- **Mudança proposta:** tratar o argumento citado de `ssh <host> "..."`, `podman|docker run ... sh
  -c "..."` e `sh -c` como um script remoto: aplicar a ele só as regras destrutivas (M-24), não a
  de encadeamento, que existe para auditar comandos **locais** um a um. Alternativa: uma receita
  `remote <host> <script>` que recebe um arquivo de script do scratchpad.

### M-26. `ctx search` não achou o módulo pelo nome do arquivo — levada (0.5.0)

- **Problema:** `ctx search "r36os push" "push build over ssh"` não trouxe `src/r36os/push.py` em
  nenhum dos 10 resultados (vieram serviços OpenRC e um hunk de patch do mesa). O módulo se
  chama `push.py`, tem `push` no título dos trechos e a docstring começa com "Update a console
  over the USB cable: `r36os push`". O agente achou o arquivo com `rg` logo depois.
- **Mudança proposta:** dar peso ao **nome do arquivo** (não só ao caminho inteiro) no BM25 e um
  bônus quando um termo da consulta é o radical do nome do arquivo; conferir com esta consulta
  como caso de teste.
- **Também visto:** o aviso "5 arquivo(s) nos resultados mudaram desde a indexação" sem
  reindexar. A busca podia reindexar na hora só esses arquivos (são poucos e já foram lidos).

### M-27. `upstream get` exige declarar o projeto antes — medida (desenho no hub, com M-16)

- **Medido (2026-11-13):** para ler o código do `umtprd` 1.6.8 foi preciso editar o `policy.toml`
  (`[upstream.umtprd]`) antes do primeiro `ctx upstream get`, e o arquivo com o achado
  principal (`src/msgqueue.c`) só apareceu depois de um `git clone` no scratchpad, porque não dá
  para buscar no projeto sem saber o caminho. Confirma o M-16: `github:<dono>/<repo>@<tag>/<caminho>`
  sem declaração prévia, e um `ctx upstream grep <projeto> <versão> <padrão>` (ou clone raso no
  cache, indexado) para quando o caminho não é conhecido.

### M-28. Fatos nunca consultados e com fonte em caminho que se move — proposta (desenho no hub)

- **Problema (2026-11-14):** o `evaluate` mostra 16 fatos registrados e **nenhuma consulta**. O
  agente não roda `ctx fact search` antes de redescobrir algo; o `recall` (transcripts, 6 de 6 com
  resultado) é o que de fato é usado. Além disso, 9 dos 16 fatos ficaram "stale" em um dia, sem
  que o conteúdo tivesse mudado:
  - 4 apontavam para o `design.md` de um change que foi arquivado (`openspec/changes/<nome>/` →
    `openspec/changes/archive/<data>-<nome>/`);
  - 3 apontavam para a árvore do kernel em `.cache/src/linux-6.18.62-<hash>/`, cujo hash muda a
    cada mudança nos patches (mesmo problema do M-09);
  - 2 tinham a linha citada deslocada por edições no mesmo arquivo.

  Não existe `ctx fact update`. Para manter um fato verdadeiro, é preciso registrar de novo e
  remover o antigo: foi o que se fez em 2026-11-14 (fatos #3 a #13 viraram #17 a #25).
- **Mudança proposta:**
  - O `ctx recall` também busca nos fatos e mostra os que casam primeiro, assim o fato é
    consultado sem um comando a mais.
  - `ctx fact stale` tenta realocar a fonte antes de declarar o fato velho: procura o trecho
    citado no mesmo arquivo (linha deslocada), no caminho arquivado do OpenSpec e na árvore com
    o mesmo prefixo e hash novo; com `--fix`, regrava a fonte.
  - `ctx fact update <id> --source ...` para corrigir a fonte sem perder o id.

### M-29. Receitas do console e da vm no lugar de scripts soltos — feita (policy.toml)

- **Problema (2026-11-17, J1 da `lume-hud-actions`):** cada `r36os dev shot/keys/run` e cada
  script de apoio em `cache/tmp/` caía fora da lista (`defer`) e pedia permissão ao usuário,
  dezenas de vezes por janela de aparelho. Liberar `cache/tmp/*` liberaria qualquer código novo.
- **Feito (escolha do usuário, opção 2):** os ajudantes que se repetem foram para
  `scripts/dev/` (versionados): `put.py` copia pelo ssh do `r36os dev`, faz `sync` e confere o
  sha256; `vm_qmp.py` captura a tela e aperta teclas na vm pelo QMP. Receitas no
  `policy.toml`: `console-put`, `vm-put`, `console-shot`, `console-keys`, `console-run`,
  `vm-shot`, `vm-keys`, `vm-holdshot`. Só as etapas delas entraram em `commands.allow`
  (`r36os dev shot`, `keys`, `run`, `wait`, `log`); o `r36os dev sh` (qualquer comando como root
  no console) continua pedindo.
- **Achado:** o guardrail toma qualquer argumento absoluto por caminho do PC; o destino no
  console vai como `console:/caminho` para não ser lido como leitura fora do workspace.
- **Para o hub:** uma forma de marcar um parâmetro de receita como "caminho remoto" (não
  checado contra o workspace) evitaria o prefixo; e caminhos com espaço não cabem numa etapa.

## Avaliação de 2026-11-14

`ctx evaluate` (31 sessões, sem a marca de provisório): **não compensa**. Saldo ≈ −46.486
tokens estimados (−1.500 por sessão); ganho ≈ 34.250 (137 chamadas) contra custo ≈ 80.736
(instruções 1.806 por sessão + bloqueios 24.750). Por recurso:
- recall e coaching do guardrail **compensam** (6 de 6 consultas com resultado; bloqueios por
  sessão de 3,7 para 2,8);
- upstream (18 chamadas, 0 servidas do cache sem rede) e receitas (6 execuções, 1 ok) são
  **marginais**;
- busca (adoção de 1% por chamada, 21 de 31 sessões; p95 de 1.050 ms) e fatos (nunca
  consultados) **não compensam**.

Por modelo, a amostra é pequena (Opus 29 sessões, só 1 sem ctx; Sonnet 2) e não permite comparar.

Feito na sequência: M-19, M-23 e M-24 medidos de novo; M-28 aberto; fatos stale registrados de
novo com a fonte atual. Próximos passos: avaliar só a janela desde 2026-11-13 (M-23); encurtar o
bloco de instruções (M-15), que sozinho custa mais que o ganho por sessão; decidir com o usuário se
o Antigravity sai de `[harnesses].enabled`.

## Avaliação de 2026-11-13

`ctx evaluate` (23 sessões, veredito provisório): **não compensa**, saldo ≈ −31.612 tokens
(−1.374 por sessão): ganho ≈ 24.250 (97 chamadas), custo ≈ 55.862 (instruções 1.744 por sessão +
bloqueios 15.750). Por recurso: coaching do guardrail e recall **compensam**; upstream marginal;
busca (36 `ctx search` contra 2.999 `rg`/`grep`/`sed`, 1% por chamada, 14 de 23 sessões) e
receitas (4 execuções, 0 ok, ver M-07) **não compensam**; fatos sem dados (registrados depois, ver
M-21). Bloqueio mais caro: encadeamento de comandos (35, ≈ 8.750 tokens). Feito na sequência:
M-07 medida, M-21 primeiro uso, M-23 ligado. O Antigravity continua em `[harnesses].enabled`
até o usuário dizer se o usa (o custo fixo é o M-15).

## Métricas a acompanhar

Repetir o `ctx evaluate` depois de algumas sessões e comparar com a linha de base:
- adoção do `ctx search` contra `rg`/`grep`/`sed`;
- quantas vezes cada modo de recuo (M-01) e a semântica (M-05) trouxeram o resultado usado;
- latência da busca e tamanho do índice.

Cada vez que o agente usar `rg` porque o `ctx` falhou, registrar aqui a consulta e o motivo.

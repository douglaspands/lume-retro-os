# Tasks

Verificação desta change: testes de unidade (Rust do `lume/`, Python em `tests/unit`, suítes
de shell), o protótipo do launcher no navegador a 640x480 (telas novas aprovadas pelo usuário)
e o aparelho (GA36 e R36S, com um único cartão passado de um console ao outro: nunca os dois
ligados ao mesmo tempo). A imagem `vm` segue fora do ciclo (P-81).

**Escopo reduzido (decisão do usuário, 2026-11-18):** o menu do sistema pelo Fn, a dica do Fn
no rodapé do Dock, a dica dos atalhos e o reiniciar pelo código 66 (antigas 1.2, parte da 1.3,
3.1, 3.2, 3.3 e 3.4) passaram para a change `device-fixes` (D19 de lá, tarefas 3.5 e 9.10 a
9.13, junto com o Suspender e a saída do RetroArch das Configurações), com os mesmos modelos
aprovados. Esta change fica com as cores e os logos dos consoles.

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7` e `ARCH:aarch64` (um `lume pkg` por arquitetura), `GA36`, `R36S`, `USUARIO`
(ação física ou olho humano), `MERGE` (um merge por vez, seguido de `cargo test` do `lume/`,
`pytest tests/unit` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, aprovação do usuário).

**Depende da `device-fixes`:** o protótipo e o `lume-ui` desta change partem do launcher com o
menu do sistema da `device-fixes` já mesclado.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | sonnet | 0 | |
| 1.4 | — | — | AG | sonnet | 0 | |
| 1.3 | 1.4 | USUARIO | AG+PR | sonnet | 1 | |
| 2.2 | 1.1 | — | AG | sonnet | 1 | J1, J2 |
| 2.1 | 1.1, 1.3, 1.4 | — | AG | sonnet | 2 | J1, J2 |
| 3.1 | — | USUARIO | AG+PR | sonnet | 0 | |
| 2.3 | 3.1 (protótipo) | — | AG | sonnet (a aprovar) | 2 | J1, J2 |
| 3.2 | `device-fixes` 9.1 | — | AG | sonnet (a aprovar) | 1 | J1, J2 |
| 3.3 | 3.1, 3.2 | — | AG | sonnet (a aprovar) | 2 | J1, J2 |
| 4.1 | 2.1, 2.2, 3.3 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 3 | |
| 4.2 | 4.1 | GA36, USUARIO | PR | — | 4 | J1 |
| 4.3 | 4.2 | R36S, USUARIO | PR | — | 5 | J2 |

Modelos aprovados pelo usuário em 2026-11-17.

**Trilhas e caminho crítico:**

```
  1.4 (cores oficiais) --> 1.3 (protótipo, USUARIO) --+--> 2.1 (cores no Dock) --+
                                 ^                    |                          |
  1.1 (formato do tema) ---------+--------------------+--> 2.2 (logo colorido) --+--> 4.1 build
                                                                                       |
                                                                                       v
                                                                          4.2 GA36 (J1) --> 4.3 R36S (J2)

  caminho crítico: 1.4 -> 1.3 -> 2.1 -> 4.1 -> 4.2 -> 4.3
```

**Ondas:**
- Onda 0: 1.1, 1.4, 3.1 (AG, em paralelo; a 3.1 termina com a escolha e a aprovação do usuário).
- Onda 1: 1.3 (termina com a aprovação do usuário), 2.2, 3.2.
- Onda 2: 2.1, 3.3.
- Onda 3: 4.1 (build dos pacotes, fila única de CPU).
- Onda 4: 4.2 (janela J1). Onda 5: 4.3 (janela J2).

**Janelas de aparelho:**
- **J1** (GA36, build da 4.1): o Dock contra o protótipo, as cores por console, as conferências
  da P-70 do GA36. O usuário navega e confere a tela.
- **J2** (R36S, o mesmo cartão): as mesmas provas e as medições da P-70 do R36S.

## 1. Interfaces congeladas e protótipo

- [ ] 1.1 Congelar o formato do tema para as cores e os logos (D6, D7): tabela `[systems.<id>]` com `icon_bg`, `icon_fg`, `icon_sel_bg` e `icon_sel_fg`, resolução chave a chave (sistema no tema, na cadeia `extends`, depois o token geral), e `icons/<sistema>.color.png` com prioridade sobre a máscara do mesmo tema; parser e validação no carregamento do tema (sistema fora do catálogo é aviso, cor inválida é erro e cai para o herdado, chave desconhecida é aviso); `docs/lume-launcher/formato-de-tema.md` atualizado (tabela de tokens, exemplo, ordem de busca do logo colorido, "a distro não traz logos coloridos"). Verificação: testes de unidade do tema (herança de uma chave só, sistema sem tabela usa o geral, cor inválida cai para o herdado e registra erro, `.color.png` antes da máscara, busca na cadeia `extends`).
- [ ] 1.3 Tela nova no protótipo (`docs/lume-launcher/prototipo/`, D5): o Dock do tema Lume com as cores por console da 1.4, nos temas do protótipo e nos três idiomas; medidas a 640x480 numa tabela no `docs/lume-launcher/design-das-telas.md`. (O menu do sistema e as dicas do Fn estão no protótipo da `device-fixes` 4.1.) Verificação: o usuário aprova a tela no navegador a 640x480 (aprovação anotada na tabela com a data).
- [ ] 1.4 Tabela das cores oficiais dos logos dos sistemas do catálogo (D6): para cada sistema com logo oficial conhecido, `icon_bg`/`icon_fg` e o par de foco, com a fonte de cada cor (guia de marca ou logo oficial publicado) e o contraste entre `icon_fg` e `icon_bg` de pelo menos 3:1; a tabela vai para o `theme.toml` do tema Lume como `[systems.*]`, com a fonte em comentário. Verificação: teste de unidade que lê o tema Lume e confere o contraste de cada sistema e que todo sistema da tabela existe no catálogo; a revisão das cores é a aprovação da 1.3.

## 2. Cores e logos no Dock

- [ ] 2.1 `lume-ui`, cores por console (D6): o tile, a máscara do logo e a sigla usam os tokens resolvidos do sistema, normal e em foco; temas sem `[systems.*]` desenham como hoje. Verificação: testes de tela em `lume/lume-ui/tests/ui.rs` com o tema Lume (cor do SNES e do Mega Drive no tile e no foco, conferidas contra a tabela da 1.3) e com o Material escuro (cor geral em todos); no aparelho, captura do Dock comparada com o protótipo (J1, J2).
- [ ] 2.2 `lume-ui`, logo colorido do cartão (D7): `icons/<sistema>.color.png` desenhado como imagem RGBA, reduzido ao tamanho do tile na decodificação, com prioridade sobre a máscara e a mesma busca na cadeia `extends`; o teto do cache de ícones vale para os dois tipos; teste do pacote que recusa qualquer PNG em `themes/` da imagem. Verificação: testes de unidade (um tema de teste com `snes.color.png` e `nes.png`: SNES colorido, NES em máscara; cache dentro do teto com logos grandes) e o teste do pacote; no aparelho, um tema do cartão com um logo colorido (J1).

- [ ] 2.3 (Protótipo feito e mesclado em 2026-11-18: o contador numa linha própria entre o nome em foco e as dicas, alinhado à direita, x da borda direita 620,8 e y 418,7; a grade perde 23 px e mantém 2 fileiras. Visto pelo usuário na captura da grade; falta a aprovação formal ao retomar a change.) Contador de jogos na lista (pedido do usuário, 2026-11-18): o contador sai do meio do rodapé e vai para o canto inferior direito, logo acima das dicas dos botões, sem cobrir as dicas nem o nome do jogo em foco; primeiro no protótipo (com a 3.1), depois no `lume-ui`. Verificação: o usuário aprova no navegador; teste de tela e de régua da grade (o `footer_centered_and_counter_in_the_middle` muda para a posição nova); no aparelho, J1 e J2.

## 3. Relógio na tela e acerto da hora (P-102, incluído pelo usuário em 2026-11-18)

- [ ] 3.1 (Protótipo feito e mesclado em 2026-11-18, `docs/lume-launcher/prototipo/` e a seção "Relógio e acerto da hora" do `design-das-telas.md`. **Decidido pelo usuário:** posição **B, canto superior esquerdo** (visto no Dock e na grade). **Guardado para a retomada desta change, ainda a responder:** (a) unificar a altura do cabeçalho do Dock com a das outras telas (hoje a bateria e o relógio ficam 9 a 11 px mais altos no Dock; unificar move a bateria já aprovada) ou deixar assim; (b) a data no acerto, `AAAA-MM-DD` em todos os idiomas ou `DD/MM/AAAA` em pt e es; (c) 24 h sempre ou 12 h em inglês; (d) relógio ligado ou desligado de fábrica (o protótipo usa ligado); (e) o L1/R1 nos campos do acerto, que o subagente acrescentou sem pedido: manter ou tirar. Falta a aprovação final das telas no navegador.) Protótipo do relógio (`docs/lume-launcher/prototipo/`): 2 ou 3 variações de posição (ao lado da bateria no canto superior direito, no canto superior esquerdo, centralizado no topo) para o usuário escolher; formato de 24 h; nas Configurações, as linhas "Mostrar relógio" (interruptor) e "Acertar a hora" (seletores de data e hora pelo direcional, com confirmação vertical); o estado "hora nunca acertada" sem relógio; nos temas e nos três idiomas; medidas a 640x480 no `docs/lume-launcher/design-das-telas.md`. Verificação: o usuário escolhe a posição e aprova as telas no navegador (aprovação anotada com a data).
- [ ] 3.2 Pedido de acerto da hora (o `lume-ui` roda como `game`): um pedido em `/run/lume/clock/` atendido por um serviço root que chama `lume-clock set <epoch> manual` (o `lume-clock` da `device-fixes` 9.1, que grava o sistema, o RTC e o `ROMS/system/clock`); a marca "hora já acertada por uma fonte real" guardada pelo `lume-clock` e lida pelo `lume-ui`. Verificação: testes do shell com relógio falso (pedido válido acerta e marca, pedido inválido recusado e registrado) e do leitor da marca.
- [ ] 3.3 `lume-ui`, relógio e Configurações: o relógio no lugar aprovado em todas as telas, redesenhado uma vez por minuto só com a tela acesa, escondido sem a marca da 3.2; as linhas "Mostrar relógio" e "Acertar a hora"; textos en/pt/es. Verificação: testes de tela (mesmo lugar em cada tela, desligado some, sem marca não aparece, acerto grava o pedido, régua igual à tabela da 3.1); no aparelho, J1 e J2.

## 4. Build e provas nos consoles

- [ ] 4.1 Build dos pacotes mudados (`lume-launcher`, `lume-core` e o pacote do tema, se separado) nas duas arquiteturas, um `lume pkg` por vez sob a proteção de calor, e `lume push` para o cartão. Verificação: os `.apk` novos com o `pkgrel` novo no repositório local e o `push` terminando com `ok`.
- [ ] 4.2 Janela J1 no GA36 (D8): (a) o Dock com as cores por console contra o protótipo, com capturas pelo `lume-shot`; (b) a linha de volume e brilho sobre um jogo do RetroArch, nas cores do tema; (c) tempo até o primeiro quadro de um jogo; (d) um tema do cartão com um logo colorido. Verificação: resultado anotado no `docs/BRINGUP-GA36.md`, sem nome de jogo; o que falhar vira tarefa aqui.
- [ ] 4.3 Janela J2 no R36S, com o mesmo cartão: as mesmas provas da 4.2, mais as medições da 9.6 da `lume-launcher` (CPU e memória com o launcher parado, tempo do fim do jogo até a grade, tempo de boot), o nome do sensor de temperatura no painel Sistema (`soc-thermal` esperado) e a mancha clara nas bordas num fundo liso (observar; se aparecer, captura e registro na P-70). Verificação: resultado anotado no `docs/BRINGUP-R36S.md`, sem nome de jogo; P-70, P-72, P-74 e P-84 movidos para "Concluídas" no `docs/PENDENCIAS.md` com o nome desta change (o que sobrar da P-70 vira P-NN nova).

## Workflow follow-up

- Arquivar a change depois das provas da J1 e da J2.

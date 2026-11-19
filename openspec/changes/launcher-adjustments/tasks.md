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
| 2.4 | — | USUARIO | AG+PR | sonnet (a aprovar) | 0 (protótipo), 2 (código) | J1, J2 |
| 3.2 | `device-fixes` 9.1 | — | AG | sonnet (a aprovar) | 1 | J1, J2 |
| 3.3 | 3.1, 3.2 | — | AG | sonnet (a aprovar) | 2 | J1, J2 |
| 5.1 | — | USUARIO | AG+PR | sonnet (a aprovar) | 0 | |
| 5.2 | — | — | AG | opus (a aprovar: toca o boot e o fim da sessão) | 1 | J1, J2 |
| 5.3 | 5.1, 5.2 | — | AG | sonnet (a aprovar) | 2 | J1, J2 |
| 6.1 | — | USUARIO | AG+PR | sonnet (a aprovar) | 0 | |
| 6.2 | — | GA36 | AG+PR | opus (a aprovar: root e senhas) | 1 | J1 |
| 6.3 | 6.1, 6.2 | — | AG | sonnet (a aprovar) | 2 | J1, J2 |
| 7.1 | — | USUARIO | AG+PR | sonnet (a aprovar) | 0 | |
| 7.2 | `device-fixes` 3.4 | — | AG | opus (a aprovar: caminho de som do jogo) | 1 | J1, J2 |
| 7.3 | 7.1, 7.2 | — | AG | sonnet (a aprovar) | 2 | J1, J2 |
| 8.1 | — | USUARIO | AG+PR | sonnet (a aprovar) | 0 | |
| 8.2 | 8.1, `device-fixes` 9.9 | — | AG | sonnet (a aprovar) | 1 | J1, J2 |
| 9.1 | — | — | AG | sonnet (a aprovar) | 1 | J1, J2 |
| 10.1 | — | — | AG | sonnet (a aprovar) | 1 | J1, J2 |
| 4.1 | 2.1, 2.2, 2.3, 3.3, 5.3, 6.3, 7.3, 8.2, 9.1, 10.1 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 3 | |
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
- Onda 0: 1.1, 1.4, 3.1, 5.1, 6.1, 7.1, 8.1 (AG, em paralelo; os protótipos terminam com a aprovação do usuário).
- Onda 1: 1.3 (termina com a aprovação do usuário), 2.2, 3.2, 5.2, 6.2, 7.2, 8.2, 9.1, 10.1.
- Onda 2: 2.1, 2.3, 3.3, 5.3, 6.3, 7.3.
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

- [ ] 2.4 Zona de risco do brilho na barra (pedido do usuário, 2026-11-18): o GA36 ficou com os 10 níveis liberados (sem o `backlight_max`, só o `backlight_boot 7` para o boot sem brilho salvo); a barra do brilho (a linha da borda esquerda do Fn + volume, desenhada pelo `lume-menu` e pelo patch 0011 do RetroArch, e a barra de Brilho das Configurações) mostra os níveis a partir de um limite do perfil (proposta: `backlight_warn 8` no `ga36.conf`) em outra cor (vermelho ou âmbar do tema), ou um ponto no limite; as duas variações no protótipo primeiro, para o usuário escolher. O aprendizado do limite por aparelho continua na change do P-95. Verificação: o usuário escolhe e aprova no navegador; testes de tela e do `lume-input` (a linha nova, a cor na zona); no aparelho, J1 e J2.

## 3. Relógio na tela e acerto da hora (P-102, incluído pelo usuário em 2026-11-18)

- [ ] 3.1 (Protótipo feito e mesclado em 2026-11-18, `docs/lume-launcher/prototipo/` e a seção "Relógio e acerto da hora" do `design-das-telas.md`. **Decidido pelo usuário:** posição **B, canto superior esquerdo** (visto no Dock e na grade). **Guardado para a retomada desta change, ainda a responder:** (a) unificar a altura do cabeçalho do Dock com a das outras telas (hoje a bateria e o relógio ficam 9 a 11 px mais altos no Dock; unificar move a bateria já aprovada) ou deixar assim; (b) a data no acerto, `AAAA-MM-DD` em todos os idiomas ou `DD/MM/AAAA` em pt e es; (c) 24 h sempre ou 12 h em inglês; (d) relógio ligado ou desligado de fábrica (o protótipo usa ligado); (e) o L1/R1 nos campos do acerto, que o subagente acrescentou sem pedido: manter ou tirar. Falta a aprovação final das telas no navegador.) Protótipo do relógio (`docs/lume-launcher/prototipo/`): 2 ou 3 variações de posição (ao lado da bateria no canto superior direito, no canto superior esquerdo, centralizado no topo) para o usuário escolher; formato de 24 h; nas Configurações, as linhas "Mostrar relógio" (interruptor) e "Acertar a hora" (seletores de data e hora pelo direcional, com confirmação vertical); o estado "hora nunca acertada" sem relógio; nos temas e nos três idiomas; medidas a 640x480 no `docs/lume-launcher/design-das-telas.md`. Verificação: o usuário escolhe a posição e aprova as telas no navegador (aprovação anotada com a data).
- [ ] 3.2 Pedido de acerto da hora (o `lume-ui` roda como `game`): um pedido em `/run/lume/clock/` atendido por um serviço root que chama `lume-clock set <epoch> manual` (o `lume-clock` da `device-fixes` 9.1, que grava o sistema, o RTC e o `ROMS/system/clock`); a marca "hora já acertada por uma fonte real" guardada pelo `lume-clock` e lida pelo `lume-ui`. Verificação: testes do shell com relógio falso (pedido válido acerta e marca, pedido inválido recusado e registrado) e do leitor da marca.
- [ ] 3.3 `lume-ui`, relógio e Configurações: o relógio no lugar aprovado em todas as telas, redesenhado uma vez por minuto só com a tela acesa, escondido sem a marca da 3.2; as linhas "Mostrar relógio" e "Acertar a hora"; textos en/pt/es. Verificação: testes de tela (mesmo lugar em cada tela, desligado some, sem marca não aparece, acerto grava o pedido, régua igual à tabela da 3.1); no aparelho, J1 e J2.

## 5. Telas de carregamento com barra de progresso (P-100, incluído pelo usuário em 2026-11-18)

- [ ] 5.1 Protótipo das telas de carregamento (`docs/lume-launcher/prototipo/`): (1) inicialização do sistema; (2) carregamento do jogo, do A no launcher até o primeiro quadro; (3) finalização do jogo, da gravação da SRAM até a volta ao launcher; (4) encerramento e reinício do sistema; (5) tarefa demorada genérica (verificação e TRIM do cartão, indexação das listas, `push`, migrações). Todas com barra de progresso; **o tipo de barra de cada tela é decidido com o usuário tela a tela** (por etapas conhecidas, por bytes, ou indeterminada quando não há como medir); temas, três idiomas e medidas a 640x480 no `design-das-telas.md`. Verificação: o usuário aprova cada tela e o tipo de barra no navegador (aprovação anotada com a data).
- [ ] 5.2 Fonte do progresso: um protocolo único e barato para quem tem etapas publicar o andamento (por exemplo um arquivo em `/run/lume/progress/` com etapa, total e texto, lido pela tela), usado pelo boot (só as etapas que ele já registra: nada novo no caminho do boot, P-58), pelo `lume-run` (core carregado, conteúdo carregado, primeiro quadro pelo contador de quadros), pelo fim da sessão (gravar, `sync`, remontar, desligar) e pelos scripts demorados. Verificação: testes do formato e de cada publicador com relógio falso; o boot não fica mais lento (tempo de boot medido antes e depois na J1).
- [ ] 5.3 Desenho das telas no sistema (o `lume-ui` ou uma tela leve própria onde o `lume-ui` ainda não roda, como no initramfs e no fim do boot), no tema ativo, com a barra aprovada na 5.1. Verificação: testes de tela de cada uma com o progresso falso da 5.2 e a régua igual à tabela da 5.1; no aparelho, J1 e J2 (cada tela vista, sem piscar entre elas e o launcher ou o jogo).

## 6. Wi-Fi completo nas Configurações (P-66, incluído pelo usuário em 2026-11-18)

- [ ] 6.1 Protótipo do painel Wi-Fi: ligar e desligar, rede conectada (nome e endereço), procurar redes (nome, sinal, cadeado), redes salvas com Conectar e Esquecer, e o teclado da tela para a senha (maiúsculas, números e símbolos, mostrada como pontos); temas, três idiomas, régua a 640x480. Verificação: o usuário aprova no navegador.
- [ ] 6.2 Acesso à rede pelo usuário `game`: conferir no GA36 se o `nmcli` liga, procura, conecta e apaga sem polkit e se as redes sobrevivem ao reboot; senão, o ajudante root `lume-netd` (verbos fixos, socket em `/run/lume/`, senha por stdin ou arquivo `0600`, nunca em argumento nem log); autoconexão no boot e quando o adaptador aparece, fora do caminho do boot. Verificação: testes com backend falso (lista, conectar, senha errada, esquecer, argv sem a senha).
- [ ] 6.3 `lume-ui`, painel Wi-Fi e teclado da tela, com as chamadas numa thread com tempo limite. Verificação: testes de tela com o backend falso; no aparelho (J1), conectar com o dongle RTL8821CU, reboot com a rede salva, e a prova do SSH pela rede (código novo derruba o antigo, `root` sem senha recusado).

## 7. Bluetooth nas Configurações, com foco em fone (P-67, incluído pelo usuário em 2026-11-18)

- [ ] 7.1 Protótipo do painel Bluetooth: ligar e desligar, pareados (Conectar, Desconectar, Esquecer), procurar só a pedido (15 s, fones primeiro), escolher = parear, confiar e conectar. Verificação: o usuário aprova no navegador.
- [ ] 7.2 Som no fone Bluetooth com `bluez-alsa` (sem PulseAudio nem PipeWire): o ALSA padrão vai para o fone enquanto conectado e volta ao alto-falante quando ele cai, sem reiniciar o jogo; as teclas de volume mexem no fone (uma saída a mais na escala da `device-fixes` 3.4); latência do A2DP medida. Verificação: testes com backend falso da troca de saída; no aparelho (J1), som do launcher e de um jogo no fone e a volta ao alto-falante.
- [ ] 7.3 `lume-ui`, painel Bluetooth; um controle pareado pelo painel continua virando o jogador seguinte. Verificação: testes de tela com backend falso; no aparelho (J1), parear um fone e um controle.

## 8. Modo avançado: acesso completo ao RetroArch (P-101, incluído pelo usuário em 2026-11-18)

- [ ] 8.1 Protótipo da opção "Modo avançado" nas Configurações (com confirmação vertical e aviso do que muda); o que o modo libera além do RetroArch fica decidido com o usuário no protótipo. Verificação: o usuário aprova no navegador.
- [ ] 8.2 Com o modo ligado, o script do frontend desliga a `lume_menu_lock` (patch da `device-fixes` 9.9) e mostra de novo os itens da tela principal do RetroArch; com ele desligado, volta a trava; o valor fica no cartão e vale a partir do próximo jogo. Verificação: testes do script (as chaves certas em cada modo, o valor sobrevive ao reboot); no aparelho (J1), entrar na tela principal do RetroArch só com o modo ligado.

## 9. Idioma do RetroArch igual ao do launcher (P-107, pedido do usuário em 2026-11-19)

- [ ] 9.1 O idioma do launcher manda; o RetroArch sempre segue. Hoje a troca em Configurações → Idioma já grava o `user_language` no `retroarch.cfg` do cartão (`set_retroarch_language`, `lume/lume-ui/src/app.rs`), mas só no momento da troca. Fazer: (a) reconciliar ao subir o launcher e antes de cada jogo do RetroArch: se o `user_language` do cartão não corresponde ao idioma do launcher (`retroarch_language` do `lume-core`), regravar com a mesma escrita atômica e uma linha no log; cobre o `retroarch.cfg` restaurado de fábrica (`user_language = "0"`), o cartão vindo de outro console e uma troca feita fora do Lume; (b) o idioma do RetroArch fora do menu dele: a opção de idioma escondida mesmo no "Modo avançado" (8.2), ou, se o usuário preferir mantê-la lá, uma troca feita no RetroArch é desfeita no jogo seguinte pela reconciliação (a), e o `docs/FRONTEND.md` diz que o idioma vem do Lume; (c) o `ui_lang` do `lib.sh` (mensagens de tela dos serviços) passa a ler o idioma do launcher, a mesma fonte, e não o `user_language`. Verificação: testes do `lume-ui` (launcher em `pt` com o cartão em `"0"` regrava `"7"` ao subir; já igual não escreve; a troca de idioma regrava como hoje) e do `lib.sh` (`ui_lang` igual ao idioma do launcher); teste do `retroarch-lume.cfg` (a opção de idioma escondida, se for o caminho escolhido); no aparelho, pelo cabo: trocar o idioma no launcher pelo `dev keys` e conferir o `user_language` e o menu do RetroArch no idioma novo pelo `dev shot`; restaurar o `retroarch.cfg` de fábrica e conferir a reconciliação no jogo seguinte (J1, J2).

## 10. RetroArch sem os comandos que ficaram sem uso (decisão do usuário, 2026-11-19)

- [ ] 10.1 O patch `aports/retroarch/0012-lume-hud-hint-menu.patch` (da `lume-hud-actions` 4.3 e 4.5) acrescentou os comandos `LUME_HUD` e `LUME_HINT` e os widgets da barra e da dica no RetroArch; desde a mudança de escopo de 2026-11-17/18 (tudo sobre o jogo vem do sistema) quem desenha a barra e a dica é o `lume-menu`, e o `lume-run` nunca manda esses comandos (`lume/lume-run/tests/run.rs` garante). Fazer: tirar do patch os comandos `LUME_HUD` e `LUME_HINT` e os dois widgets, mantendo o `LUME_MENU` (reserva do menu quando o `lume-menu` falha, D14 da `lume-hud-actions`); `pkgrel` novo do `retroarch`; os comentários do `lume-menu/src/bar.rs` e do `lume-run/src/menu.rs` que citam os comandos atualizados. Verificação: `tests/unit/test_retroarch_patches.py` (o patch aplica sobre a versão fixada, só o `LUME_MENU` registrado); o build do RetroArch nas duas arquiteturas entra na 4.1; no aparelho, pelo cabo, a barra e a dica do `lume-menu` continuam e o menu de reserva ainda abre com o `lume-menu` ausente (J1, J2).

## 4. Build e provas nos consoles

- [ ] 4.1 Build dos pacotes mudados (`lume-launcher`, `lume-core`, o `retroarch` da 10.1 e o pacote do tema, se separado) nas duas arquiteturas, um `lume pkg` por vez sob a proteção de calor, e `lume push` para o cartão. Verificação: os `.apk` novos com o `pkgrel` novo no repositório local e o `push` terminando com `ok`.
- [ ] 4.2 Janela J1 no GA36 (D8): (a) o Dock com as cores por console contra o protótipo, com capturas pelo `lume-shot`; (b) a linha de volume e brilho sobre um jogo do RetroArch, nas cores do tema; (c) tempo até o primeiro quadro de um jogo; (d) um tema do cartão com um logo colorido. Verificação: resultado anotado no `docs/BRINGUP-GA36.md`, sem nome de jogo; o que falhar vira tarefa aqui.
- [ ] 4.3 Janela J2 no R36S, com o mesmo cartão: as mesmas provas da 4.2, mais as medições da 9.6 da `lume-launcher` (CPU e memória com o launcher parado, tempo do fim do jogo até a grade, tempo de boot), o nome do sensor de temperatura no painel Sistema (`soc-thermal` esperado) e a mancha clara nas bordas num fundo liso (observar; se aparecer, captura e registro na P-70). Verificação: resultado anotado no `docs/BRINGUP-R36S.md`, sem nome de jogo; P-70, P-72, P-74, P-84 e P-107 movidos para "Concluídas" no `docs/PENDENCIAS.md` com o nome desta change (o que sobrar da P-70 vira P-NN nova).

## Workflow follow-up

- Arquivar a change depois das provas da J1 e da J2.

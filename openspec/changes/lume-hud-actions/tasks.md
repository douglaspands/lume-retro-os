# Tasks

Verificação desta change: testes de unidade (Python, Rust, C pelo `--test` do `r36os-input` e
shell), o protótipo do launcher no navegador (tela nova do menu do Lume) e o aparelho (GA36 e
R36S, com um único cartão passado de um console ao outro: nunca os dois ligados ao mesmo
tempo). A imagem `vm` segue fora do ciclo (P-81); o `vm.conf` é mantido coerente, mas não é
provado aqui.

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7` e `ARCH:aarch64` (um `r36os pkg` por arquitetura), `GA36`, `R36S`, `USUARIO`
(ação física ou olho humano), `MERGE` (um merge por vez em `feature/lume-hud-actions`, seguido
de `pytest tests/unit`, `cargo test` do `lume/` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, aprovação do usuário).

**Ordem de merge que importa:** a 5.1 (tira o botão do menu do RetroArch) só é mesclada depois
da 2.1 e da 3.1, para nunca existir um build em que o menu não abre por nenhum caminho. A 3.1
deixa o laço do `lume-run` com prazo e despacho por mensagem, e a 3.3 e a 4.2 entram como
módulos próprios (`menu.rs`, `hud.rs`), para os dois nós da onda 2 não brigarem no `main.rs`.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | opus | 0 | |
| 1.2 | — | — | AG | sonnet | 0 | |
| 1.3 | — | USUARIO | AG+PR | sonnet | 0 | |
| 2.1 | 1.1 | — | AG | opus | 1 | J2, J3 |
| 2.2 | 2.1 | — | AG | opus | 2 | J2, J3 |
| 3.1 | 1.1, 1.2 | — | AG | sonnet | 1 | J2, J3 |
| 3.2 | 1.2 | — | AG | sonnet | 1 | J2, J3 |
| 3.3 | 1.1, 1.3, 3.1 | — | AG | sonnet | 2 | J2, J3 |
| 4.1 | — | GA36, R36S, USUARIO | PR | — | 0 | J1 |
| 4.2 | 3.1, 4.1 | — | AG | sonnet | 2 | J2, J3 |
| 4.3 | — | — | AG | opus | 0 | J2, J3 |
| 4.4 | 4.1 | — | AG | sonnet | 1 | J3 |
| 4.5 | 1.3, 4.3, 4.6 | — | AG | opus | 2 | J2, J3 |
| 4.6 | — | GA36, R36S, USUARIO | AG+PR | opus | 0 | J1 |
| 3.4 | 1.3, 3.3, 4.6 | — | AG | opus | 3 | J2, J3 |
| 5.1 | 2.1, 3.1 | — | AG | sonnet | 2 | J2, J3 |
| 6.1 | 2.2, 3.2, 3.3, 3.4, 4.2, 4.4, 4.5, 5.1 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 4 | |
| 6.2 | 6.1 | GA36, USUARIO | PR | — | 5 | J2 |
| 6.3 | 6.2 | R36S, USUARIO | PR | — | 6 | J3 |

Modelos aprovados pelo usuário em 2026-11-17.

**Trilhas e caminho crítico:**

```
  1.1 (protocolo) --+--> 2.1 (acordes) --> 2.2 (captura) ---------------------+
                    |                                                           |
  1.2 (ações) ------+--> 3.1 (lume-run ações) --+--> 3.3 (menu do Lume) -------+
                    |                           |         ^                     |
                    +--> 3.2 (lume-ui, toml)    +--> 4.2 (barra)               +--> 6.1 build
                                                |         ^                     |      |
  1.3 (protótipo do menu, USUARIO) -------------+---------+--> 4.5 (widget menu)+      v
                                                |              ^                |    6.2 GA36 (J2)
  4.3 (patch: widget da barra) -----------------+--------------+                |      |
                                                                                |      v
  4.1 (prova sysfs, J1) --> 4.2, 4.4 (udev panfrost) ---------------------------+    6.3 R36S (J3)
  2.1 + 3.1 --> 5.1 (cfg RA) ---------------------------------------------------+
  4.6 (prova: menu pelo sistema, J1) --> 3.4 (lume-menu) ou 4.5 (reserva) ------+

  caminho crítico: 1.1 -> 3.1 -> 3.3 -> 3.4 -> 6.1 -> 6.2 -> 6.3
```

**Ondas:**
- Onda 0: 1.1, 1.2, 1.3, 4.3 (AG, em paralelo); 1.3 termina com a aprovação do usuário; 4.1
  e 4.6 (janela J1 com o build atual; o programa de prova da 4.6 é escrito por AG antes).
- Onda 1: 2.1, 3.1, 3.2, 4.4.
- Onda 2: 2.2, 3.3, 4.2, 4.5 (sem o `LUME_MENU` se a 4.6 passou), 5.1.
- Onda 3: 3.4 (só se a 4.6 passou; senão a task registra o resultado e fica marcada).
- Onda 4: 6.1 (build dos pacotes, fila única de CPU).
- Onda 5: 6.2 (janela J2). Onda 6: 6.3 (janela J3).

**Janelas de aparelho:**
- **J1** (build atual, sem código novo no sistema): GA36 e depois R36S, o mesmo cartão. Ler
  pelo cabo (`r36os dev`) o `fdinfo` do RetroArch num jogo e os campos da bateria, com e sem
  o carregador; rodar o programa de prova da 4.6 (menu pelo sistema). O usuário liga o
  console, abre um jogo do RetroArch e um Port, liga/desliga o carregador e confere a tela.
- **J2** (GA36, build da 6.1): todos os atalhos, o menu do Lume, a foto do jogo, a foto do save
  state, a barra e o custo dela. O usuário joga e confere a tela.
- **J3** (R36S, o mesmo cartão): as mesmas provas da J2.

## 1. Interfaces congeladas e protótipo

- [x] 1.1 Congelar o protocolo do `/run/r36os/input.sock` (D2, D11) e o formato `chord <código> <ação>` dos perfis (D1): do daemon `quit`, `app_menu`, `save_state`, `load_state`, `screenshot`, `hud`, `fn_tap`, `fn_hold <tabela>` (D13), `fn_release`, `volume`, `brightness` e `nav up|down|left|right|a|b`; do cliente `tap <KEY_*>`, `capture on` e `capture off`; uma mensagem por linha; a linha antiga `quit <código>` lida como `chord <código> quit`; `fn_hold_ms` no perfil (padrão 500). Um módulo Rust no `lume-core` com o parser das mensagens e o comentário do cabeçalho do `input.c` atualizados juntos. Verificação: testes de unidade em Rust (mensagens válidas, `fn_hold` com a tabela lida em pares botão=ação, desconhecidas ignoradas, `tap` com código fora de `KEY_*` recusado) e um teste do parser de perfis do `r36os-input` em modo `--test` com `chord` e com `quit` antigo.
- [x] 1.2 Congelar as ações do runner (D3): `[runner.actions]` com `pause`, `app_menu`, `reset`, `save_state`, `load_state` e `screenshot`, valores `retroarch-cmd:<CMD>`, `key:<KEY_*>` e `signal:<NOME>`, e `retroarch-pause` só para `pause`, e o campo `overlay = "retroarch"`, validados no `lume-core/src/runner.rs`; linhas `action=<ação> <forma>` e `overlay=` no arquivo de lançamento, lidas pelo `lume-run/src/launch.rs`; `docs/LAUNCHER.md` com o formato. Verificação: testes de unidade (runner sem ações válido, valor inválido recusado com a mensagem, ação ou `overlay` desconhecidos recusados, arquivo de lançamento com e sem as linhas novas).
- [ ] 1.3 Telas do menu do Lume e da dica dos acordes sobre o jogo no protótipo (`docs/lume-launcher/prototipo/`, D10, D13), na família do menu do jogo do launcher: lista (Voltar ao jogo, Encerrar jogo, Reiniciar, Menu do RetroArch: ordem pedida pelo usuário em 2026-11-17), confirmação com Não em foco, a dica com uma linha por acorde (glifo do botão e nome da ação), sobre uma imagem de jogo de exemplo, nos temas do protótipo e nos três idiomas; as medidas a 640x480 (posições, tamanhos, fontes, cores dos tokens) anotadas numa tabela no `docs/lume-launcher/design-das-telas.md`. Verificação: o usuário aprova a tela no navegador a 640x480 (a aprovação é anotada na tabela com a data).

## 2. Acordes e captura no daemon de entrada

- [ ] 2.1 `r36os-input`, gestos e acordes (D1, D2, D13): o Fn nunca sai; sozinho vira `fn_tap` (solto antes de `fn_hold_ms`) ou `fn_hold <tabela>` e depois `fn_release` (segurado), com o prazo no `poll` só enquanto o Fn está apertado; um Fn que fez acorde nunca gera `fn_tap` nem `fn_hold`, e um acorde depois do `fn_hold` manda `fn_release` antes da ação; acordes da tabela mandam a ação aos clientes e engolem a tecla; acordes fora da tabela não saem; Fn+volume continua sendo o brilho; `tap <KEY_*>` de um cliente vira pressão e soltura no controle virtual, que passa a declarar as teclas `KEY_*` aceitas; perfis `ga36.conf`, `r36s.conf` e `vm.conf` com a tabela da proposta. Verificação: `tests/unit/test_r36os_input.py` com toque no Fn (só `fn_tap` no socket, nada na saída), Fn segurado 600 ms e solto (`fn_hold` com a tabela e `fn_release`, sem `fn_tap`), Fn segurado e depois R1 (`fn_hold`, `fn_release`, `save_state`), Fn+R1 solto rápido (só `save_state`, sem `fn_tap`), Fn+A (nada sai), Fn+B (`app_menu`, nenhum B), Fn+R1 (`save_state`, nenhum R1), Fn+Y (`screenshot`), Fn+Start (`quit`, sem mudança), Fn+volume (brilho), `tap KEY_F2` (pressão e soltura na saída), perfil com `quit` antigo; no aparelho, nas janelas J2 e J3.
- [ ] 2.2 `r36os-input`, captura (D11): `capture on` solta as teclas apertadas no controle virtual, para de encaminhar e manda `nav ...` ao cliente que pediu; `capture off`, o fim da conexão desse cliente ou 2 s sem mensagem dele voltam a encaminhar; os acordes com Fn continuam valendo durante a captura. Verificação: testes do `r36os-input` em modo `--test` para cada uma das três saídas da captura (nenhum evento preso na saída, encaminhamento de volta), A com a captura ligada vira `nav a` e não sai, Fn+Start com a captura ligada manda `quit`; no aparelho, matar o `lume-run` com o menu aberto devolve o controle em até 2 s (J2, J3).

## 3. Ações e menu do Lume no supervisor

- [ ] 3.1 `lume-run`, ações (D3, D10): o laço do jogo passa a ter prazo e despacho por mensagem (base da 3.3 e da 4.2); pausa e despausa pelo `pause` do runner (`retroarch-pause`: `GET_STATUS` com prazo de 1 s, `PAUSE_TOGGLE` só se `PLAYING`, guarda se pausou e confere com outro `GET_STATUS`; sem `pause`, `SIGSTOP`/`SIGCONT` no grupo) e informa "sem resposta"; "forçar fechamento" manda `SIGKILL` ao grupo sem esperar o prazo; executa `app_menu`, `reset`, `save_state`, `load_state` e `screenshot` pela forma do runner (`retroarch-cmd` por UDP na porta já usada pelo `QUIT`, `key` pedindo `tap` ao socket, `signal` ao grupo do jogo); ação não declarada vira a linha `action <ação> not supported by runner <id>` no log; `quit` sem mudança; `docs/LAUNCHER.md` com a tabela de atalhos. Verificação: testes em `lume/lume-run/tests/run.rs` com um RetroArch falso (servidor UDP de teste recebe `SAVE_STATE`, `SCREENSHOT`, `MENU_TOGGLE`; pausa com ele respondendo `PLAYING` alterna e despausa ao voltar, com `PAUSED` não alterna nada, mudo dá "sem resposta" em até 1 s), um processo de teste congelado e descongelado pelo `SIGSTOP`/`SIGCONT` e morto pelo "forçar fechamento", um socket de entrada falso (recebe `tap KEY_F2`) e um runner sem ações (só a linha no log); no aparelho, nas janelas J2 e J3.
- [ ] 3.2 Lançamento (D3, D4): o `lume-ui` escreve as ações resolvidas e o `overlay` no arquivo de lançamento e, aberto pela grade ou pelo estado automático, passa `--lume-set state_slot=0`; o `runners.d/retroarch.toml` declara as ações e `overlay = "retroarch"`; `love.toml` e `sh.toml` sem nada disso. Verificação: testes de `lume/lume-ui/src/launch.rs` (argv pela grade com `state_slot=0`, pelo slot 3 com `-e 3` e sem `state_slot=0`, ações e `overlay` no arquivo) e do catálogo (`tests/unit/test_catalog.py` lê o `retroarch.toml` novo); no aparelho, Fn+R1 num jogo aberto pelo slot 3 grava no slot 3 (J2, J3).
- [ ] 3.3 `lume-run`, menu do Lume e dica dos acordes (D10, D13), em módulo próprio: `fn_tap` abre e fecha o menu; `fn_hold` monta a dica com as ações que o runner declara mais Fn+Start, nos três idiomas, e manda `LUME_HINT` (renovado a cada 1 s), `fn_release` ou uma ação de acorde a esconde, e com o menu aberto o `fn_hold` é ignorado; pausa ao abrir e despausa ao voltar (3.1), despausa antes de `reset` e `quit`; com o app sem resposta, a lista ganha "Forçar fechamento"; Reiniciar e Menu da aplicação só aparecem se o runner os declara; o desenho vai pelo `lume-menu` (3.4) ou, se a 4.6 falhar, pelo `LUME_MENU`; os estados fechado, lista e confirmação; `capture on` ao abrir e a cada 1 s, `capture off` ao fechar; `nav` move o foco, A escolhe, B volta; Reiniciar e Encerrar com confirmação e foco em Não; Menu do RetroArch fecha o menu do Lume e manda `app_menu`; Encerrar segue o `polite_quit`; envia `LUME_MENU` a cada mudança e a cada 1 s; textos em en, pt e es no `lume-core`, com o idioma lido como o `lume-ui` lê; runner sem `overlay` ignora `fn_hold` com uma linha no log (e também `fn_tap`, só se a 4.6 falhar). Verificação: testes de unidade da máquina de estados (cada caminho da figura do D10, A em Reiniciar sem mover o foco não reinicia, `fn_tap` fecha de qualquer estado, `fn_hold` com o menu aberto não mostra a dica, runner `sh` com só Voltar ao jogo e Encerrar jogo, pausa não respondida acrescenta "Forçar fechamento"), da dica (runner só com `app_menu` lista Fn+B e Fn+Start) e do texto de `LUME_MENU` e `LUME_HINT` nos três idiomas; no aparelho, J2 e J3.

- [ ] 3.4 `lume-menu` (D14), só se a 4.6 passou: binário novo no `lume/` (Rust, sem SDL), aberto pelo `lume-run` com o jogo já pausado e congelado; `pidfd_getfd` do fd do DRM da aplicação, `GETFB2` do plano primário como fundo, o menu desenhado em software com as medidas da 1.3 e a fonte do tema, commit atômico com nova tentativa por até 200 ms em `EBUSY`; ao fechar, devolve o framebuffer e o estado do plano e sai; recebe o estado do menu (itens, foco) do `lume-run` por stdin, uma linha por mudança; pacote `lume-launcher` com o binário (e o `setcap` se a 4.6 mostrar que precisa); delta da spec `game-runners` conferido (processo só com o menu aberto). Verificação: testes de unidade do desenho (imagem gerada em memória comparada com a tabela da 1.3) e do protocolo de stdin; no aparelho, menu sobre um jogo do RetroArch, um Port e um RetroArch travado de propósito, captura pelo `r36os-shot` comparada com o protótipo, volta ao jogo sem tela preta, e nenhum `lume-menu` no `ps` depois de fechar (J2, J3). Se a 4.6 falhou: anotar aqui o resultado e marcar.

## 4. Barra de status e widgets

- [ ] 4.1 Prova no aparelho, com o build atual (janela J1): no GA36 (`lima`) e no R36S (`panfrost`), as linhas `drm-engine-*` no `/proc/<pid>/fdinfo` do RetroArch num jogo, e no `panfrost` com e sem o `profiling` ligado; os campos da bateria (`current_now` e o sinal dele carregando e descarregando, `voltage_now`, `charge_full`, `charge_now`, `status`) no AXP223 e no RK817. Verificação: tabela por console no `docs/BRINGUP-GA36.md` e no `docs/BRINGUP-R36S.md`, e o ramo do D7 escolhido para cada um anotado no `design.md`.
- [ ] 4.2 `lume-run`, barra (D6, D7), em módulo próprio: `hud` liga e desliga a barra, estado em `/run/r36os/hud` lido no início de cada jogo; com a barra ligada, leitura a cada 1 s de `/proc/stat`, `scaling_cur_freq`, `fdinfo` do jogo, `/proc/meminfo` e da bateria, texto `CPU .. GPU .. MEM u/t/s BAT ..` com `--` e `--:--`, envio de `LUME_HUD`; desligada, `LUME_HUD` vazio e nenhuma leitura; ligar e desligar o `profiling` do `panfrost` quando o sysfs existir; runner sem `overlay` ignora `hud`; `docs/LAUNCHER.md` com o formato da barra. Verificação: testes de unidade com árvores falsas de `/proc` e `/sys` (CPU, GPU de `lima` e de `panfrost`, MEM `124/1006/200`, bateria descarregando, carregando, sem `charge_full`, menos de 30 s de amostras dá `--:--`), teste de que, escondida, não há leitura; no aparelho, custo e RSS nas janelas J2 e J3.
- [ ] 4.3 Patch numerado do RetroArch (D8), no molde do 0011, primeira parte: comando `LUME_HUD [texto]` e o widget da faixa no topo, fundo semitransparente, sem mudar o viewport, sumindo em 3 s sem atualização; `APKBUILD` com o patch e o `pkgrel` novo. Verificação: `tests/unit/test_retroarch_patches.py` (patch listado, aplica sobre a versão fixada, comando registrado); a barra legível a 640x480 nas janelas J2 e J3.
- [ ] 4.4 Regra do udev para o `profiling` do `panfrost` gravável pelo grupo `video`, se a 4.1 mostrar que é preciso (senão, a task registra que não foi e fica marcada). Verificação: teste da regra como o da `90-lume-backlight.rules`; no R36S, `GPU` com número na barra (J3).
- [ ] 4.5 Patch do RetroArch, segunda parte (D8, D13): comando `LUME_HINT [linhas]` e o widget da dica (sem pausar o jogo, some em 3 s sem atualização) e, **só se a 4.6 falhou**, comando `LUME_MENU [título|itens|foco]` e o widget do menu do Lume (sem pausar: a pausa é do `lume-run`), com as medidas aprovadas na 1.3 (constantes anotadas com a origem na tabela do protótipo); some em 3 s sem atualização. Verificação: `tests/unit/test_retroarch_patches.py` (comando registrado, constantes iguais à tabela da 1.3); no aparelho, captura pelo `r36os-shot` comparada com o protótipo (1 px de tolerância a 640x480) e o jogo parado com o menu aberto (J2, J3).

- [ ] 4.6 Prova técnica do menu pelo sistema (D14), janela J1, antes de qualquer código do `lume-menu`: um programa pequeno de prova (AG, em `out/worktrees/`, fora da imagem) que, com um jogo aberto, pausa pelo `GET_STATUS`/`PAUSE_TOGGLE`, manda `SIGSTOP` ao grupo, faz `pidfd_getfd` do fd do DRM da aplicação, lê o plano primário com `GETFB2`, faz commit de um buffer com o último quadro e um retângulo, espera 5 s, devolve o plano, `SIGCONT` e despausa. Casos, no GA36 (`sun4i-drm`) e no R36S (`rockchip`): RetroArch num jogo, um Port (LÖVE ou `sh`), RetroArch travado de propósito (`SIGSTOP` sem pausa). Conferir também o `ptrace_scope` do Yama e se o `lume-run` (usuário de jogo) consegue o `pidfd_getfd` sem capacidade extra. Verificação: o usuário vê o retângulo sobre o quadro e o jogo volta sem tela preta nem quadro trocado nos três casos e nos dois consoles; resultado anotado no `design.md` (D14: passou ou caminho de reserva) e nos guias de bring-up.

## 5. Configuração do RetroArch

- [ ] 5.1 `retroarch-lume.cfg` (D5, D9): `input_menu_toggle_gamepad_combo = "0"`, `savestate_thumbnail_enable = "true"`, `video_gpu_screenshot = "false"` e `auto_screenshot_filename = "true"`, com os comentários atualizados; `input_menu_toggle_btn` e o rótulo saem dos autoconfigs `GA36-MB Gamepad.cfg` e `R36S Gamepad.cfg`; `docs/FRONTEND.md` com os atalhos novos. Verificação: teste da configuração (as chaves fixadas, nenhum autoconfig com `input_menu_toggle_btn`); no aparelho, Start + Select chega ao jogo, a foto do save state aparece num cartão com a opção desligada no menu, e a foto do jogo sai sem a barra (J2, J3).

## 6. Build e provas nos consoles

- [ ] 6.1 Build dos pacotes mudados (`r36os-input`, `lume-launcher`, `retroarch`, `lume-retroarch-cfg`, `lume-games`) nas duas arquiteturas, um `r36os pkg` por vez sob a proteção de calor, e `r36os push` para o cartão. Verificação: os `.apk` novos com o `pkgrel` novo no repositório local e o `push` terminando com `ok`.
- [ ] 6.2 Janela J2 no GA36: Fn+A e Fn+Select não fazem nada; segurar o Fn mostra a dica com os acordes e o jogo continua, soltar fecha a dica sem abrir menu, R1 com a dica na tela grava o estado; um acorde solto rápido não abre o menu; o `fn_hold_ms` ajustado com o usuário (anotar o valor); Fn+B abre e fecha o menu do RetroArch com o jogo pausado; Start + Select chega ao jogo; o toque no Fn abre o menu do Lume com o jogo pausado pelo RetroArch e sem som, B ou outro toque volta e despausa; com o jogo já pausado antes, fechar o menu o mantém pausado; num Port, o menu aparece e o Port continua de onde parou ao voltar; com o RetroArch travado de propósito, o toque mostra o menu com "Forçar fechamento" em até 2 s e ele volta ao launcher; Reiniciar e Encerrar pedem confirmação com Não em foco, Sim reinicia ou encerra (SRAM gravada), "Menu do RetroArch" abre o menu dele; com o menu do Lume aberto, os botões não chegam ao jogo, e matar o `lume-run` devolve o controle em até 2 s; Fn+R1, mais jogo, Fn+L1 volta ao ponto salvo; aberto pelo slot 3, Fn+R1 grava no slot 3; depois de sair, "Save states" mostra a foto e o core certo; Fn+Y grava duas fotos diferentes em `ROMS/screenshots/`, sem a barra; Fn+X mostra e esconde a barra com os cinco campos, e ela continua ligada no jogo seguinte; carregador ligado aparece em até 5 s; Fn+Start continua saindo direto, também com o menu do Lume aberto; num jogo LÖVE ou num Port, segurar o Fn, Fn+R1 e Fn+Y só registram no log e Fn+Start encerra; `events.log` e log do `lume-run` sem erro; com a barra visível 5 min, o `lume-run` abaixo de 2% de um núcleo e o RSS dele anotado. Verificação: resultado anotado no `docs/BRINGUP-GA36.md`, sem nome de jogo.
- [ ] 6.3 Janela J3 no R36S, com o mesmo cartão: as mesmas provas da 6.2, mais a GPU com número na barra. Verificação: resultado anotado no `docs/BRINGUP-R36S.md`, sem nome de jogo; P-62 movido para "Concluídas" no `docs/PENDENCIAS.md` com o nome desta change, e o P-57 atualizado (atalho Fn+Y feito no RetroArch; a captura do sistema para qualquer programa continua aberta).

## Andamento (2026-11-17, sessão principal, sem subagentes, na branch `feature/virtual-gamepad` a pedido do usuário)

**Código feito, com testes de unidade passando** (nada marcado sem a prova no aparelho):
1.1 e 1.2 (marcadas); 2.1, 2.2 (`input.c`, perfis, `tests/unit/test_r36os_input.py`); 3.1, 3.3
e 4.2 (`lume-run`: `actions.rs`, `menu.rs`, `hud.rs`, `tests/run.rs` com RetroArch falso); 3.2
(`lume-ui`, `retroarch.toml`, catálogo); 4.3 e 4.5 num patch só (`0012-lume-hud-hint-menu.patch`:
`LUME_HUD`, `LUME_HINT` e `LUME_MENU`); 5.1 (cfg, autoconfigs, self-test da vm). 1.3: tela no
protótipo (`prototipo/jogo.html`) e tabela no `design-das-telas.md`; falta a aprovação do usuário.

**Prova na vm, só vm** (imagem `vm` com `r36os-input` r14, `retroarch` r115, `lume-launcher`
r30; QEMU sem virgl com display VNC num socket unix, capturas pelo QMP; o `lume-ui` não ajusta o
modo de vídeo nesse modo, então o jogo é aberto às cegas pelo `dev run`): barra com Fn+X e
continua no jogo seguinte; dica ao segurar o Fn, some ao soltar; toque abre o menu com o
RetroArch pausado pelo `PAUSE_TOGGLE` e fecha despausando (`GET_STATUS PLAYING`); confirmação
com Não em foco; Reiniciar com Sim reinicia e despausa; Fn+B abre e fecha o menu do RetroArch;
Fn+Y grava `ROMS/screenshots/<jogo>-<data>.png`; Fn+R1 grava `<jogo>.state` (slot 0) com a
foto `.state.png`; Fn+L1 carrega; Fn+Start encerra; textos em en, pt e es; RetroArch congelado
de propósito: o `lume-run` detecta o silêncio em 1 s, congela o grupo e "Forçar fechamento"
encerra (`end=force-close`), mas o menu não aparece (o widget é desenhado pelo próprio
RetroArch: limite do caminho de reserva, o D14 resolve). Capturas em `cache/tmp/shots/vm/`.

**Pendente:** 1.3 (aprovação), 4.1 e 4.6 (J1), 3.4 (depende da 4.6), 4.4 (depende da 4.1),
6.1 a 6.3 (build do console e janelas J2/J3). As tarefas 2.1, 2.2, 3.1, 3.2, 3.3, 4.2, 4.3,
4.5 e 5.1 só são marcadas depois da J2/J3.

## Workflow follow-up

- Arquivar a change depois das provas da J2 e da J3.
- Abrir a exploração da change do governor (tema 6, P-60, P-78), usando a barra para medir os perfis.
